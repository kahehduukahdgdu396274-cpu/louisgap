#!/usr/bin/env python3
"""Reconcile all strategy position_*.json + state.json to match OKX net via LIFO open fills."""
from __future__ import annotations

import json
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime

BASE = os.environ.get("OKX_BOT_DIR", "/home/admin/okx_bot")
if os.environ.get("HERMES_A2_FIXTURE") == "1":
    _fixture_state = os.environ.get("HERMES_STATE_PATH", "").strip()
    if _fixture_state and os.path.isfile(_fixture_state):
        BASE = os.path.dirname(os.path.abspath(_fixture_state))
elif not os.path.isdir(BASE):
    _repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if os.path.isfile(os.path.join(_repo_root, "api.py")):
        BASE = _repo_root
CUTOFF_TS = 1781452800.0  # 2026-06-15 00:00:00 CST
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "scripts"))

from position_state import (  # noqa: E402
    load_state,
    reconcile_state_from_tracker,
    record_close_leg,
    save_state,
)

SYMBOL = "BTC-USDT-SWAP"
STRATEGY_IDS = ["003", "006", "009", "011", "012", "014", "015", "016", "017", "019", "020", "021"]
CL_PAT = re.compile(r"str(003|006|009|011|012|014|015|016|017|019|020|021)(open|close)")


def empty_position():
    return {"position": False, "entry_price": 0}


def backup():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    for name in ("state.json", "trades.csv"):
        src = os.path.join(BASE, name)
        if os.path.exists(src):
            shutil.copy2(src, f"{src}.bak_all_{ts}")
    for sid in STRATEGY_IDS:
        pf = os.path.join(BASE, f"position_{sid}.json")
        if os.path.exists(pf):
            shutil.copy2(pf, f"{pf}.bak_all_{ts}")


def fetch_okx_net(client: OKXClient) -> tuple[int, float, float]:
    """返回带符号净持仓（正=long, 负=short），处理 long_short_mode 的 posSide。"""
    pr = client.request("GET", f"/api/v5/account/positions?instId={SYMBOL}")
    if pr.get("code") != "0" or not pr.get("data"):
        raise RuntimeError(f"OKX position query failed: {pr}")
    signed = 0
    total_sz = 0
    weighted_px = 0.0
    entry_time = time.time()
    for row in pr["data"]:
        p = float(row.get("pos") or 0)
        if abs(p) < 0.01:
            continue
        side = (row.get("posSide") or "net").lower()
        if side == "short":
            signed -= int(abs(p))
        elif side == "long":
            signed += int(abs(p))
        else:
            signed += int(round(p))
        sz = abs(p)
        total_sz += sz
        weighted_px += sz * float(row.get("avgPx") or 0)
        ctime_ms = row.get("cTime")
        if ctime_ms:
            entry_time = min(entry_time, float(ctime_ms) / 1000.0)
    avg_px = round(weighted_px / total_sz, 2) if total_sz > 0 else 0.0
    return signed, avg_px, entry_time


def fetch_okx_gross(client: OKXClient) -> dict:
    """long_short_mode 下分别返回多/空腿张数（对冲时 net 可能=0 但腿仍在）。

    修复根因：原 fetch_okx_net 只返回 signed=多-空，016 转空 + 021 持多 时 net=0，
    reconcile 误判为空仓并清掉所有本地仓，造成 OKX 孤儿腿 + 归因丢失。
    """
    pr = client.request("GET", f"/api/v5/account/positions?instId={SYMBOL}")
    if pr.get("code") != "0" or not pr.get("data"):
        raise RuntimeError(f"OKX position query failed: {pr}")
    long_qty = short_qty = 0.0
    long_px_sum = short_px_sum = 0.0
    long_et = short_et = None
    for row in pr["data"]:
        p = float(row.get("pos") or 0)
        if abs(p) < 0.01:
            continue
        side = (row.get("posSide") or "net").lower()
        sz = abs(p)
        px = float(row.get("avgPx") or 0)
        ct = row.get("cTime")
        et = float(ct) / 1000.0 if ct else time.time()
        if side == "short" or (side == "net" and p < 0):
            short_qty += sz
            short_px_sum += sz * px
            short_et = et if short_et is None else min(short_et, et)
        else:
            long_qty += sz
            long_px_sum += sz * px
            long_et = et if long_et is None else min(long_et, et)
    return {
        "long": long_qty,
        "short": short_qty,
        "net": long_qty - short_qty,
        "long_avg": round(long_px_sum / long_qty, 2) if long_qty else 0.0,
        "short_avg": round(short_px_sum / short_qty, 2) if short_qty else 0.0,
        "long_entry_time": long_et or time.time(),
        "short_entry_time": short_et or time.time(),
    }


def _fetch_bot_fills(client: OKXClient) -> list[dict]:
    seen_bills: set[str] = set()
    raw: list[dict] = []
    after = None
    for _ in range(15):
        path = f"/api/v5/trade/fills?instType=SWAP&instId={SYMBOL}&limit=100"
        if after:
            path += f"&after={after}"
        r = client.request("GET", path)
        if not r or r.get("code") != "0":
            break
        batch = r.get("data") or []
        if not batch:
            break
        new_in_batch = 0
        for row in batch:
            bill = row.get("billId", "")
            if bill in seen_bills:
                continue
            seen_bills.add(bill)
            raw.append(row)
            new_in_batch += 1
        if len(batch) < 100 or new_in_batch == 0:
            break
        after = batch[-1].get("billId") or batch[-1].get("fillId")
        if not after:
            break
    return raw


def fetch_bot_open_orders(client: OKXClient, reset_after_ms: int = 0) -> list[dict]:
    """Group surviving open fills by ordId (扣除已平仓成交量后 LIFO 归因)."""
    raw = _fetch_bot_fills(client)

    by_ord: dict[str, dict] = {}
    close_by_sid: dict[str, float] = defaultdict(float)

    for row in raw:
        cl = row.get("clOrdId", "") or ""
        m = CL_PAT.search(cl)
        if not m:
            continue
        ts = int(row["ts"])
        if reset_after_ms > 0 and ts < reset_after_ms:
            continue
        action = m.group(2)
        sid = m.group(1)
        sz = float(row.get("fillSz") or 0)
        if action == "close":
            close_by_sid[sid] += sz
            continue
        oid = row["ordId"]
        side = row["side"]
        px = float(row.get("fillPx") or 0)
        if oid not in by_ord:
            by_ord[oid] = {
                "ord_id": oid,
                "sid": sid,
                "side": side,
                "sz": 0.0,
                "px_sum": 0.0,
                "last_ts": ts,
            }
        g = by_ord[oid]
        g["sz"] += sz
        g["px_sum"] += px * sz
        g["last_ts"] = max(g["last_ts"], ts)

    # 按策略 LIFO 扣减已平仓量，避免历史开仓 fill 被误当作仍持仓
    orders = sorted(by_ord.values(), key=lambda x: x["last_ts"])
    for sid in STRATEGY_IDS:
        remaining_close = close_by_sid.get(sid, 0.0)
        if remaining_close <= 1e-9:
            continue
        for o in reversed(orders):
            if o["sid"] != sid or remaining_close <= 1e-9:
                continue
            deduct = min(o["sz"], remaining_close)
            if deduct <= 0:
                continue
            ratio = deduct / o["sz"] if o["sz"] else 1.0
            o["px_sum"] *= (o["sz"] - deduct) / o["sz"] if o["sz"] else 0
            o["sz"] -= deduct
            remaining_close -= deduct

    live = []
    for g in orders:
        if g["sz"] <= 1e-9:
            continue
        g["avg_px"] = g["px_sum"] / g["sz"]
        live.append(g)
    live.sort(key=lambda x: x["last_ts"])
    return live


def lifo_attribution(net_pos: int, orders: list[dict]) -> list[dict]:
    """Allocate surviving OKX net to strategies using LIFO on open orders."""
    if net_pos == 0:
        return []
    direction = "long" if net_pos > 0 else "short"
    need_side = "buy" if direction == "long" else "sell"
    remaining = float(abs(net_pos))
    picked: list[dict] = []

    for o in reversed(orders):
        if remaining <= 1e-9:
            break
        if o["side"] != need_side:
            continue
        take = min(remaining, o["sz"])
        if take <= 0:
            continue
        picked.append({**o, "qty": take})
        remaining -= take

    if remaining > 0.01:
        print(f"WARN: LIFO 仅覆盖 {abs(net_pos) - remaining:.2f}/{abs(net_pos)} 张")

    # 保留每笔 open ord 独立 tranche（不合并同策略多笔）
    out = []
    for p in reversed(picked):
        out.append(
            {
                "sid": p["sid"],
                "direction": direction,
                "qty": float(p["qty"]),
                "entry_price": float(p["avg_px"]),
                "entry_time": p["last_ts"] / 1000.0,
                "open_ord_id": p["ord_id"],
                "px_sum": float(p["avg_px"]) * float(p["qty"]),
            }
        )
    return out


def _aggregate_close_ord(fills: list[dict], ord_id: str) -> dict | None:
    rows = [r for r in fills if r.get("ordId") == ord_id]
    if not rows:
        return None
    sz = sum(float(r.get("fillSz") or 0) for r in rows)
    if sz <= 0:
        return None
    px_sum = sum(float(r.get("fillPx") or 0) * float(r.get("fillSz") or 0) for r in rows)
    fee = sum(float(r.get("fee") or 0) for r in rows)
    ts = max(int(r.get("ts") or 0) for r in rows)
    return {
        "avg_px": px_sum / sz,
        "total_sz": sz,
        "fee": fee,
        "fillTime": ts,
        "ordId": ord_id,
    }


def record_closes_before_flat(
    client: OKXClient,
    reset_ms: int = 0,
    okx_long: float | None = None,
    okx_short: float | None = None,
) -> int:
    """本地某方向 tranche 多于 OKX 同向腿时，用平仓 fill 回补 realized_leg（战报真源）。

    side-aware：仅处理「本地某方向张数 > OKX 同向张数」的方向，避免对仍持仓的
    tranche 反复打印 no-close-fill，也避免误记未平仓位。
    """
    import build_war_report as b  # noqa: E402

    state = load_state(BASE)
    open_tranches = [
        tr
        for tr in state.get("tranches", [])
        if float(tr.get("remaining_qty", tr.get("qty", 0)) or 0) > 0
    ]
    if not open_tranches:
        return 0

    # 计算本地各方向张数，判断哪个方向确有平仓（本地 > OKX 同向）
    loc_long = sum(
        float(tr.get("remaining_qty", tr.get("qty", 0)) or 0)
        for tr in open_tranches
        if tr.get("direction", "long") != "short"
    )
    loc_short = sum(
        float(tr.get("remaining_qty", tr.get("qty", 0)) or 0)
        for tr in open_tranches
        if tr.get("direction", "long") == "short"
    )
    closed_long = okx_long is None or loc_long - float(okx_long) > 0.01
    closed_short = okx_short is None or loc_short - float(okx_short) > 0.01

    fills = _fetch_bot_fills(client)
    # P0 2026-07-03: 已入账的 close_ord_id 不得重复回补 —— record_close_leg 的
    # merge 分支会用 stale tranche 数据覆盖 bot 已写入的正确腿（14:27 事故根因）
    state_now = load_state(BASE)
    booked_close_ids = {
        (l.get("close_ord_id") or "").strip()
        for l in state_now.get("realized_legs", [])
        if (l.get("close_ord_id") or "").strip()
    }
    recorded = 0
    for tr in open_tranches:
        sid = (tr.get("strategy_id") or "").strip()
        if sid not in STRATEGY_IDS:
            continue
        _dir = tr.get("direction", "long")
        if _dir == "short" and not closed_short:
            continue
        if _dir != "short" and not closed_long:
            continue
        entry_ms = int(float(tr.get("entry_time", 0) or 0) * 1000)
        qty = float(tr.get("qty", tr.get("remaining_qty", 0)) or 0)
        if qty <= 0:
            continue
        open_oid = (tr.get("open_ord_id") or "").strip()

        # P0 2026-07-03: 平仓 fill 必须与 tranche 同方向（posSide 匹配），
        # 否则会把平多 fill 配到旧空 tranche 上生成假腿（-14.34/-17.52 事故根因）
        want_pos_side = "short" if _dir == "short" else "long"
        close_candidates = []
        for row in fills:
            cl = row.get("clOrdId", "") or ""
            m = CL_PAT.search(cl)
            if not m or m.group(1) != sid or m.group(2) != "close":
                continue
            if (row.get("posSide") or "").lower() != want_pos_side:
                continue
            ts = int(row.get("ts") or 0)
            if reset_ms > 0 and ts < reset_ms:
                continue
            if entry_ms > 0 and ts < entry_ms:
                continue
            if (row.get("ordId") or "").strip() in booked_close_ids:
                continue
            close_candidates.append(row)

        by_close_ord: dict[str, list] = {}
        for row in close_candidates:
            by_close_ord.setdefault(row.get("ordId", ""), []).append(row)

        best = None
        for oid, rows in by_close_ord.items():
            agg = _aggregate_close_ord(fills, oid)
            if not agg:
                continue
            if abs(float(agg["total_sz"]) - qty) > 0.05:
                continue
            if best is None or agg["fillTime"] > best["fillTime"]:
                best = agg

        if not best:
            print(f"WARN: no close fill for open tranche {sid} qty={qty} open={open_oid}")
            continue

        close_oid = best["ordId"]
        exit_px = float(best["avg_px"])
        fee = float(best["fee"])
        direction = tr.get("direction", "long")
        entry_px = float(tr.get("entry_price", 0) or 0)
        pnl = b.attributed_pnl_from_prices(direction, entry_px, exit_px, qty, fee)
        if pnl is None:
            continue

        tracker_entry = {
            "position": True,
            "direction": direction,
            "entry_price": entry_px,
            "entry_time": tr.get("entry_time", 0),
            "qty": qty,
            "open_ord_id": open_oid,
        }
        leg = record_close_leg(
            sid,
            tracker_entry,
            close_oid,
            pnl,
            fee,
            exit_px,
            "对账平仓回补",
            BASE,
        )
        if leg:
            ct = float(best["fillTime"]) / 1000.0
            # 对账只回填6月15日之后的leg
            if ct < CUTOFF_TS:
                print(f"  [skip] 跳过{ct} < CUTOFF_TS")
                continue
            close_ts = ct
            state = load_state(BASE)
            for existing in state.get("realized_legs", []):
                if (existing.get("close_ord_id") or "").strip() == close_oid:
                    existing["close_time"] = close_ts
                    break
            save_state(state, BASE)
            recorded += 1
            print(
                f"RECORD_CLOSE {sid} {direction} {entry_px:.2f}→{exit_px:.2f} "
                f"pnl={pnl:.4f} close={close_oid}"
            )
    return recorded


def save_tracker(attribution: list[dict], okx_avg: float, okx_entry_time: float):
    """写入 position_*.json（按策略汇总）+ state tranches（每笔归因一行）。"""
    attribution = [
        a
        for a in attribution
        if (a.get("open_ord_id") or "").strip() not in ("okx_net_pad", "sync_snapshot")
    ]
    tracker = {sid: empty_position() for sid in STRATEGY_IDS}
    by_sid: dict[str, dict] = {}

    for i, a in enumerate(attribution):
        sid = a["sid"]
        qty = float(a["qty"])
        ep = float(a["entry_price"] or okx_avg or 0)
        et = float(a.get("entry_time") or okx_entry_time)
        print(f"SET {sid} {a['direction']} qty={qty} @ {ep:.2f} ord={a['open_ord_id']}")

        if sid not in by_sid:
            by_sid[sid] = {
                "position": True,
                "direction": a["direction"],
                "qty": 0.0,
                "px_sum": 0.0,
                "entry_time": et,
                "open_ord_id": a["open_ord_id"],
            }
        g = by_sid[sid]
        g["qty"] += qty
        g["px_sum"] += ep * qty
        g["entry_time"] = min(g["entry_time"], et)
        g["open_ord_id"] = a["open_ord_id"]

    for sid, g in by_sid.items():
        ep = g["px_sum"] / g["qty"] if g["qty"] else okx_avg
        tracker[sid] = {
            "position": True,
            "direction": g["direction"],
            "entry_price": round(ep, 2),
            "entry_time": g["entry_time"],
            "qty": round(g["qty"], 4),
            "remaining_qty": round(g["qty"], 4),
            "open_ord_id": g["open_ord_id"],
            "tranche_id": f"{sid}-{int(g['entry_time'] * 1000)}-1",
            "margin_locked": round((g["qty"] * ep * 0.01) / 5, 2) if ep else 0,
        }

    # 先写 state，再写 position（与 main.save_all 一致，避免半写分裂）
    reconcile_state_from_tracker(tracker, BASE, logger=None)
    for sid, data in tracker.items():
        tmp = os.path.join(BASE, f"position_{sid}.json.tmp")
        with open(tmp, "w", encoding="utf-8") as fp:
            json.dump(data, fp)
        os.replace(tmp, os.path.join(BASE, f"position_{sid}.json"))
    return tracker


def _is_fully_aligned(align: dict) -> bool:
    return bool(
        align.get("net_aligned")
        and align.get("gross_aligned")
        and align.get("direction_aligned")
    )


def _maintenance_base_dir() -> str:
    if os.environ.get("HERMES_A2_FIXTURE") == "1":
        state_path = os.environ.get("HERMES_STATE_PATH", "").strip()
        if state_path and os.path.isfile(state_path):
            return os.path.dirname(os.path.abspath(state_path))
    return BASE


def _worker_script_path() -> str:
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "state_maintenance_worker.py",
    )


SUMMARY_PREFIX = "HERMES_MAINT_SUMMARY="


def _parse_worker_summary(stdout: str) -> dict:
    for line in reversed((stdout or "").strip().splitlines()):
        if line.startswith(SUMMARY_PREFIX):
            try:
                return json.loads(line[len(SUMMARY_PREFIX) :])
            except json.JSONDecodeError:
                return {}
    return {}


def _empty_maint_stats() -> dict:
    return {
        "worker_rc": 0,
        "repair": False,
        "dry_run": True,
        "prune_changed": 0,
        "pruned_syn": 0,
        "legs_deduped": False,
        "would_change": False,
        "state_changed": False,
        "written": False,
        "did_lifo_rebuild": False,
        "n_close": 0,
        "added": 0,
        "updated": 0,
        "okx_flat": False,
    }


def invoke_maintenance_worker(
    *,
    repair: bool,
    dry_run: bool,
    extra_env: dict | None = None,
) -> dict:
    """A2.7：reconcile 维护唯一路由至 worker；解析 JSON summary。"""
    base_dir = _maintenance_base_dir()
    cmd = [
        sys.executable,
        _worker_script_path(),
        "--base-dir",
        base_dir,
        "--prune",
        "--rebuild-trades",
        "--sync-equity",
    ]
    if repair:
        cmd.append("--repair")
        if not dry_run:
            cmd.extend(["--confirm", "--no-dry-run"])
    print(
        f"MAINTENANCE | repair={repair} dry_run={dry_run} "
        f"base_dir={base_dir} → state_maintenance_worker"
    )
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if proc.stdout:
        print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n")
    if proc.stderr:
        print(proc.stderr, file=sys.stderr, end="" if proc.stderr.endswith("\n") else "\n")

    summary = _parse_worker_summary(proc.stdout)
    stats = _empty_maint_stats()
    stats.update(
        {
            k: summary[k]
            for k in (
                "prune_changed",
                "pruned_syn",
                "legs_deduped",
                "would_change",
                "state_changed",
                "written",
                "rebuild_rows",
                "equity_updated",
            )
            if k in summary
        }
    )
    stats["worker_rc"] = proc.returncode
    stats["repair"] = repair
    stats["dry_run"] = dry_run
    if proc.returncode != 0:
        print(f"CRITICAL | maintenance worker exit {proc.returncode}")
    elif stats.get("would_change") and not stats.get("written"):
        print("AUDIT_WOULD_CHANGE | maintenance drift detected (readonly/dry-run)")
    return stats


def audit_maintenance(*, repair: bool = False, dry_run: bool = True) -> dict:
    """三层对齐审计：默认不 spawn worker；仅 --repair 时路由 worker。"""
    if not repair:
        print("AUDIT | readonly — skip maintenance worker (use --repair to route)")
        return _empty_maint_stats()
    print("REPAIR | state maintenance routed to worker")
    return invoke_maintenance_worker(repair=True, dry_run=dry_run)


def _print_summary(client, bf: dict, stats: dict) -> dict:
    from okx_net_alignment import check_alignment  # noqa: E402

    state = load_state(BASE)
    total_legs = len(state.get("realized_legs") or [])
    align = check_alignment(client, BASE)
    added = int(bf.get("added", 0) or 0)
    updated = int(bf.get("updated", 0) or 0)
    print(
        f"SUMMARY | 新增 {added} 笔 | 更新 {updated} 笔 | "
        f"realized_legs 总数 {total_legs} | net {state.get('net_position')} | "
        f"tranches {[(t['strategy_id'], t['direction'], t.get('remaining_qty', t.get('qty'))) for t in state.get('tranches', [])]}"
    )
    print(
        f"ALIGN | okx={align.get('okx_net')} state={align.get('state_net')} "
        f"pos_files={align.get('position_net')} aligned={align.get('aligned')}"
    )
    return align


def main():
    import argparse

    ap = argparse.ArgumentParser(
        description="OKX 对账：默认审计（不改 open tranche）；失配修复须 --apply"
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help="允许 LIFO 重写 open tranche、回补 close leg、backfill（须 Louis 批准）",
    )
    ap.add_argument(
        "--repair",
        action="store_true",
        help="state 维护写操作路由至 state_maintenance_worker（非 LIFO --apply）",
    )
    ap.add_argument(
        "--no-dry-run",
        action="store_true",
        help="--repair 真实写入（须 HERMES_MAINTENANCE_APPLY 或 fixture）",
    )
    args = ap.parse_args()
    repair_dry_run = not args.no_dry_run

    if args.repair and os.environ.get("HERMES_A2_FIXTURE") == "1":
        print("A2.6 FIXTURE | repair routing test (skip OKX)")
        stats = audit_maintenance(repair=True, dry_run=repair_dry_run)
        print("P19_2C_A2_6_FIXTURE_REPAIR_ROUTING_OK")
        sys.exit(stats.get("worker_rc", 0))

    from api import OKXClient  # noqa: E402

    client = OKXClient()
    from okx_net_alignment import check_alignment, pad_attribution_to_net, attribution_gross_gaps  # noqa: E402

    pre_align = check_alignment(client, BASE)
    if _is_fully_aligned(pre_align) and not args.apply:
        print("AUDIT | 三层已对齐 — bot open tranche 为真源，跳过 LIFO/回补")
        stats = audit_maintenance(repair=args.repair, dry_run=repair_dry_run)
        if stats.get("worker_rc", 0) != 0:
            sys.exit(int(stats["worker_rc"]))
        war_needed = bool(
            stats.get("state_changed")
            or stats.get("written")
            or (
                stats.get("would_change")
                and args.repair
                and not repair_dry_run
            )
        )
        import build_war_report as b  # noqa: E402

        if war_needed:
            b.refresh_war_report_accurate(trigger_sid="reconcile_audit")
        else:
            print("SKIP war refresh | 审计无变更，等待 bot 开/平仓触发")
        _print_summary(client, {}, stats)
        return

    if not _is_fully_aligned(pre_align) and not args.apply:
        mismatches = pre_align.get("direction_mismatches") or []
        print(
            f"CRITICAL | 未对齐 net={pre_align.get('net_aligned')} "
            f"gross={pre_align.get('gross_aligned')} "
            f"dir={pre_align.get('direction_aligned')} — 仅审计，不自动修复"
        )
        if mismatches:
            print("DIR_MISMATCH | " + "; ".join(mismatches))
        print("HINT | 人工确认后: venv/bin/python3 scripts/reconcile_all_from_okx.py --apply")
        audit_maintenance(repair=False, dry_run=True)
        _print_summary(client, {}, {})
        sys.exit(2)

    # --apply 修复路径（失配且 Louis 批准）
    gross = fetch_okx_gross(client)
    long_qty = gross["long"]
    short_qty = gross["short"]
    net_pos = int(round(gross["net"]))
    okx_avg = gross["long_avg"] or gross["short_avg"]
    okx_entry_time = min(gross["long_entry_time"], gross["short_entry_time"])

    reset_ms = 0
    reset_file = os.path.join(BASE, "war_reset_after_ms.txt")
    if os.path.exists(reset_file):
        try:
            reset_ms = int(open(reset_file).read().strip())
        except (OSError, ValueError):
            reset_ms = 0

    orders = fetch_bot_open_orders(client, reset_ms)

    # 多腿、空腿分别 LIFO 归因（不 pad 合成腿）
    attr: list[dict] = []
    if long_qty >= 0.01:
        n_long = int(round(long_qty))
        al = lifo_attribution(n_long, orders)
        al = pad_attribution_to_net(
            n_long, al, gross["long_avg"], gross["long_entry_time"], orders
        )
        attr += al
    if short_qty >= 0.01:
        n_short = int(round(short_qty))
        ash = lifo_attribution(-n_short, orders)
        ash = pad_attribution_to_net(
            -n_short, ash, gross["short_avg"], gross["short_entry_time"], orders
        )
        attr += ash

    attr_qty = sum(float(a.get("qty", 0) or 0) for a in attr)
    print(
        f"OKX long={long_qty:.2f} short={short_qty:.2f} net={net_pos} "
        f"open_orders={len(orders)} attribution={len(attr)} attr_qty={attr_qty:.2f}"
    )
    backup()

    okx_flat = long_qty < 0.01 and short_qty < 0.01
    did_lifo_rebuild = False

    # 先回补确有平仓的方向（side-aware：本地某向 > OKX 同向腿才处理）
    n_close = record_closes_before_flat(client, reset_ms, long_qty, short_qty)
    if n_close:
        print(f"recorded {n_close} close leg(s)")

    if okx_flat:
        tracker = {sid: empty_position() for sid in STRATEGY_IDS}
        for sid, data in tracker.items():
            path = os.path.join(BASE, f"position_{sid}.json")
            with open(path + ".tmp", "w", encoding="utf-8") as fp:
                json.dump(data, fp)
            os.replace(path + ".tmp", path)
        reconcile_state_from_tracker(tracker, BASE, logger=None)
        print("CLEARED all local positions (OKX 多空腿均为0)")
    else:
        pre_align = check_alignment(client, BASE)
        if _is_fully_aligned(pre_align):
            print("SKIP save_tracker | 本地已三层对齐，保留 bot 归因不重写")
        else:
            gaps = attribution_gross_gaps(long_qty, short_qty, attr)
            if gaps:
                print(
                    "CRITICAL | LIFO gap " + "; ".join(gaps)
                    + " — 禁止 save_tracker（禁止 okx_net_pad）"
                )
            else:
                print(
                    f"MISALIGNED net={pre_align.get('net_aligned')} "
                    f"gross={pre_align.get('gross_aligned')} "
                    f"direction={pre_align.get('direction_aligned')} → LIFO 兜底重建"
                )
                save_tracker(attr, okx_avg, okx_entry_time)
                did_lifo_rebuild = True

    import build_war_report as b  # noqa: E402

    # okx_flat 清仓为 OKX 权威，非 LIFO 猜测
    if okx_flat:
        b.reconcile_state_from_position_files(BASE)

    # 2) safe backfill（48h 内、最多 8 条）— 先于维护投影
    bf: dict = {}
    try:
        from backfill_missing_legs import backfill_missing_legs  # noqa: E402

        bf = backfill_missing_legs(refresh_war=False, max_add=8, safe=True)
        print(f"backfill: {bf}")
    except Exception as ex:
        print(f"WARN backfill_missing_legs: {ex}")

    # 3) state/trades 维护 — 路由 worker（唯一 writer，含 prune/dedupe/rebuild/sync）
    maint_env = {"HERMES_MAINTENANCE_APPLY": "1"}
    maint = invoke_maintenance_worker(
        repair=True,
        dry_run=False,
        extra_env=maint_env,
    )
    if maint.get("worker_rc", 0) != 0:
        print("CRITICAL | maintenance worker failed during --apply")
        sys.exit(2)
    pruned_syn = int(maint.get("pruned_syn", 0) or 0)
    legs_deduped = bool(maint.get("legs_deduped"))
    prune_changed = int(maint.get("prune_changed", 0) or 0)
    n = int(maint.get("rebuild_rows", 0) or 0)
    if prune_changed:
        print(f"maintenance prune_inflated changed={prune_changed}")
    if n:
        print(f"trades rebuilt: {n} rows")

    # 4) refresh war report — 仅平仓/回补/失配修复时
    added = int(bf.get("added", 0) or 0)
    updated = int(bf.get("updated", 0) or 0)
    war_needed = (
        n_close > 0
        or added > 0
        or updated > 0
        or legs_deduped
        or prune_changed > 0
        or maint.get("written")
        or okx_flat
        or did_lifo_rebuild
        or pruned_syn > 0
    )
    if war_needed:
        b.refresh_war_report_accurate(trigger_sid="reconcile")
    else:
        print("SKIP war refresh | 无平仓/回补/失配变更，等待 bot 平仓触发")

    align = _print_summary(client, bf, {
        "n_close": n_close,
        "pruned_syn": pruned_syn,
        "legs_deduped": legs_deduped,
        "did_lifo_rebuild": did_lifo_rebuild,
        "okx_flat": okx_flat,
    })
    if not align.get("aligned"):
        print("CRITICAL | OKX 与本地仍未对齐，请人工核查 fills/LIFO")
        sys.exit(2)


if __name__ == "__main__":
    main()
