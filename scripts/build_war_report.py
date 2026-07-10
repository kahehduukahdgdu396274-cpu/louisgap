#!/usr/bin/env python3
"""
build_war_report.py — 战报自动化脚本
1) 拉 OKX fills（limit=100）→ 开/平仓配对写入 trades.csv
2) 清除幽灵行（持仓中残缺、自动回填碎片）
3) 运行 generate_war_report_v3.py
"""
import csv
import hashlib
import hmac
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_vps_bot = "/home/admin/okx_bot"
if os.path.isdir(_vps_bot):
    sys.path.insert(0, _vps_bot)
    _default_base = _vps_bot
else:
    sys.path.insert(0, _root)
    _default_base = _root
try:
    from config import API_KEY, SECRET_KEY, PASSPHRASE  # noqa: F401
except ImportError:
    API_KEY = SECRET_KEY = PASSPHRASE = ""
CUTOFF_TS = 1782316800.0  # 2026-06-25 00:00:00 CST (Louis: 仅保留25号后数据)

_scripts = os.path.join(_root, "scripts")
if os.path.isdir(_scripts) and _scripts not in sys.path:
    sys.path.insert(0, _scripts)
if _root not in sys.path:
    sys.path.insert(0, _root)

_re_war = re.compile(r"str(003|006|009|011|012|014|015|016|017|019|020|021)(open|close)")
VALID_TRADE_STRATEGIES = frozenset({
    "003", "006", "009", "011", "012", "014",
    "015", "016", "017", "019", "020", "021"
})
POOL_MEMBERS = frozenset()
INDEPENDENT_STRATEGIES = VALID_TRADE_STRATEGIES
DEFAULT_EQ = {"003": 200, "006": 200, "009": 200, "011": 200, "012": 200, "014": 200}

BASE_URL = "https://openapi.okx.com"
SYMBOL = "BTC-USDT-SWAP"
BASE_DIR = _default_base
TRADES_CSV = os.path.join(BASE_DIR, "trades.csv")
TRADES_LOCKFILE = os.path.join(BASE_DIR, "trades.lock")
import fcntl
import argparse

# P19-2C A1: BWR 默认 readonly；维护写由 state_maintenance_worker 承担
BWR_READ_ONLY = True


def set_bwr_write_mode(repair: bool) -> None:
    global BWR_READ_ONLY
    BWR_READ_ONLY = not repair


def _bwr_skip_maintenance(op: str) -> bool:
    if BWR_READ_ONLY:
        print(f"[BWR_MODE] readonly skip {op}")
        return True
    return False


WAR_V3 = os.path.join(BASE_DIR, "generate_war_report_v3.py")
LOG_DIR = os.path.join(BASE_DIR, "logs")
WAR_REPORT = os.path.join(BASE_DIR, "hermes_latest_war_report.xlsx")
STATE_JSON = os.path.join(BASE_DIR, "state.json")
RESET_AFTER_FILE = os.path.join(BASE_DIR, "war_reset_after_ms.txt")
FILLS_LIMIT = 100
FILLS_MAX_PAGES = 15  # 最多 1500 条，降低长周期战报遗漏
CT_VAL = 0.01  # BTC-USDT-SWAP 合约面值

FIELDNAMES = [
    "开仓时间", "出场时间", "策略", "方向", "入场价", "出场价", "收益率%", "净盈亏",
    "状态", "持仓时间(分)", "原因", "K值", "D值", "ADX", "杠杆", "开仓张数",
    "策略权益金", "fee", "ordId", "数据源", "数据来源",
]


def strategy_from_cl_ord_id(cl):
    m = _re_war.search(cl or "")
    return m.group(1) if m else None


def leg_kind(cl):
    m = _re_war.search(cl or "")
    return m.group(2) if m else None


def log(msg):
    path = os.path.join(LOG_DIR, f"war_cron_{datetime.now().strftime('%Y%m%d')}.log")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} | {msg}"
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    if "WAR_ACC" in msg or msg.startswith("WAR_DONE"):
        with open(os.path.join(LOG_DIR, "war_accurate.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    print(line)


def sign(method, path, body=""):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    m = f"{ts}{method}{path}{body}"
    sig = base64.b64encode(
        hmac.new(SECRET_KEY.encode(), m.encode(), hashlib.sha256).digest()
    ).decode()
    return sig, ts


def okx_request(method, path, params=None):
    import requests

    body = json.dumps(params) if params is not None else ""
    sig, ts = sign(method, path, body)
    headers = {
        "OK-ACCESS-KEY": API_KEY,
        "OK-ACCESS-SIGN": sig,
        "OK-ACCESS-TIMESTAMP": ts,
        "OK-ACCESS-PASSPHRASE": PASSPHRASE,
        "Content-Type": "application/json",
        "x-simulated-trading": "1",
        "User-Agent": "okx-bot-war/1.0",
    }
    url = BASE_URL + path
    try:
        if method == "GET":
            resp = requests.get(url, headers=headers, params=params, timeout=15)
        else:
            resp = requests.post(url, headers=headers, data=body, timeout=15)
    except Exception as e:
        log(f"WAR_FAIL | 网络异常 HTTP | {path} | {e}")
        return None
    if resp.status_code >= 400:
        log(f"WAR_FAIL | HTTP {resp.status_code} | {method} {path}")
        return None
    return resp.json()


def fetch_fills(max_retries=3):
    """分页拉 fills；单页 limit=100，最多 FILLS_MAX_PAGES 页。"""
    all_fills = []
    after = None
    for page in range(1, FILLS_MAX_PAGES + 1):
        for attempt in range(1, max_retries + 1):
            wait = 2 ** attempt
            path = f"/api/v5/trade/fills?instId={SYMBOL}&limit={FILLS_LIMIT}"
            if after:
                path += f"&after={after}"
            data = okx_request("GET", path)
            if data is None:
                log(f"WAR_FAIL | fills p{page} 第{attempt}次HTTP错误, {wait}s后重试")
                time.sleep(wait)
                continue
            if data.get("code") != "0":
                log(f"WAR_FAIL | fills p{page} code={data.get('code')}")
                time.sleep(wait)
                continue
            batch = data.get("data", [])
            if not batch:
                log(f"[fills] 共{len(all_fills)}条 (pages={page - 1})")
                return all_fills
            all_fills.extend(batch)
            if len(batch) < FILLS_LIMIT:
                log(f"[fills] 共{len(all_fills)}条 (pages={page}, last={len(batch)})")
                return all_fills
            after = batch[-1].get("billId") or batch[-1].get("fillId")
            if not after:
                log(f"[fills] 共{len(all_fills)}条 (pages={page}, 无分页游标)")
                return all_fills
            break
        else:
            log("WAR_FAIL | fills 分页重试耗尽")
            return all_fills or None
    log(f"[fills] 共{len(all_fills)}条 (hit max pages={FILLS_MAX_PAGES})")
    return all_fills


def load_strategy_equity():
    eq = dict(DEFAULT_EQ)
    eq_path = os.path.join(BASE_DIR, "strategy_eq.json")
    if os.path.exists(eq_path):
        try:
            with open(eq_path, encoding="utf-8") as f:
                saved = json.load(f)
            for k, v in saved.items():
                eq[k] = float(v)
        except (OSError, ValueError, TypeError):
            pass
    return eq


def equity_after_close_value(sid, eq):
    """平仓后权益快照：全部独立策略键。"""
    return eq.get(sid, DEFAULT_EQ.get(sid, 200))


def load_equity_after_from_state():
    """state.json realized_legs → close_ord_id → equity_after。"""
    if not os.path.exists(STATE_JSON):
        return {}
    try:
        with open(STATE_JSON, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    out = {}
    for leg in state.get("realized_legs") or []:
        oid = (leg.get("close_ord_id") or "").strip()
        val = leg.get("equity_after")
        if oid and val is not None and val != "":
            try:
                out[oid] = round(float(val), 2)
            except (TypeError, ValueError):
                pass
    return out


def _rewind_equity_baseline(current_eq, closed_rows):
    """从当前权益倒推 reset 后首笔平仓前的权益基线。"""
    eq = {k: float(v) for k, v in current_eq.items()}
    for row in reversed(closed_rows):
        sid = (row.get("策略") or "").strip()
        try:
            pnl = float(row.get("净盈亏") or 0)
        except (TypeError, ValueError):
            pnl = 0.0
        if sid:
            eq[sid] = round(eq.get(sid, DEFAULT_EQ.get(sid, 200)) - pnl, 2)
    return eq


def _replay_equity_after_close(closed_rows, current_eq=None):
    """按出场时间 FIFO 回放，返回 close_ordId → 平仓后权益金。"""
    current_eq = current_eq or load_strategy_equity()
    baseline = _rewind_equity_baseline(current_eq, closed_rows)
    running = dict(baseline)
    replay_map = {}
    for row in sorted(closed_rows, key=_row_time_ms):
        sid = (row.get("策略") or "").strip()
        try:
            pnl = float(row.get("净盈亏") or 0)
        except (TypeError, ValueError):
            pnl = 0.0
        if sid:
            running[sid] = max(1, round(running.get(sid, DEFAULT_EQ.get(sid, 200)) + pnl, 2))
            replay_map[(row.get("ordId") or "").strip()] = running[sid]
    return replay_map, running


def sync_state_equity_after_from_replay(replay_map):
    """将回放后的 equity_after 写回 state.json realized_legs。"""
    if _bwr_skip_maintenance("sync_state_equity_after_from_replay"):
        return 0
    if not replay_map or not os.path.exists(STATE_JSON):
        return 0
    with open(STATE_JSON, encoding="utf-8") as f:
        state = json.load(f)
    updated = 0
    for leg in state.get("realized_legs") or []:
        cid = (leg.get("close_ord_id") or "").strip()
        if cid in replay_map:
            leg["equity_after"] = round(float(replay_map[cid]), 2)
            updated += 1
    if updated:
        tmp = STATE_JSON + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        os.replace(tmp, STATE_JSON)
        log(f"[equity] state.json 更新{updated}条 equity_after")
    return updated


def stamp_closed_equity(force=False):
    """为已平仓行写入平仓时权益金（默认按 reset 基线回放，不用错位快照）。"""
    if not os.path.exists(TRADES_CSV) or os.path.getsize(TRADES_CSV) == 0:
        return 0
    with open(TRADES_CSV, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return 0

    closed = [r for r in rows if (r.get("状态") or "").strip() == "已平仓"]
    if not closed:
        return 0

    replay_map, _running = _replay_equity_after_close(closed)
    sync_state_equity_after_from_replay(replay_map)

    stamped = 0
    for row in rows:
        if (row.get("状态") or "").strip() != "已平仓":
            continue
        if not force and str(row.get("策略权益金", "")).strip():
            continue
        oid = (row.get("ordId") or "").strip()
        val = replay_map.get(oid)
        if val is not None and val != "":
            row["策略权益金"] = round(float(val), 2)
            stamped += 1

    if stamped:
        with open(TRADES_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
            w.writeheader()
            for row in rows:
                w.writerow({k: row.get(k, "") for k in FIELDNAMES})
        log(f"[equity] 回填{stamped}条已平仓权益金(回放)")
    return stamped


def load_reset_after_ms():
    """战报重新开始的成交时间边界；小于该时间的历史 fills 不再回填。"""
    if not os.path.exists(RESET_AFTER_FILE):
        return 0
    try:
        return int(float(open(RESET_AFTER_FILE, encoding="utf-8").read().strip() or "0"))
    except (OSError, ValueError):
        log(f"[reset] reset marker 无效，忽略: {RESET_AFTER_FILE}")
        return 0


def _row_time_ms(row):
    """取行时间用于 reset 过滤：已平仓用出场时间，否则用开仓时间。"""
    ts = (row.get("出场时间") or row.get("开仓时间") or "").strip()
    if not ts:
        return 0
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return int(datetime.strptime(ts[:19], fmt).timestamp() * 1000)
        except ValueError:
            continue
    return 0


def purge_pre_reset_trades():
    """删除 reset 边界之前的 trades.csv 行（防止 00:10 cron 回填历史）。"""
    reset_ms = load_reset_after_ms()
    if reset_ms <= 0 or not os.path.exists(TRADES_CSV):
        return
    with open(TRADES_CSV, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return
    kept, removed = [], 0
    for row in rows:
        if _row_time_ms(row) < reset_ms:
            removed += 1
        else:
            kept.append(row)
    if removed:
        with open(TRADES_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
            w.writeheader()
            for row in kept:
                w.writerow({k: row.get(k, "") for k in FIELDNAMES})
        log(f"[reset] 删除{removed}条 reset 前成交，保留{len(kept)}条")


def _minute_key(ts_str):
    return (ts_str or "").strip()[:16]


def _parse_ts_seconds(ts_str):
    ts = (ts_str or "").strip()
    if not ts:
        return 0
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return int(datetime.strptime(ts[:19], fmt).timestamp())
        except ValueError:
            continue
    return 0


def _merge_trade_batch(batch):
    """合并同批次多笔成交为一条（加权均价、盈亏求和）。"""
    batch = sorted(batch, key=lambda r: _row_time_ms(r))
    total_qty = 0.0
    for row in batch:
        try:
            total_qty += float(row.get("开仓张数") or 0)
        except (TypeError, ValueError):
            pass
    if total_qty <= 0:
        return dict(batch[0])

    ep_sum = xp_sum = pnl_sum = fee_sum = 0.0
    et_min = ct_max = None
    for row in batch:
        try:
            qty = float(row.get("开仓张数") or 0)
            ep = float(row.get("入场价") or 0)
            xp = float(row.get("出场价") or 0)
            pnl = float(row.get("净盈亏") or 0)
            fee = float(row.get("fee") or 0)
        except (TypeError, ValueError):
            continue
        ep_sum += ep * qty
        xp_sum += xp * qty
        pnl_sum += pnl
        fee_sum += fee
        ot = row.get("开仓时间", "")
        ct = row.get("出场时间", "")
        if ot and (et_min is None or ot < et_min):
            et_min = ot
        if ct and (ct_max is None or ct > ct_max):
            ct_max = ct

    ep = round(ep_sum / total_qty, 2)
    xp = round(xp_sum / total_qty, 2)
    pnl_sum_r = round(pnl_sum, 4)
    ret_pct = net_return_pct(ep, total_qty, pnl_sum_r)

    hold_min = 0
    if et_min and ct_max:
        hold_min = max(0, int((_parse_ts_seconds(ct_max) - _parse_ts_seconds(et_min)) / 60))

    primary = next((r for r in batch if (r.get("ordId") or "").strip()), batch[0])
    merged = dict(primary)
    merged.update({
        "开仓时间": et_min or primary.get("开仓时间", ""),
        "出场时间": ct_max or primary.get("出场时间", ""),
        "入场价": ep,
        "出场价": xp,
        "收益率%": ret_pct,
        "净盈亏": pnl_sum_r,
        "开仓张数": round(total_qty, 4),
        "持仓时间(分)": hold_min,
        "fee": round(fee_sum, 4),
        "ordId": (primary.get("ordId") or "").strip(),
        "原因": "批次合并",
        "数据源": "state_json_batch",
    })
    return merged


def _should_merge_batch(batch, entry_spread_min=5):
    """同平仓分钟且开仓时间相差不超过 entry_spread_min 分钟，或开/平分钟完全一致。"""
    if len(batch) <= 1:
        return False
    open_minutes = {_minute_key(r.get("开仓时间", "")) for r in batch}
    close_minutes = {_minute_key(r.get("出场时间", "")) for r in batch}
    if len(open_minutes) == 1 and len(close_minutes) == 1:
        return True
    ets = [_parse_ts_seconds(r.get("开仓时间", "")) for r in batch]
    ets = [x for x in ets if x > 0]
    if not ets:
        return False
    spread_min = (max(ets) - min(ets)) / 60
    return spread_min <= entry_spread_min


def _cluster_batches(batch, entry_spread_min=5):
    """同平仓分钟内，再按开仓时间聚类；开平分钟完全一致或开仓相差≤阈值才合并。"""
    if len(batch) <= 1:
        return [batch]
    open_groups = {}
    for row in batch:
        om = _minute_key(row.get("开仓时间", ""))
        open_groups.setdefault(om, []).append(row)
    if len(open_groups) == 1:
        return [batch]
    clusters = []
    for rows in open_groups.values():
        if _should_merge_batch(rows, entry_spread_min):
            clusters.append(rows)
        else:
            clusters.extend([[r] for r in rows])
    return clusters


def collapse_burst_trades(rows, entry_spread_min=5):
    """合并：平仓时间相同(到分钟)且开仓时间相同/相近的多笔成交。"""
    closed = [r for r in rows if r.get("状态") == "已平仓"]
    other = [r for r in rows if r.get("状态") != "已平仓"]
    if not closed:
        return rows, 0

    groups = {}
    order = []
    for row in closed:
        key = (
            row.get("策略", ""),
            row.get("方向", ""),
            _minute_key(row.get("出场时间", "")),
        )
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)

    merged_closed, collapsed = [], 0
    for key in order:
        for batch in _cluster_batches(groups[key], entry_spread_min):
            if len(batch) > 1 and _should_merge_batch(batch, entry_spread_min):
                merged_closed.append(_merge_trade_batch(batch))
                collapsed += len(batch) - 1
                log(
                    f"[batch] 合并{len(batch)}笔→1 "
                    f"{key[0]} 开{_minute_key(batch[0].get('开仓时间',''))} "
                    f"平{key[2]} pnl="
                    f"{sum(float(r.get('净盈亏') or 0) for r in batch):.2f}"
                )
            else:
                merged_closed.extend(batch)

    # 第二轮：开仓时间相同(到分钟)，且平仓时间相差≤阈值 → 合并
    open_groups, open_order = {}, []
    for row in merged_closed:
        key = (row.get("策略", ""), row.get("方向", ""), _minute_key(row.get("开仓时间", "")))
        if key not in open_groups:
            open_groups[key] = []
            open_order.append(key)
        open_groups[key].append(row)

    final_closed, collapsed2 = [], 0
    for key in open_order:
        batch = open_groups[key]
        cts = [_parse_ts_seconds(r.get("出场时间", "")) for r in batch]
        cts = [x for x in cts if x > 0]
        close_spread = (max(cts) - min(cts)) / 60 if len(cts) >= 2 else 0
        if len(batch) > 1 and close_spread <= entry_spread_min:
            final_closed.append(_merge_trade_batch(batch))
            collapsed2 += len(batch) - 1
            log(
                f"[batch/open] 合并{len(batch)}笔→1 {key[0]} "
                f"开{key[2]} pnl="
                f"{sum(float(r.get('净盈亏') or 0) for r in batch):.2f}"
            )
        else:
            final_closed.extend(batch)

    collapsed += collapsed2
    final_closed.sort(key=_row_time_ms)
    return final_closed + other, collapsed


def _row_to_leg(row):
    et = _parse_ts_seconds(row.get("开仓时间", ""))
    ct = _parse_ts_seconds(row.get("出场时间", ""))
    return {
        "strategy_id": row.get("策略", ""),
        "direction": row.get("方向", "long"),
        "entry_price": float(row.get("入场价") or 0),
        "exit_price": float(row.get("出场价") or 0),
        "qty": float(row.get("开仓张数") or 0),
        "entry_time": et,
        "close_time": ct,
        "open_ord_id": "",
        "close_ord_id": (row.get("ordId") or "").strip(),
        "fee": float(row.get("fee") or 0),
        "net_pnl": float(row.get("净盈亏") or 0),
        "reason": row.get("原因") or "批次合并",
    }


def collapse_burst_realized_legs(legs, entry_spread_min=5):
    """state.json realized_legs：按 OKX 同策略同开仓同平仓分钟合并。"""
    from okx_close_aggregate import collapse_okx_close_legs  # noqa: E402

    return collapse_okx_close_legs(legs or [])


def apply_burst_collapse_to_trades(entry_spread_min=5):
    """对 trades.csv 已平仓行按 OKX 同策略平仓规则合并并重算权益金。"""
    if not os.path.exists(TRADES_CSV) or os.path.getsize(TRADES_CSV) == 0:
        return 0
    with open(TRADES_CSV, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    from okx_close_aggregate import collapse_okx_close_rows  # noqa: E402

    merged, collapsed = collapse_okx_close_rows(rows)
    if collapsed <= 0:
        return 0
    closed = [r for r in merged if r.get("状态") == "已平仓"]
    replay_map, _ = _replay_equity_after_close(closed)
    sync_state_equity_after_from_replay(replay_map)
    for row in merged:
        if row.get("状态") == "已平仓":
            oid = (row.get("ordId") or "").strip()
            if oid in replay_map:
                row["策略权益金"] = replay_map[oid]
    with open(TRADES_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        w.writeheader()
        for row in merged:
            w.writerow({k: row.get(k, "") for k in FIELDNAMES})
    log(f"[batch] trades.csv 合并{collapsed}笔，剩余已平仓{len(closed)}")
    return collapsed


def dedup_same_moment_trades():
    """剔除完全重复成交：策略/开平时间/方向/价格/张数/盈亏一致，仅 ordId 不同。"""
    if not os.path.exists(TRADES_CSV) or os.path.getsize(TRADES_CSV) == 0:
        return 0
    with open(TRADES_CSV, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    seen = {}
    kept, removed = [], 0
    for row in rows:
        if row.get("状态") != "已平仓":
            kept.append(row)
            continue
        key = (
            row.get("策略", ""),
            row.get("开仓时间", ""),
            row.get("出场时间", ""),
            row.get("方向", ""),
            row.get("入场价", ""),
            row.get("出场价", ""),
            row.get("开仓张数", ""),
            row.get("净盈亏", ""),
        )
        if key in seen:
            removed += 1
            log(f"[dedup_moment] 删除重复成交 {row.get('策略')} ordId={row.get('ordId')} (同{seen[key]})")
            continue
        seen[key] = row.get("ordId", "")
        kept.append(row)
    if removed:
        with open(TRADES_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
            w.writeheader()
            for row in kept:
                w.writerow({k: row.get(k, "") for k in FIELDNAMES})
        log(f"[dedup_moment] 删除{removed}条同刻重复成交")
    return removed


def dedup_trades_csv():
    """按 ordId 去重：已平仓看 close ordId，持仓中看 (策略, ordId)。"""
    if _bwr_skip_maintenance("dedup_trades_csv"):
        return
    if not os.path.exists(TRADES_CSV) or os.path.getsize(TRADES_CSV) == 0:
        return
    with open(TRADES_CSV, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return
    seen_closed, seen_open = set(), set()
    kept, removed = [], 0
    for row in rows:
        status = (row.get("状态") or "").strip()
        oid = (row.get("ordId") or "").strip()
        if status == "已平仓":
            if not oid or oid in seen_closed:
                removed += 1
                continue
            seen_closed.add(oid)
        elif status == "持仓中":
            key = (row.get("策略", ""), oid)
            if not oid or key in seen_open:
                removed += 1
                continue
            seen_open.add(key)
        kept.append(row)
    if removed:
        with open(TRADES_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
            w.writeheader()
            for row in kept:
                w.writerow({k: row.get(k, "") for k in FIELDNAMES})
        log(f"[dedup] 删除{removed}条重复成交，保留{len(kept)}条")


def ms_to_str(ms):
    if not ms or ms == "0":
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return datetime.fromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d %H:%M:%S")


def aggregate_ord_fills(fs):
    total_sz = sum(float(x.get("fillSz", 0)) for x in fs)
    if total_sz <= 0:
        return None
    vwap = sum(float(x.get("fillPx", 0)) * float(x.get("fillSz", 0)) for x in fs) / total_sz
    pnl = sum(float(x.get("fillPnl", 0) or 0) for x in fs)
    fee = sum(float(x.get("fee", 0) or 0) for x in fs)
    side = fs[0].get("side", "")
    cl = fs[0].get("clOrdId", "") or ""
    return {
        "ordId": fs[0].get("ordId", ""),
        "clOrdId": cl,
        "strategy": strategy_from_cl_ord_id(cl),
        "kind": leg_kind(cl),
        "fillTime": int(fs[0].get("fillTime", 0)),
        "time_str": ms_to_str(fs[0].get("fillTime", "0")),
        "side": side,
        "pos_side": (fs[0].get("posSide") or "").lower(),
        "direction": "long" if side == "buy" else "short",
        "avg_px": round(vwap, 2),
        "total_sz": round(total_sz, 4),
        "pnl": round(pnl, 4),
        "fee": round(fee, 4),
    }


def calc_pnl_from_prices(direction, entry_px, exit_px, sz):
    try:
        ep, xp, s = float(entry_px), float(exit_px), float(sz)
    except (TypeError, ValueError):
        return None
    if ep <= 0 or xp <= 0 or s <= 0:
        return None
    if direction in ("long", "多"):
        return round((xp - ep) * s * CT_VAL, 4)
    return round((ep - xp) * s * CT_VAL, 4)


def net_return_pct(entry_px, sz, net_pnl):
    """净收益率%：与净盈亏同号（按名义本金=入场价×张数×面值）。"""
    try:
        ep, s, pnl = float(entry_px), float(sz), float(net_pnl)
    except (TypeError, ValueError):
        return ""
    denom = ep * s * CT_VAL
    if denom <= 0:
        return ""
    return round(pnl / denom * 100, 4)


def sync_return_pct_row(row):
    """战报展示用：收益率% 必须与净盈亏方向一致。"""
    if row.get("状态") != "已平仓":
        return
    ret = net_return_pct(row.get("入场价"), row.get("开仓张数"), row.get("净盈亏"))
    if ret != "":
        row["收益率%"] = ret


def sync_all_return_pct(rows):
    for row in rows:
        sync_return_pct_row(row)


def attributed_pnl_from_prices(direction, entry_px, exit_px, sz, fee=0):
    """策略归因盈亏：价差×张数×面值 + 手续费（net_mode 下替代账户 fillPnl）。"""
    gross = calc_pnl_from_prices(direction, entry_px, exit_px, sz)
    if gross is None:
        return None
    try:
        f = float(fee or 0)
    except (TypeError, ValueError):
        f = 0.0
    return round(gross + f, 4)


def _pnl_ret_mismatch(direction, ret_pct, pnl, entry_px=None, exit_px=None, sz=None):
    """价差毛利与净盈亏符号明显矛盾（排除手续费吃掉微利）。"""
    try:
        p = float(pnl or 0)
    except (TypeError, ValueError):
        return False
    if entry_px is not None and exit_px is not None and sz is not None:
        gross = calc_pnl_from_prices(direction, entry_px, exit_px, sz)
        if gross is None:
            return False
        if abs(gross) < 0.5:
            return False
        return (gross > 0.05 and p < -0.05) or (gross < -0.05 and p > 0.05)
    try:
        ret = float(ret_pct or 0)
    except (TypeError, ValueError):
        return False
    if abs(ret) < 0.05 or abs(p) < 0.05:
        return False
    d = (direction or "").strip()
    if d in ("long", "多"):
        return (ret > 0 and p < 0) or (ret < 0 and p > 0)
    if d in ("short", "空"):
        # short: ret>0 盈利 pnl>0; ret<0 亏损 pnl<0 → 符号一致则不矛盾
        return False
    return False


def fetch_ord_fill_summary(ord_id):
    """按 ordId 拉 OKX 成交聚合（与 api.fetch_fills_by_ordId 口径一致）。"""
    if not ord_id:
        return None
    paths = [
        f"/api/v5/trade/fills?instId={SYMBOL}&ordId={ord_id}",
        f"/api/v5/trade/fills?instId={SYMBOL}&limit=100",
    ]
    for path in paths:
        data = okx_request("GET", path)
        if not data or data.get("code") != "0":
            continue
        matched = [f for f in (data.get("data") or []) if f.get("ordId") == ord_id]
        if not matched:
            continue
        total_sz = sum(float(f.get("fillSz", 0) or 0) for f in matched)
        if total_sz <= 0:
            continue
        total_px = sum(float(f.get("fillPx", 0) or 0) * float(f.get("fillSz", 0) or 0) for f in matched)
        total_pnl = sum(float(f.get("fillPnl", 0) or 0) for f in matched)
        total_fee = sum(float(f.get("fee", 0) or 0) for f in matched)
        cl = (matched[0].get("clOrdId") or "").strip()
        fill_ms = int(matched[0].get("fillTime", 0) or 0)
        return {
            "avgPx": round(total_px / total_sz, 2),
            "totalSz": round(total_sz, 4),
            "fillPnl": round(total_pnl, 4),
            "fee": round(total_fee, 4),
            "fillTime": fill_ms,
            "clOrdId": cl,
            "strategy": strategy_from_cl_ord_id(cl),
            "kind": leg_kind(cl),
        }
    return None


def _close_ord_candidates_from_fills(fills, sid, after_ms=0):
    """从 fills 聚合某策略在 after_ms 之后的全部平仓 ord。"""
    by_ord = {}
    for f in fills or []:
        ft = int(f.get("fillTime", 0) or 0)
        if after_ms and ft < after_ms:
            continue
        cl = f.get("clOrdId", "") or ""
        if strategy_from_cl_ord_id(cl) != sid or leg_kind(cl) != "close":
            continue
        by_ord.setdefault(f.get("ordId", ""), []).append(f)
    out = []
    for fs in by_ord.values():
        leg = aggregate_ord_fills(fs)
        if leg:
            out.append(leg)
    out.sort(key=lambda x: x["fillTime"])
    return out


def build_fifo_exact_legs(fills=None):
    """按策略 FIFO：开仓入栈，平仓匹配首张数相同的开仓（OKX 真源）。"""
    fills = fills if fills is not None else fetch_fills()
    reset_ms = load_reset_after_ms()
    if reset_ms > 0:
        fills = [f for f in (fills or []) if int(f.get("fillTime", 0) or 0) >= reset_ms]
    if not fills:
        return []

    by_ord = {}
    for f in fills:
        oid = f.get("ordId", "")
        if oid:
            by_ord.setdefault(oid, []).append(f)

    events = []
    for fs in by_ord.values():
        leg = aggregate_ord_fills(fs)
        if leg and leg["strategy"] in VALID_TRADE_STRATEGIES and leg["kind"] in ("open", "close"):
            events.append(leg)
    events.sort(key=lambda x: x["fillTime"])

    stacks = {sid: [] for sid in VALID_TRADE_STRATEGIES}
    out = []
    for ev in events:
        sid = ev["strategy"]
        if ev["kind"] == "open":
            stacks[sid].append(ev)
            continue
        close_sz = float(ev["total_sz"] or 0)
        match_i = None
        for i, op in enumerate(stacks[sid]):
            if abs(float(op["total_sz"] or 0) - close_sz) < 1e-4:
                match_i = i
                break
        if match_i is None:
            log(f"[fifo] {sid} close sz={close_sz} 无匹配开仓 ord={ev['ordId']}")
            continue
        op = stacks[sid].pop(match_i)
        ep, xp = float(op["avg_px"]), float(ev["avg_px"])
        direction = op["direction"]
        fee = float(ev.get("fee") or 0)
        attr = attributed_pnl_from_prices(direction, ep, xp, close_sz, fee)
        out.append({
            "strategy_id": sid,
            "direction": direction,
            "entry_price": ep,
            "exit_price": xp,
            "qty": close_sz,
            "entry_time": float(op["fillTime"]) / 1000.0,
            "close_time": float(ev["fillTime"]) / 1000.0,
            "open_ord_id": op["ordId"],
            "close_ord_id": ev["ordId"],
            "fee": fee,
            "net_pnl": attr if attr is not None else ev.get("pnl", 0),
            "reason": "OKX开平配对",
        })
    return out


def _leg_interval(leg):
    try:
        et = float(leg.get("entry_time") or 0)
        ct = float(leg.get("close_time") or 0)
    except (TypeError, ValueError):
        return 0, 0
    return et, ct


def _intervals_overlap(iv_a, iv_b):
    ae, ac = iv_a
    be, bc = iv_b
    if ac <= 0 or bc <= 0:
        return False
    # 顺序交易（后开仓 ≥ 前平仓）不算重叠，避免误删合法成交
    if be >= ac - 1.0 or ae >= bc - 1.0:
        return False
    return ae < bc and be < ac


TRUSTED_REPAIR_REASONS = frozenset({"对账回补"})
# OKX fills 分页窗口外仍可信的归因（≥ CUTOFF_TS，非 OKX回补）
FILLS_WINDOW_TRUSTED_REASONS = frozenset(
    {
        "OKX开平配对",
        "bot平仓",
        "对账平仓回补",
        "对账回补",
        "对账修正(fills真源)",
        "策略归因",
    }
)
UNTRUSTED_LEG_REASONS = frozenset({"OKX回补"})
# 对账 LIFO 占位 open_ord_id：不可查 OKX fills，但平仓 ordId 仍须校验
SYNTHETIC_OPEN_ORD_IDS = frozenset({"okx_net_pad", "sync_snapshot"})


def is_synthetic_open_ord(open_oid: str) -> bool:
    oid = (open_oid or "").strip()
    return not oid or oid in SYNTHETIC_OPEN_ORD_IDS or oid.startswith("state_")


def prune_synthetic_tranches(base_dir=None) -> int:
    """剔除 state tranches 中 okx_net_pad 等不可信占位腿（不覆盖 bot position 文件）。"""
    if _bwr_skip_maintenance("prune_synthetic_tranches"):
        return 0
    try:
        from position_state import load_state, save_state, compute_net_position
    except ImportError:
        return 0
    base_dir = base_dir or BASE_DIR
    state = load_state(base_dir)
    tranches = state.get("tranches") or []
    kept = [
        tr
        for tr in tranches
        if not is_synthetic_open_ord(tr.get("open_ord_id") or "")
    ]
    removed = len(tranches) - len(kept)
    if removed <= 0:
        return 0
    state["tranches"] = kept
    state["net_position"] = compute_net_position(kept)
    save_state(state, base_dir)
    log(f"[tranche] 剔除 {removed} 条合成 open_ord 幽灵 tranche")
    return removed


def _normalize_ord_id(ord_id: str) -> str:
    oid = (ord_id or "").strip()
    if "#" in oid:
        oid = oid.split("#", 1)[0]
    return oid


def _leg_fills_window_trusted(leg, close_meta=None) -> bool:
    """OKX demo fills 仅保留近期窗口；cutoff 后 bot/对账可信腿不因 ord API 过期被剔除。"""
    reason = (leg.get("reason") or "").strip()
    if reason in UNTRUSTED_LEG_REASONS or reason not in FILLS_WINDOW_TRUSTED_REASONS:
        return False
    sid = (leg.get("strategy_id") or "").strip()
    if sid not in VALID_TRADE_STRATEGIES:
        return False
    close_oid = _normalize_ord_id(leg.get("close_ord_id") or "")
    if not close_oid:
        return False
    ct = float(leg.get("close_time", 0) or 0)
    if ct < CUTOFF_TS:
        return False
    reset_ms = load_reset_after_ms()
    if reset_ms > 0 and ct * 1000 < reset_ms:
        return False
    if close_meta is not None:
        if close_meta.get("strategy") != sid or close_meta.get("kind") != "close":
            return False
        open_oid = (leg.get("open_ord_id") or "").strip()
        if is_synthetic_open_ord(open_oid):
            return True
        return bool(open_oid)
    open_oid = (leg.get("open_ord_id") or "").strip()
    if is_synthetic_open_ord(open_oid):
        return True
    return bool(open_oid)


def verify_realized_leg(leg, fetch_fn=None, strict_open=True):
    """校验 realized_leg：close/open ordId 的 clOrdId 必须归属该策略且开平类型正确。"""
    if (leg.get("reason") or "") in TRUSTED_REPAIR_REASONS:
        sid = (leg.get("strategy_id") or "").strip()
        if sid in VALID_TRADE_STRATEGIES and (leg.get("open_ord_id") or "").strip():
            return True, "repair_trusted"
    fetch_fn = fetch_fn or fetch_ord_fill_summary
    sid = (leg.get("strategy_id") or "").strip()
    if sid not in VALID_TRADE_STRATEGIES:
        return False, "bad_sid"
    close_oid = _normalize_ord_id(leg.get("close_ord_id") or "")
    if not close_oid:
        return False, "no_close"
    close_meta = fetch_fn(close_oid)
    if not close_meta:
        if _leg_fills_window_trusted(leg, None):
            return True, "fills_window_trusted"
        return False, "close_fill_missing"
    if close_meta.get("strategy") != sid:
        return False, "close_sid_mismatch"
    if close_meta.get("kind") != "close":
        return False, "close_kind"
    open_oid = (leg.get("open_ord_id") or "").strip()
    if is_synthetic_open_ord(open_oid):
        return True, "synthetic_open"
    if strict_open and not open_oid:
        return False, "no_open"
    if open_oid:
        open_meta = fetch_fn(open_oid)
        if not open_meta:
            if _leg_fills_window_trusted(leg, close_meta):
                return True, "fills_window_open_aged"
            if not strict_open:
                return True, "close_only_verified"
            return False, "open_fill_missing"
        if open_meta.get("strategy") != sid:
            return False, "open_sid_mismatch"
        if open_meta.get("kind") != "open":
            return False, "open_kind"
    return True, "ok"


def compute_prune_inflated_legs(state: dict) -> tuple[int, int, list]:
    """只读计算 prune_inflated（单源真值，worker/reconcile 共用）。"""
    legs = state.get("realized_legs") or []
    before = len(legs)
    filtered = [
        leg
        for leg in legs
        if (leg.get("reason") or "") not in UNTRUSTED_LEG_REASONS
    ]
    if len(filtered) == before:
        return before, before, filtered

    filtered = dedupe_realized_legs(filtered)
    filtered, _ = prune_unverified_legs(filtered, strict_open=False)
    filtered = prune_overlap_independent_legs(filtered)
    filtered = [
        leg
        for leg in filtered
        if float(leg.get("close_time", 0) or 0) >= CUTOFF_TS
        or float(leg.get("close_time", 0) or 0) == 0
    ]
    return before, len(filtered), filtered


def prune_inflated_state_legs(base_dir=None):
    """剔除 OKX回补 膨胀腿（cron/backfill 历史污染），保留 bot 可信归因。"""
    try:
        from position_state import load_state, save_state
    except ImportError:
        return 0, 0

    base_dir = base_dir or BASE_DIR
    state = load_state(base_dir)
    before, after, filtered = compute_prune_inflated_legs(state)
    if _bwr_skip_maintenance("prune_inflated_state_legs"):
        return before, after

    if before == after:
        return before, after

    state["realized_legs"] = filtered
    save_state(state, base_dir)
    log(f"[prune_inflated] realized_legs {before}→{after}（剔除 OKX回补）")
    return before, after


def prune_unverified_legs(legs, fetch_fn=None, strict_open=True):
    """剔除 OKX clOrdId 无法印证的幽灵腿。"""
    kept, removed = [], []
    for leg in legs or []:
        ok, reason = verify_realized_leg(leg, fetch_fn, strict_open=strict_open)
        if ok:
            kept.append(leg)
        else:
            removed.append(leg)
            log(
                f"[verify] 剔除幽灵腿 {leg.get('strategy_id')} "
                f"close={leg.get('close_ord_id')} reason={reason}"
            )
    return kept, removed


def prune_overlap_independent_legs(legs):
    """按 close_ord_id 去重；顺序成交不再按时间窗互删（避免误删战报行）。"""
    best: dict[str, dict] = {}
    orphans: list[dict] = []
    for leg in legs or []:
        cid = (leg.get("close_ord_id") or "").strip()
        if not cid:
            orphans.append(leg)
            continue
        prev = best.get(cid)
        if not prev or float(leg.get("close_time") or 0) >= float(prev.get("close_time") or 0):
            best[cid] = leg
    kept_all = list(best.values()) + orphans
    kept_all.sort(key=lambda x: float(x.get("close_time", 0) or 0))
    return kept_all


def round_trip_to_realized_leg(trip):
    """OKX 开平配对 → state.json realized_leg。"""
    try:
        et = datetime.strptime((trip.get("开仓时间") or "")[:19], "%Y-%m-%d %H:%M:%S").timestamp()
        ct = datetime.strptime((trip.get("出场时间") or "")[:19], "%Y-%m-%d %H:%M:%S").timestamp()
    except ValueError:
        return None
    open_oid = (trip.get("_open_ordId") or "").strip()
    close_oid = (trip.get("ordId") or "").strip()
    if not close_oid:
        return None
    return {
        "strategy_id": trip.get("策略"),
        "direction": trip.get("方向", "long"),
        "entry_price": trip.get("入场价"),
        "exit_price": trip.get("出场价"),
        "qty": trip.get("开仓张数"),
        "entry_time": et,
        "close_time": ct,
        "open_ord_id": open_oid,
        "close_ord_id": close_oid,
        "fee": trip.get("fee", 0),
        "net_pnl": trip.get("净盈亏"),
        "reason": "OKX开平配对",
    }


def merge_okx_legs_into_state(legs, fills=None):
    """用 OKX 开平配对覆盖 reset 后同 close_ord_id 的 state 腿（真源优先）。"""
    fills = fills if fills is not None else fetch_fills()
    if not fills:
        return legs, 0
    reset_ms = load_reset_after_ms()
    if reset_ms > 0:
        fills = [f for f in fills if int(f.get("fillTime", 0) or 0) >= reset_ms]
    okx_legs = []
    for trip in pair_round_trips(fills):
        leg = round_trip_to_realized_leg(trip)
        if leg:
            ct = float(leg.get("close_time", 0) or 0)
            if 0 < ct < CUTOFF_TS:
                log(f"[merge_okx] 过滤 OKX配对旧leg {leg.get('strategy_id')} ct={ct}")
                continue
            okx_legs.append(leg)
    if len(okx_legs) < len([l for l in [round_trip_to_realized_leg(t) for t in pair_round_trips(fills)] if l]):
        log("[merge_okx] CUTOFF_TS 过滤了历史leg")
    if not okx_legs:
        return legs, 0

    okx_by_close = {(l.get("close_ord_id") or "").strip(): l for l in okx_legs}
    out, replaced = [], 0
    seen_close = set()
    for leg in legs:
        cid = (leg.get("close_ord_id") or "").strip()
        if cid in okx_by_close:
            if cid not in seen_close:
                out.append(okx_by_close[cid])
                seen_close.add(cid)
                replaced += 1
            continue
        out.append(leg)
    existing_open_ids = {(l.get("open_ord_id") or "").strip() for l in legs}
    for cid, leg in okx_by_close.items():
        if cid not in seen_close:
            # 硬性截断：禁止回填6月15日之前的leg
            ct = float(leg.get("close_time", 0) or 0)
            if ct >= 1781452800.0:
                ooid = (leg.get("open_ord_id") or "").strip()
                if ooid and ooid in existing_open_ids:
                    log(f"[merge_okx] 跳过重复open_ord_id={ooid[:12]} (state已有)")
                    continue
                out.append(leg)
                if ooid:
                    existing_open_ids.add(ooid)
                replaced += 1
    out.sort(key=lambda x: float(x.get("close_time", 0) or 0))
    return out, replaced


def filter_valid_realized_legs(
    legs,
    fills=None,
    *,
    supplement_fifo=False,
    collapse_batch=False,
    repair_pnl=False,
):
    """保守修正：dedupe → 校验剔除幽灵腿；FIFO 补充与批次合并仅手动修复时开启。"""
    raw_n = len(legs or [])
    legs = dedupe_realized_legs(legs or [])
    if repair_pnl:
        legs, _ = repair_realized_leg_pnls(legs)

    fifo_n = 0
    if supplement_fifo:
        fills = fills if fills is not None else fetch_fills()
        fifo_legs = build_fifo_exact_legs(fills)
        fifo_n = len(fifo_legs)
        if fifo_legs:
            have = {(l.get("close_ord_id") or "").strip() for l in legs}
            added = 0
            for fl in fifo_legs:
                cid = (fl.get("close_ord_id") or "").strip()
                if cid and cid not in have:
                    ok, _ = verify_realized_leg(fl, strict_open=bool(fl.get("open_ord_id")))
                    if ok:
                        legs.append(fl)
                        have.add(cid)
                        added += 1
            if added:
                legs = dedupe_realized_legs(legs)
                log(f"[fifo] 补充 {added} 条已校验缺失成交")

    verified, removed_verify = prune_unverified_legs(legs, strict_open=False)
    overlapped = prune_overlap_independent_legs(verified)
    batch_n = 0
    if collapse_batch:
        collapsed, batch_n = collapse_burst_realized_legs(overlapped)
    else:
        collapsed = overlapped
    return collapsed, {
        "fifo": fifo_n,
        "pruned_verify": len(removed_verify),
        "batch_collapsed": batch_n,
        "before": raw_n,
        "after": len(collapsed),
    }


def _leg_reason_rank(leg):
    reason = (leg.get("reason") or "").strip()
    if reason in ("对账修正(fills真源)",):
        # 人工按 fills 真源逐笔核对后的修正，任何自动管线不得覆盖
        return 4
    if reason in ("对账平仓回补", "策略归因", "bot平仓"):
        return 3
    if reason in ("OKX回补", "OKX开平配对", "OKX同策略平仓合并"):
        return 2
    if reason in ("批次合并",):
        return 1
    return 0


def merge_realized_leg(existing, incoming):
    """同 close_ord_id：按 OKX 规则聚合 fill（加权价、盈亏求和）；否则保留高优先级归因。"""
    eid = (existing.get("close_ord_id") or "").strip()
    iid = (incoming.get("close_ord_id") or "").strip()
    if eid and eid == iid:
        from okx_close_aggregate import merge_okx_close_legs  # noqa: E402

        merged = merge_okx_close_legs(existing, incoming)
        keep_existing_meta = _leg_reason_rank(existing) >= _leg_reason_rank(incoming)
        if keep_existing_meta and (existing.get("reason") or "").strip():
            merged["reason"] = existing["reason"]
        return merged

    out = dict(existing)
    inc = dict(incoming)
    keep_existing_meta = _leg_reason_rank(existing) >= _leg_reason_rank(incoming)

    for key in ("strategy_id", "direction", "reason"):
        if keep_existing_meta and (existing.get(key) or "").strip():
            out[key] = existing[key]
        elif (inc.get(key) or "").strip():
            out[key] = inc[key]

    for key in (
        "entry_price",
        "exit_price",
        "qty",
        "fee",
        "net_pnl",
        "entry_time",
        "close_time",
        "open_ord_id",
        "close_ord_id",
    ):
        ev = existing.get(key)
        iv = inc.get(key)
        if ev in (None, "") and iv not in (None, ""):
            out[key] = iv
        elif key in ("entry_price", "exit_price", "qty", "fee") and iv not in (
            None,
            "",
        ):
            try:
                if abs(float(iv) - float(ev or 0)) >= 0.01 and not keep_existing_meta:
                    out[key] = iv
            except (TypeError, ValueError):
                out[key] = iv
        elif key == "net_pnl" and iv not in (None, ""):
            # net_pnl 只允许高优先级覆盖低优先级，不允许 OKX raw fillPnl 反向覆盖策略归因
            if not keep_existing_meta:
                out[key] = iv
    return out


def merge_realized_legs_by_ord_id(existing_legs, incoming_legs):
    """按 close_ord_id 合并腿列表（不整表覆盖）。"""
    by_close: dict[str, dict] = {}
    no_id = []
    for leg in existing_legs or []:
        cid = (leg.get("close_ord_id") or "").strip()
        if cid:
            by_close[cid] = dict(leg)
        else:
            no_id.append(dict(leg))

    added = updated = skipped = 0
    for leg in incoming_legs or []:
        cid = (leg.get("close_ord_id") or "").strip()
        if not cid:
            skipped += 1
            continue
        if cid not in by_close:
            by_close[cid] = dict(leg)
            added += 1
            continue
        merged = merge_realized_leg(by_close[cid], leg)
        if merged != by_close[cid]:
            by_close[cid] = merged
            updated += 1
        else:
            skipped += 1

    merged = sorted(by_close.values(), key=lambda x: float(x.get("close_time", 0) or 0))
    return no_id + merged, {
        "added": added,
        "updated": updated,
        "skipped": skipped,
        "total": len(merged) + len(no_id),
    }


def dedupe_realized_legs(legs):
    """按 close_ord_id 去重；同 id 用 merge_realized_leg 智能合并。"""
    best = {}
    orphans = []
    for leg in legs or []:
        cid = (leg.get("close_ord_id") or "").strip()
        if not cid:
            orphans.append(leg)
            continue
        prev = best.get(cid)
        if not prev:
            best[cid] = dict(leg)
            continue
        if float(leg.get("close_time", 0) or 0) >= float(prev.get("close_time", 0) or 0):
            best[cid] = merge_realized_leg(prev, leg)
        else:
            best[cid] = merge_realized_leg(leg, prev)
    return sorted(best.values(), key=lambda x: float(x.get("close_time", 0) or 0)) + orphans


def load_known_close_ord_ids():
    """state.json + trades.csv 已记账的平仓 ordId（防 FIFO 全量覆盖）。"""
    known = set()
    if os.path.exists(STATE_JSON):
        try:
            with open(STATE_JSON, encoding="utf-8") as f:
                state = json.load(f)
            for leg in state.get("realized_legs") or []:
                cid = (leg.get("close_ord_id") or "").strip()
                if cid:
                    known.add(cid)
        except (OSError, json.JSONDecodeError):
            pass
    close_ids, _ = load_existing_keys()
    known.update(close_ids)
    return known


def prune_overclose_legs(legs, fetch_fn=None):
    """同一 open_ord_id 平仓张数不得超过开仓张数，剔除超额幽灵腿。"""
    fetch_fn = fetch_fn or fetch_ord_fill_summary
    by_open = {}
    no_open = []
    for leg in legs:
        oid = (leg.get("open_ord_id") or "").strip()
        if not oid:
            no_open.append(leg)
            continue
        by_open.setdefault(oid, []).append(leg)

    kept, removed = [], []
    for leg in no_open:
        ok, reason = verify_realized_leg(leg, fetch_fn, strict_open=False)
        if ok:
            kept.append(leg)
        else:
            removed.append(leg)
            log(
                f"[prune] 无 open_ord 且未通过校验 {leg.get('strategy_id')} "
                f"close={leg.get('close_ord_id')} reason={reason}"
            )
    for open_oid, group in by_open.items():
        open_sz = None
        summary = fetch_fn(open_oid)
        if summary:
            open_sz = float(summary.get("totalSz") or 0)
        if not open_sz or open_sz <= 0:
            kept.extend(group)
            continue
        used = 0.0
        for leg in sorted(group, key=lambda x: float(x.get("close_time", 0) or 0)):
            qty = float(leg.get("qty") or 0)
            if used + qty > open_sz + 1e-6:
                removed.append(leg)
                log(
                    f"[prune] 超额平仓剔除 {leg.get('strategy_id')} "
                    f"open={open_oid} close={leg.get('close_ord_id')} "
                    f"qty={qty} used={used} open_sz={open_sz}"
                )
                continue
            used += qty
            kept.append(leg)
    kept.sort(key=lambda x: float(x.get("close_time", 0) or 0))
    return kept, removed


def repair_realized_leg_pnls(legs, fetch_fn=None):
    """修正 realized_legs：入场价用开仓成交均价，盈亏用策略归因（修复 net_mode fillPnl 错位）。"""
    fetch_fn = fetch_fn or fetch_ord_fill_summary
    fixed = 0
    for leg in legs:
        if (leg.get("reason") or "").strip() in ("批次合并",):
            continue
        direction = leg.get("direction", "long")
        open_oid = (leg.get("open_ord_id") or "").strip()
        close_oid = (leg.get("close_ord_id") or "").strip()
        try:
            xp = float(leg.get("exit_price") or 0)
            qty = float(leg.get("qty") or 0)
            old_pnl = float(leg.get("net_pnl") or 0)
            ep = float(leg.get("entry_price") or 0)
            fee = float(leg.get("fee") or 0)
        except (TypeError, ValueError):
            continue
        if open_oid:
            op = fetch_fn(open_oid)
            if op and op.get("avgPx"):
                ep = float(op["avgPx"])
                leg["entry_price"] = ep
        close_fill = fetch_fn(close_oid) if close_oid else None
        if close_fill:
            if close_fill.get("avgPx"):
                xp = float(close_fill["avgPx"])
                leg["exit_price"] = xp
            if close_fill.get("totalSz"):
                qty = float(close_fill["totalSz"])
                leg["qty"] = qty
            if leg.get("fee") in (None, ""):
                fee = float(close_fill.get("fee") or 0)
                leg["fee"] = fee
        attr = attributed_pnl_from_prices(direction, ep, xp, qty, fee)
        if attr is None:
            continue
        if abs(attr - old_pnl) >= 0.01 or _pnl_ret_mismatch(
            direction, None, old_pnl, ep, xp, qty
        ):
            leg["net_pnl"] = attr
            leg["reason"] = "策略归因"
            fixed += 1
            log(
                f"[pnl_fix] {leg.get('strategy_id')} {direction} "
                f"{ep}→{xp} qty={qty} {old_pnl}→{attr} close={close_oid}"
            )
    return legs, fixed


def reconcile_state_from_position_files(base_dir=None):
    """以 position_*.json 为真源，同步 state.json 开仓 tranches。"""
    base_dir = base_dir or BASE_DIR
    try:
        from position_state import load_state
        st = load_state(base_dir)
        if len(st.get("tranches") or []) > 1:
            log("[state] 跳过多 tranche 持仓拆分，保留 state.json 明细")
            return False
    except Exception:
        pass
    tracker = {}
    for name in os.listdir(base_dir):
        if not name.startswith("position_") or not name.endswith(".json"):
            continue
        sid = name.replace("position_", "").replace(".json", "")
        if sid not in VALID_TRADE_STRATEGIES:
            continue
        path = os.path.join(base_dir, name)
        try:
            with open(path, encoding="utf-8") as f:
                tracker[sid] = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
    try:
        from position_state import reconcile_state_from_tracker

        reconcile_state_from_tracker(tracker, base_dir, logger=None)
        log(f"[state] 已从 position 文件同步 {len(tracker)} 个策略 tranche")
        return True
    except Exception as ex:
        log(f"[state] position 同步失败: {ex}")
        return False


def rebuild_trades_from_state():
    """用 state.json 完全重建 trades.csv（已平仓 + 当前 tranche 持仓中）。"""
    if _bwr_skip_maintenance("rebuild_trades_from_state"):
        return 0
    if not os.path.exists(STATE_JSON):
        return 0
    with open(STATE_JSON, encoding="utf-8") as f:
        state = json.load(f)
    equity = load_strategy_equity()
    reset_ms = load_reset_after_ms()
    closed_rows = []

    from okx_close_aggregate import collapse_okx_close_legs  # noqa: E402

    legs = dedupe_realized_legs(state.get("realized_legs") or [])
    legs, leg_merged = collapse_okx_close_legs(legs)
    if leg_merged > 0:
        from position_state import save_state  # noqa: E402

        state["realized_legs"] = legs
        save_state(state, BASE_DIR)
        log(f"[rebuild] OKX 同策略平仓合并 {leg_merged} 笔 realized_legs")
    for leg in legs:
        if reset_ms > 0:
            ct_ms = int(float(leg.get("close_time", 0) or 0) * 1000)
            if ct_ms < reset_ms:
                continue
        row = realized_leg_to_row(leg, equity)
        if not row:
            continue
        clean = {k: v for k, v in row.items() if not k.startswith("_")}
        if is_ghost_row(clean):
            continue
        closed_rows.append(clean)

    # OKX 规则：同策略+同开仓 ord+同平仓分钟 → 一行战报（非一次平也按加权聚合）
    from okx_close_aggregate import collapse_okx_close_rows  # noqa: E402

    closed_rows, collapsed_n = collapse_okx_close_rows(closed_rows)
    if collapsed_n > 0:
        log(f"[rebuild] OKX 同策略平仓合并 {collapsed_n} 笔战报行")

    replay_map, _final = _replay_equity_after_close(closed_rows, equity)
    sync_state_equity_after_from_replay(replay_map)
    for clean in closed_rows:
        oid = (clean.get("ordId") or "").strip()
        if oid in replay_map:
            clean["策略权益金"] = replay_map[oid]
    rows = list(closed_rows)

    for tr in state.get("tranches") or []:
        qty = float(tr.get("remaining_qty", tr.get("qty", 0)) or 0)
        if qty <= 0:
            continue
        sid = tr.get("strategy_id", "")
        if sid not in VALID_TRADE_STRATEGIES:
            continue
        if is_synthetic_open_ord(tr.get("open_ord_id") or ""):
            continue
        et = float(tr.get("entry_time", 0) or 0)
        ord_key = tr.get("open_ord_id") or tr.get("tranche_id") or f"state_{sid}"
        rows.append({
            "开仓时间": datetime.fromtimestamp(et).strftime("%Y-%m-%d %H:%M:%S") if et else "",
            "出场时间": "",
            "策略": sid,
            "方向": tr.get("direction", "long"),
            "入场价": round(float(tr.get("entry_price", 0) or 0), 2),
            "出场价": "",
            "收益率%": "",
            "净盈亏": "",
            "状态": "持仓中",
            "持仓时间(分)": "",
            "原因": tr.get("hold_reason") or "bot持仓",
            "K值": "",
            "D值": "",
            "ADX": "",
            "杠杆": 5,
            "开仓张数": round(qty, 4),
            "策略权益金": equity.get(sid, ""),
            "fee": tr.get("open_fee", ""),
            "ordId": ord_key,
            "数据源": "state_json",
            "数据来源": "bot自动",
        })

    with open(TRADES_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in FIELDNAMES})
    log(f"[rebuild] trades.csv 自 state 重建: 已平仓{sum(1 for r in rows if r.get('状态')=='已平仓')} "
        f"持仓中{sum(1 for r in rows if r.get('状态')=='持仓中')}")
    return len(rows)


def fix_state_realized_legs(save=True, supplement_fifo=False, collapse_batch=False):
    """轻量修正 state.json realized_legs（去重 + 校验）；FIFO/批次合并需显式开启。"""
    if not os.path.exists(STATE_JSON):
        return {"before": 0, "after": 0}
    with open(STATE_JSON, encoding="utf-8") as f:
        state = json.load(f)
    raw = state.get("realized_legs") or []
    reset_ms = load_reset_after_ms()
    pre_reset = []
    post_reset = []
    for leg in raw:
        ct_ms = int(float(leg.get("close_time", 0) or 0) * 1000)
        if reset_ms > 0 and ct_ms < reset_ms:
            pre_reset.append(leg)
        else:
            post_reset.append(leg)
    collapsed, stats = filter_valid_realized_legs(
        post_reset,
        supplement_fifo=supplement_fifo,
        collapse_batch=collapse_batch,
    )
    state["realized_legs"] = pre_reset + collapsed
    stats["before"] = len(raw)
    stats["after"] = len(state["realized_legs"])
    if save:
        tmp = STATE_JSON + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        os.replace(tmp, STATE_JSON)
    log(
        f"[fix_state] legs {stats['before']}→{stats['after']} "
        f"fifo={stats.get('fifo', 0)} verify_drop={stats.get('pruned_verify', 0)} "
        f"batch={stats.get('batch_collapsed', 0)}"
    )
    return stats


def pair_round_trips(fills):
    """按 clOrdId 聚合成开/平仓腿，再按时间 FIFO 配对完整交易。"""
    by_ord = {}
    for f in fills:
        oid = f.get("ordId", "")
        if not oid:
            continue
        by_ord.setdefault(oid, []).append(f)

    legs = []
    for _oid, fs in by_ord.items():
        leg = aggregate_ord_fills(fs)
        if not leg:
            continue
        cl = (leg.get("clOrdId") or "").strip()
        if cl.startswith("stralignclose"):
            # P0 2026-07-03: 对齐清仓单必须参与配对消耗，否则被它清掉的开仓
            # 会残留在栈里，与之后的 close 跨清仓边界错配（假腿根因之一）
            leg["kind"] = "alignclose"
            legs.append(leg)
        elif leg["strategy"] and leg["kind"] in ("open", "close"):
            legs.append(leg)

    legs.sort(key=lambda x: x["fillTime"])
    stacks = {sid: [] for sid in VALID_TRADE_STRATEGIES}
    round_trips = []

    for leg in legs:
        if leg["kind"] == "alignclose":
            # 按 posSide 从所有策略栈按时间 FIFO 消耗库存（清仓不产生策略腿）
            remaining = float(leg.get("total_sz", 0) or 0)
            entries = []
            for s, stk in stacks.items():
                for op in stk:
                    if (
                        not leg.get("pos_side")
                        or not op.get("pos_side")
                        or op["pos_side"] == leg["pos_side"]
                    ):
                        entries.append((op["fillTime"], s, op))
            entries.sort(key=lambda x: x[0])
            for _ft, _s, op in entries:
                if remaining <= 1e-9:
                    break
                take = min(float(op.get("total_sz", 0) or 0), remaining)
                op["total_sz"] = round(float(op["total_sz"]) - take, 6)
                remaining -= take
            for s in stacks:
                stacks[s] = [op for op in stacks[s] if float(op.get("total_sz", 0) or 0) > 1e-9]
            continue
        sid = leg["strategy"]
        if leg["kind"] == "open":
            stacks[sid].append(leg)
        elif leg["kind"] == "close":
            # P0 2026-07-03: 开/平必须同 posSide，禁止平多 fill 配到开空腿（假腿根因）
            cand = [
                i for i, op in enumerate(stacks[sid])
                if not op.get("pos_side") or not leg.get("pos_side")
                or op["pos_side"] == leg["pos_side"]
            ]
            if not cand:
                log(f"[pair] {sid} close无匹配open ordId={leg['ordId']}，跳过")
                continue
            op = stacks[sid].pop(cand[0])
            open_ms, close_ms = op["fillTime"], leg["fillTime"]
            hold_min = max(0, int((close_ms - open_ms) / 60000))
            ep, xp = op["avg_px"], leg["avg_px"]
            net_pnl = leg["pnl"]
            if abs(net_pnl) < 1e-6:
                est = calc_pnl_from_prices(op["direction"], ep, xp, op["total_sz"])
                if est is not None:
                    net_pnl = est
            ret_pct = net_return_pct(ep, op["total_sz"], net_pnl)
            round_trips.append({
                "开仓时间": op["time_str"],
                "出场时间": leg["time_str"],
                "策略": sid,
                "方向": op["direction"],
                "入场价": ep,
                "出场价": xp,
                "收益率%": ret_pct,
                "净盈亏": net_pnl,
                "状态": "已平仓",
                "持仓时间(分)": hold_min,
                "原因": "OKX开平配对",
                "K值": "",
                "D值": "",
                "ADX": "",
                "杠杆": 5,
                "开仓张数": op["total_sz"],
                "策略权益金": "",
                "fee": round(op["fee"] + leg["fee"], 4),
                "ordId": leg["ordId"],
                "数据源": "OKX fills",
                "数据来源": "bot自动",
                "_open_ordId": op["ordId"],
            })
    return round_trips


def load_existing_keys():
    close_ids = set()
    open_ids = set()
    if not os.path.exists(TRADES_CSV) or os.path.getsize(TRADES_CSV) == 0:
        return close_ids, open_ids
    with open(TRADES_CSV, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            status = (row.get("状态") or "").strip()
            oid = (row.get("ordId") or "").strip()
            if status == "已平仓":
                if oid:
                    close_ids.add(oid)
                ooid = (row.get("_open_ordId") or "").strip()
                if ooid:
                    open_ids.add(ooid)
            elif status == "持仓中" and oid:
                open_ids.add(oid)
    return close_ids, open_ids


def build_trades_csv(fills):
    reset_after_ms = load_reset_after_ms()
    if reset_after_ms > 0:
        before = len(fills)
        fills = [f for f in fills if int(f.get("fillTime", 0) or 0) >= reset_after_ms]
        log(f"[reset] 仅统计 reset_after_ms={reset_after_ms} 之后成交: {len(fills)}/{before}")
    trips = pair_round_trips(fills)
    close_ids, open_ids = load_existing_keys()
    state_close_ids = {
        (leg.get("close_ord_id") or "").strip()
        for leg in load_reset_filtered_legs()
    }
    new_rows = []
    for t in trips:
        cid, oid = t["ordId"], t.get("_open_ordId", "")
        if cid in state_close_ids:
            continue
        if cid in close_ids or oid in open_ids:
            continue
        row = {k: v for k, v in t.items() if not k.startswith("_")}
        new_rows.append(row)
        log(
            f"[新成交] {row['策略']} {row['方向']} "
            f"{row['入场价']}→{row['出场价']} pnl={row['净盈亏']} ordId={cid}"
        )

    if not new_rows:
        log("[trades] 无新配对成交需追加")
        return 0

    exists = os.path.exists(TRADES_CSV) and os.path.getsize(TRADES_CSV) > 0
    with open(TRADES_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        if not exists:
            w.writeheader()
        for row in new_rows:
            w.writerow(row)
    log(f"[trades] 追加{len(new_rows)}行(开平配对)")
    return len(new_rows)


def is_ghost_row(row):
    """单笔碎片/假平仓：禁止再次写入战报。"""
    reason = (row.get("原因") or "").strip()
    status = (row.get("状态") or "").strip()
    if reason == "自动回填":
        return True
    if status != "已平仓":
        return status == "持仓中" and not (row.get("ordId") or "").strip()
    ep, xp = row.get("入场价", ""), row.get("出场价", "")
    ot, ct = (row.get("开仓时间") or "").strip(), (row.get("出场时间") or "").strip()
    if not xp or not ct:
        return True
    try:
        same_px = ep and xp and abs(float(ep) - float(xp)) < 0.02
    except (TypeError, ValueError):
        same_px = False
    if same_px:
        return True
    if ot and ct and ot[:16] == ct[:16] and reason in ("", "自动回填"):
        return True
    return False


def clean_ghost_rows():
    """删除幽灵行（自动回填、开平同刻、无出场价等）。"""
    if _bwr_skip_maintenance("clean_ghost_rows"):
        return
    if not os.path.exists(TRADES_CSV) or os.path.getsize(TRADES_CSV) == 0:
        return
    with open(TRADES_CSV, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return

    kept, removed = [], 0
    for row in rows:
        if is_ghost_row(row):
            removed += 1
        else:
            kept.append(row)

    if removed:
        with open(TRADES_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
            w.writeheader()
            for row in kept:
                w.writerow({k: row.get(k, "") for k in FIELDNAMES})
        log(f"[clean] 清除{removed}条幽灵行，保留{len(kept)}条")
    else:
        log("[clean] 无幽灵行")


def repair_closed_pnl():
    """补算/修正已平仓净盈亏：fillPnl=0 或收益率与盈亏符号矛盾时按策略开平价差归因。"""
    if not os.path.exists(TRADES_CSV) or os.path.getsize(TRADES_CSV) == 0:
        return
    with open(TRADES_CSV, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    fixed = 0
    for row in rows:
        if row.get("状态") != "已平仓":
            continue
        try:
            pnl = float(row.get("净盈亏") or 0)
        except ValueError:
            pnl = 0.0
        direction = row.get("方向", "")
        ret = row.get("收益率%", "")
        need_fix = abs(pnl) < 1e-4 or _pnl_ret_mismatch(
            direction,
            ret,
            pnl,
            row.get("入场价", ""),
            row.get("出场价", ""),
            row.get("开仓张数", ""),
        )
        if not need_fix:
            continue
        try:
            fee = float(row.get("fee") or 0)
        except (TypeError, ValueError):
            fee = 0.0
        est = attributed_pnl_from_prices(
            direction,
            row.get("入场价", ""),
            row.get("出场价", ""),
            row.get("开仓张数", ""),
            fee,
        )
        if est is None:
            continue
        if abs(pnl) >= 1e-4 and abs(est - pnl) < 0.01:
            continue
        row["净盈亏"] = est
        sync_return_pct_row(row)
        fixed += 1
    sync_all_return_pct(rows)
    if rows:
        with open(TRADES_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
            w.writeheader()
            for row in rows:
                w.writerow({k: row.get(k, "") for k in FIELDNAMES})
        if fixed:
            log(f"[repair] 修正{fixed}条已平仓净盈亏")
        log("[repair] 已同步净收益率%（与净盈亏同号）")


def rebuild_open_rows_from_state():
    """删除旧的持仓中残留行，仅保留 state.json 对应的真实 tranche 持仓。"""
    if not os.path.exists(TRADES_CSV) or os.path.getsize(TRADES_CSV) == 0:
        return
    with open(TRADES_CSV, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return

    kept = [row for row in rows if row.get("状态") != "持仓中"]
    removed = len(rows) - len(kept)
    if removed:
        with open(TRADES_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
            w.writeheader()
            for row in kept:
                w.writerow({k: row.get(k, "") for k in FIELDNAMES})
        log(f"[open_rows] 清理{removed}条旧持仓中残留行，等待按 state.json 重建")


def realized_leg_to_row(leg, equity=None):
    """state.json realized_legs → trades.csv 行（fills 缺失时回补）。"""
    sid = str(leg.get("strategy_id", "")).strip()
    if sid not in VALID_TRADE_STRATEGIES:
        return None
    close_oid = (leg.get("close_ord_id") or "").strip()
    open_oid = (leg.get("open_ord_id") or "").strip()
    if not close_oid:
        return None
    try:
        ep = float(leg.get("entry_price") or 0)
        xp = float(leg.get("exit_price") or 0)
        qty = float(leg.get("qty") or 0)
        et = float(leg.get("entry_time") or 0)
        ct = float(leg.get("close_time") or 0)
        net_pnl = float(leg.get("net_pnl") or 0)
    except (TypeError, ValueError):
        return None
    if ep <= 0 or xp <= 0 or qty <= 0 or et <= 0 or ct <= 0:
        return None
    direction = leg.get("direction", "long")
    hold_min = max(0, int((ct - et) / 60))
    net_pnl_r = round(net_pnl, 4)
    ret_pct = net_return_pct(ep, qty, net_pnl_r)
    reason = (leg.get("reason") or "平仓信号").strip()
    est = "_est" in reason
    return {
        "开仓时间": datetime.fromtimestamp(et).strftime("%Y-%m-%d %H:%M:%S"),
        "出场时间": datetime.fromtimestamp(ct).strftime("%Y-%m-%d %H:%M:%S"),
        "策略": sid,
        "方向": direction,
        "入场价": round(ep, 2),
        "出场价": round(xp, 2),
        "收益率%": ret_pct,
        "净盈亏": net_pnl_r,
        "状态": "已平仓",
        "持仓时间(分)": hold_min,
        "原因": reason if est else "state归因",
        "K值": "",
        "D值": "",
        "ADX": "",
        "杠杆": 5,
        "开仓张数": round(qty, 4),
        "策略权益金": (
            round(float(leg["equity_after"]), 2)
            if leg.get("equity_after") not in (None, "")
            else equity_after_close_value(sid, equity or {})
        ),
        "fee": leg.get("fee", ""),
        "ordId": close_oid,
        "数据源": "state_json_est" if est else "state_json",
        "数据来源": "bot自动",
        "_open_ordId": open_oid,
    }


def load_reset_filtered_legs(validate=True):
    """state.json realized_legs，仅 reset 后的平仓腿（可选校验过滤）。"""
    if not os.path.exists(STATE_JSON):
        return []
    try:
        with open(STATE_JSON, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    legs = state.get("realized_legs") or []
    reset_ms = load_reset_after_ms()
    pre_reset, post_reset = [], []
    for leg in legs:
        if reset_ms > 0:
            ct_ms = int(float(leg.get("close_time", 0) or 0) * 1000)
            if ct_ms < reset_ms:
                pre_reset.append(leg)
                continue
        if (leg.get("close_ord_id") or "").strip():
            post_reset.append(leg)
    if validate and post_reset:
        post_reset = dedupe_realized_legs(post_reset)
        post_reset, _ = prune_unverified_legs(post_reset, strict_open=False)
    return pre_reset + post_reset


def _row_source_rank(row):
    src = (row.get("数据源") or "").strip()
    reason = (row.get("原因") or "").strip()
    if src == "OKX fills" or reason == "OKX开平配对":
        return 5
    if src == "state_json" and reason not in ("state归因", ""):
        return 4
    if reason == "策略归因":
        return 3
    if src.startswith("state_json") or reason == "state归因":
        return 2
    return 0


def reconcile_trades_from_state():
    """以 state.json realized_legs 为 bot 归因真源，修正 trades.csv 策略错位/缺失/幽灵持仓。"""
    legs = load_reset_filtered_legs()
    if not legs:
        return 0

    equity = load_strategy_equity()
    close_to_leg = {}
    closed_open_ids = set()
    for leg in legs:
        cid = (leg.get("close_ord_id") or "").strip()
        oid = (leg.get("open_ord_id") or "").strip()
        if cid:
            close_to_leg[cid] = leg
        if oid:
            closed_open_ids.add(oid)

    rows = []
    if os.path.exists(TRADES_CSV) and os.path.getsize(TRADES_CSV) > 0:
        with open(TRADES_CSV, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

    by_close = {}
    open_rows = []
    removed_open = 0
    fixed = 0

    # P0 2026-07-03: 「open ordId 出现在 realized_legs」不等于「该仓位已全平」——
    # 部分平仓/元数据串号时曾误删真实 tranche。只有 realized legs 平掉的张数
    # >= 该 open 订单总张数时才允许删除；OKX 查询失败时保守保留。
    closed_qty_by_open = {}
    for leg in legs:
        loid = (leg.get("open_ord_id") or "").strip()
        if loid:
            closed_qty_by_open[loid] = closed_qty_by_open.get(loid, 0.0) + float(
                leg.get("qty", 0) or 0
            )

    def _open_fully_closed(oid):
        try:
            meta = fetch_ord_fill_summary(oid)
        except Exception:
            return False
        if not meta:
            return False
        open_sz = float(meta.get("totalSz", 0) or 0)
        if open_sz <= 0:
            return False
        return closed_qty_by_open.get(oid, 0.0) >= open_sz - 1e-6

    for row in rows:
        st = (row.get("状态") or "").strip()
        oid = (row.get("ordId") or "").strip()
        if st == "持仓中":
            if oid in closed_open_ids and _open_fully_closed(oid):
                removed_open += 1
                log(f"[归因] 删除已全平仍显示的持仓中 {row.get('策略')} open={oid}")
                continue
            open_rows.append(row)
            continue
        if st != "已平仓" or not oid:
            continue
        leg = close_to_leg.get(oid)
        if leg:
            new_row = realized_leg_to_row(leg, equity)
            if not new_row:
                continue
            clean = {k: v for k, v in new_row.items() if not k.startswith("_")}
            prev = by_close.get(oid)
            if prev and _row_source_rank(prev) > _row_source_rank(clean):
                merged = dict(prev)
                for key in FIELDNAMES:
                    if not (merged.get(key) or "").strip() and (clean.get(key) or "").strip():
                        merged[key] = clean[key]
                clean = merged
            elif row.get("策略") != clean.get("策略"):
                log(
                    f"[归因修正] close={oid} "
                    f"{row.get('策略')}→{clean.get('策略')} "
                    f"({row.get('数据源')}→state)"
                )
                fixed += 1
            if not prev or _row_source_rank(clean) >= _row_source_rank(prev):
                by_close[oid] = clean
        else:
            prev = by_close.get(oid)
            if not prev or _row_source_rank(row) > _row_source_rank(prev):
                by_close[oid] = {k: row.get(k, "") for k in FIELDNAMES}

    added = 0
    for cid, leg in close_to_leg.items():
        if cid in by_close:
            continue
        new_row = realized_leg_to_row(leg, equity)
        if not new_row:
            continue
        clean = {k: v for k, v in new_row.items() if not k.startswith("_")}
        if is_ghost_row(clean):
            continue
        by_close[cid] = clean
        added += 1
        log(f"[state补齐] {clean['策略']} {clean['入场价']}→{clean['出场价']} ordId={cid}")

    closed_rows = sorted(by_close.values(), key=_row_time_ms)
    merged = closed_rows + open_rows
    old_sig = json.dumps(rows, ensure_ascii=False, sort_keys=True)
    new_sig = json.dumps(merged, ensure_ascii=False, sort_keys=True)
    if fixed or added or removed_open or old_sig != new_sig:
        with open(TRADES_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
            w.writeheader()
            for row in merged:
                w.writerow({k: row.get(k, "") for k in FIELDNAMES})
        log(
            f"[归因] 对账完成: 修正{fixed} 补齐{added} "
            f"删幽灵持仓{removed_open} 已平仓{len(closed_rows)} 持仓中{len(open_rows)}"
        )
    return fixed + added + removed_open


def sync_closed_from_state():
    """OKX fills 查不到时，用 state.json realized_legs 回补已平仓（禁止重复 ordId）。"""
    if not os.path.exists(STATE_JSON):
        log("[state] state.json 不存在，跳过已平仓回补")
        return 0
    with open(STATE_JSON, encoding="utf-8") as f:
        state = json.load(f)
    legs = state.get("realized_legs") or []
    if not legs:
        return 0

    equity = {}
    eq_path = os.path.join(BASE_DIR, "strategy_eq.json")
    if os.path.exists(eq_path):
        with open(eq_path, encoding="utf-8") as f:
            equity = json.load(f)

    reset_after_ms = load_reset_after_ms()
    close_ids, open_ids = load_existing_keys()
    new_rows = []
    for leg in legs:
        row = realized_leg_to_row(leg, equity)
        if not row:
            continue
        cid = row["ordId"]
        oid = row.get("_open_ordId", "")
        if cid in close_ids or (oid and oid in open_ids):
            continue
        if reset_after_ms > 0:
            ct_ms = int(float(leg.get("close_time", 0) or 0) * 1000)
            if ct_ms < reset_after_ms:
                continue
        clean = {k: v for k, v in row.items() if not k.startswith("_")}
        if is_ghost_row(clean):
            continue
        new_rows.append(clean)
        close_ids.add(cid)
        log(
            f"[state回补] {clean['策略']} {clean['方向']} "
            f"{clean['入场价']}→{clean['出场价']} pnl={clean['净盈亏']} "
            f"ordId={cid} ({clean['数据源']})"
        )

    if not new_rows:
        log("[state] 无缺失已平仓需回补")
        return 0

    exists = os.path.exists(TRADES_CSV) and os.path.getsize(TRADES_CSV) > 0
    with open(TRADES_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        if not exists:
            w.writeheader()
        for row in new_rows:
            w.writerow(row)
    log(f"[state] 回补{len(new_rows)}条已平仓")
    return len(new_rows)


def append_realized_leg(leg, equity=None):
    """单条 realized_leg 写入 trades.csv（去重）；供 main.py 平仓后立即调用。"""
    ok, reason = verify_realized_leg(leg, strict_open=bool(leg.get("open_ord_id")))
    if not ok:
        log(
            f"[append] 跳过未校验 leg {leg.get('strategy_id')} "
            f"close={leg.get('close_ord_id')} reason={reason}"
        )
        return False
    row = realized_leg_to_row(leg, equity)
    if not row:
        return False
    close_ids, open_ids = load_existing_keys()
    cid = row["ordId"]
    oid = row.get("_open_ordId", "")
    if cid in close_ids or (oid and oid in open_ids):
        return False
    clean = {k: v for k, v in row.items() if not k.startswith("_")}
    if is_ghost_row(clean):
        return False
    exists = os.path.exists(TRADES_CSV) and os.path.getsize(TRADES_CSV) > 0
    lock_fp = open(TRADES_LOCKFILE, "w")
    fcntl.flock(lock_fp, fcntl.LOCK_EX)
    try:
        with open(TRADES_CSV, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
            if not exists:
                w.writeheader()
            w.writerow(clean)
    finally:
        fcntl.flock(lock_fp, fcntl.LOCK_UN)
        lock_fp.close()
    return True


def append_realized_legs(legs):
    """平仓后立即写入，避免等 cron / fills 接口。"""
    if not legs:
        return 0
    equity = {}
    eq_path = os.path.join(BASE_DIR, "strategy_eq.json")
    if os.path.exists(eq_path):
        with open(eq_path, encoding="utf-8") as f:
            equity = json.load(f)
    added = 0
    for leg in legs:
        if append_realized_leg(leg, equity):
            added += 1
            sid = leg.get("strategy_id", "")
            log(
                f"[即时写入] {sid} {leg.get('direction')} "
                f"pnl={leg.get('net_pnl')} ordId={leg.get('close_ord_id')}"
            )
    return added


def sync_open_positions():
    """把 bot 当前 tranche 同步为 trades.csv 中的「持仓中」行（供战报汇总显示）。"""

    existing_open = set()
    if os.path.exists(TRADES_CSV):
        with open(TRADES_CSV, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("状态") == "持仓中":
                    existing_open.add((row.get("策略", ""), row.get("ordId", "")))

    eq_path = os.path.join(BASE_DIR, "strategy_eq.json")
    equity = {}
    if os.path.exists(eq_path):
        with open(eq_path, encoding="utf-8") as f:
            equity = json.load(f)

    tranches = []
    if os.path.exists(STATE_JSON):
        with open(STATE_JSON, encoding="utf-8") as f:
            state = json.load(f)
        tranches = [tr for tr in state.get("tranches", []) if float(tr.get("remaining_qty", tr.get("qty", 0)) or 0) > 0]
    else:
        log("[持仓] state.json 不存在，跳过 tranche 持仓同步")
        return

    added = 0
    for tr in tranches:
        sid = tr.get("strategy_id", "")
        if is_synthetic_open_ord(tr.get("open_ord_id") or ""):
            continue
        ord_key = tr.get("open_ord_id") or tr.get("tranche_id") or f"state_{sid}"
        if sid not in VALID_TRADE_STRATEGIES or (sid, ord_key) in existing_open:
            continue
        ep = tr.get("entry_price", "")
        et = tr.get("entry_time", 0)
        ts_str = (
            datetime.fromtimestamp(et).strftime("%Y-%m-%d %H:%M:%S")
            if et
            else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        row = {
            "开仓时间": ts_str,
            "出场时间": "",
            "策略": sid,
            "方向": tr.get("direction", "long"),
            "入场价": round(float(ep), 2) if ep else "",
            "出场价": "",
            "收益率%": "",
            "净盈亏": "",
            "状态": "持仓中",
            "持仓时间(分)": "",
            "原因": "bot持仓(同步)" if ord_key == "sync_snapshot" else "bot持仓",
            "K值": "",
            "D值": "",
            "ADX": "",
            "杠杆": 5,
            "开仓张数": round(float(tr.get("remaining_qty", tr.get("qty", 0)) or 0), 4),
            "策略权益金": equity.get(sid, ""),
            "fee": tr.get("open_fee", ""),
            "ordId": ord_key,
            "数据源": "state_json",
            "数据来源": "bot自动",
        }
        exists = os.path.exists(TRADES_CSV) and os.path.getsize(TRADES_CSV) > 0
        with open(TRADES_CSV, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
            if not exists:
                w.writeheader()
            w.writerow(row)
        added += 1
        existing_open.add((sid, ord_key))
        log(f"[持仓] 同步 {sid} {row['方向']} qty={row['开仓张数']} @ {row['入场价']}")

    if not added:
        log("[持仓] 无需同步")


def run_war_v3():
    if not os.path.exists(WAR_V3):
        log(f"WAR_FAIL | war_v3.py不存在 ({WAR_V3})")
        return False
    result = subprocess.run(
        [sys.executable, WAR_V3],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=BASE_DIR,
    )
    if result.returncode != 0:
        log(f"WAR_FAIL | war_v3.py exit={result.returncode} | {result.stderr[:300]}")
        if os.path.exists(WAR_REPORT):
            os.remove(WAR_REPORT)
            log("[clean] 删半成品xlsx")
        return False
    log(f"[war_v3] {result.stdout.strip()}")
    return True


def _war_lock():
    """防止战报 cron 多实例并发写坏 xlsx。"""
    import fcntl

    lock_path = os.path.join(BASE_DIR, ".war_report.lock")
    fp = open(lock_path, "w", encoding="utf-8")
    try:
        fcntl.flock(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("WAR_SKIP | 另一实例正在生成战报")
        fp.close()
        return None
    return fp


def finalize_close_leg_from_fills(leg):
    """用 OKX 开/平仓 fills 校正 leg 价格、张数、盈亏；未通过 verify 则拒绝写入战报。"""
    open_oid = (leg.get("open_ord_id") or "").strip()
    close_oid = (leg.get("close_ord_id") or "").strip()
    ok, reason = verify_realized_leg(leg, strict_open=not is_synthetic_open_ord(open_oid))
    if not ok:
        return leg, False, reason
    close_meta = fetch_ord_fill_summary(close_oid)
    if not close_meta:
        return leg, False, "fill_summary_missing"
    if is_synthetic_open_ord(open_oid):
        ep = float(leg.get("entry_price") or 0)
        open_meta = None
    else:
        open_meta = fetch_ord_fill_summary(open_oid)
        if not open_meta:
            return leg, False, "fill_summary_missing"
        ep = float(open_meta["avgPx"])
    xp = float(close_meta["avgPx"])
    if open_meta:
        qty = min(float(open_meta["totalSz"]), float(close_meta["totalSz"]))
    else:
        qty = min(float(leg.get("qty") or 0), float(close_meta["totalSz"]))
    if ep <= 0 or xp <= 0 or qty <= 0:
        return leg, False, "bad_prices"
    direction = leg.get("direction", "long")
    fee = float(close_meta.get("fee") or 0)
    pnl = attributed_pnl_from_prices(direction, ep, xp, qty, fee)
    if pnl is None:
        return leg, False, "pnl_calc_fail"
    et_ms = int(open_meta.get("fillTime") or 0) if open_meta else 0
    ct_ms = int(close_meta.get("fillTime") or 0)
    finalized = {
        **leg,
        "entry_price": ep,
        "exit_price": xp,
        "qty": qty,
        "fee": fee,
        "net_pnl": pnl,
        "entry_time": et_ms / 1000.0 if et_ms else leg.get("entry_time"),
        "close_time": ct_ms / 1000.0 if ct_ms else leg.get("close_time"),
        "reason": "OKX开平配对" if open_meta else "bot平仓",
    }
    return finalized, True, "ok"


def sync_leg_to_state(leg, base_dir=None):
    """将校正后的 realized_leg 写回 state.json。"""
    ct = float(leg.get("close_time", 0) or 0)
    if ct > 0 and ct < CUTOFF_TS:
        log("[sync_leg] 跳过6月15日前的leg " + str(leg.get("strategy_id")) + " close_oid=" + str(leg.get("close_ord_id")))
        return False
    path = STATE_JSON if base_dir is None else os.path.join(base_dir, "state.json")
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as fp:
        state = json.load(fp)
    cid = (leg.get("close_ord_id") or "").strip()
    updated = False
    for i, existing in enumerate(state.get("realized_legs", [])):
        if (existing.get("close_ord_id") or "").strip() == cid:
            state["realized_legs"][i] = {**existing, **leg}
            updated = True
            break
    if not updated:
        return False
    from position_state import compute_net_position
    state["net_position"] = compute_net_position(state.get("tranches", []))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fp:
        json.dump(state, fp, ensure_ascii=False)
    os.replace(tmp, path)
    return True


def refresh_war_report_accurate(trigger_sid=None):
    """以 state.json 只读投影重建战报 xlsx（不改 open tranche；open 仅 bot 写入）。"""
    lock_fp = _war_lock()
    if lock_fp is None:
        log(f"WAR_ACC_SKIP | sid={trigger_sid or '-'} 另一实例正在生成战报")
        return False
    try:
        sid_label = trigger_sid or "-"
        log(f"WAR_ACC_START | trigger={sid_label}")
        prune_inflated_state_legs(base_dir=BASE_DIR)
        prune_synthetic_tranches(base_dir=BASE_DIR)
        clean_ghost_rows()
        dedup_trades_csv()
        reconcile_trades_from_state()
        rebuild_trades_from_state()
        repair_closed_pnl()
        stamp_closed_equity(force=True)
        rebuild_open_rows_from_state()
        sync_open_positions()
        if not run_war_v3():
            log(f"WAR_ACC_FAIL | trigger={sid_label}")
            return False
        ts_path = os.path.join(LOG_DIR, "war_updated_at.txt")
        with open(ts_path, "w", encoding="utf-8") as fp:
            fp.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        log(f"WAR_ACC_DONE | trigger={sid_label} xlsx={WAR_REPORT}")
        return True
    except Exception as ex:
        log(f"WAR_ACC_FAIL | trigger={sid_label} err={ex}")
        return False
    finally:
        import fcntl

        fcntl.flock(lock_fp, fcntl.LOCK_UN)
        lock_fp.close()


def refresh_war_report_fast(trigger_sid=None):
    """兼容旧名：与 accurate 相同（准确优先）。"""
    return refresh_war_report_accurate(trigger_sid=trigger_sid)


def main():
    lock_fp = _war_lock()
    if lock_fp is None:
        return
    try:
        _main_war_body()
    finally:
        import fcntl

        fcntl.flock(lock_fp, fcntl.LOCK_UN)
        lock_fp.close()


def _main_war_body():
    """定时战报：以 state.json + position 为真源，禁止全量 fills 重建（防幽灵成交膨胀）。"""
    log("=== WAR START (state-accurate, read-only open) ===")
    prune_inflated_state_legs(base_dir=BASE_DIR)
    prune_synthetic_tranches(base_dir=BASE_DIR)
    bak_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if os.path.exists(TRADES_CSV):
        bak_path = os.path.join(BASE_DIR, f"trades.csv.bak_{bak_ts}")
        shutil.copy2(TRADES_CSV, bak_path)
        log(f"[backup] -> {bak_path}")

    lock_fp_csv = open(TRADES_LOCKFILE, "w")
    fcntl.flock(lock_fp_csv, fcntl.LOCK_EX)
    try:
        clean_ghost_rows()
        dedup_trades_csv()
        reconcile_trades_from_state()
        rebuild_trades_from_state()
        repair_closed_pnl()
        stamp_closed_equity(force=True)
        rebuild_open_rows_from_state()
        sync_open_positions()
    finally:
        fcntl.flock(lock_fp_csv, fcntl.LOCK_UN)
        lock_fp_csv.close()
    if not run_war_v3():
        return

    ts_path = os.path.join(LOG_DIR, "war_updated_at.txt")
    with open(ts_path, "w", encoding="utf-8") as fp:
        fp.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    total_trades = 0
    total_pnl = 0.0
    if os.path.exists(TRADES_CSV) and os.path.getsize(TRADES_CSV) > 0:
        with open(TRADES_CSV, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("状态") == "已平仓":
                    total_trades += 1
                    try:
                        total_pnl += float(row.get("净盈亏") or 0)
                    except ValueError:
                        pass
    log(
        f"WAR_DONE | mode=state-accurate | 已平仓笔数={total_trades} | "
        f"累计净盈亏={total_pnl:.2f} USDT | xlsx={WAR_REPORT}"
    )


if __name__ == "__main__":
    main()
