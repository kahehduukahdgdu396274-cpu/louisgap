#!/usr/bin/env python3
"""Reconcile all strategy position_*.json + state.json to match OKX net via LIFO open fills."""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from collections import defaultdict
from datetime import datetime

BASE = os.environ.get("OKX_BOT_DIR", "/home/admin/okx_bot")
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "scripts"))

from api import OKXClient  # noqa: E402
from position_state import (  # noqa: E402
    load_state,
    reconcile_state_from_tracker,
    record_close_leg,
    save_state,
)

SYMBOL = "BTC-USDT-SWAP"
STRATEGY_IDS = ["003", "006", "009", "010", "011", "012", "013", "014"]
CL_PAT = re.compile(r"str(003|006|009|010|011|012|013|014)(open|close)")


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


def _fetch_bot_fills(client: OKXClient) -> list[dict]:
    seen_bills: set[str] = set()
    raw: list[dict] = []
    for _ in range(15):
        r = client.request(
            "GET",
            f"/api/v5/trade/fills?instType=SWAP&instId={SYMBOL}&limit=100",
        )
        for row in r.get("data", []):
            bill = row.get("billId", "")
            if bill in seen_bills:
                continue
            seen_bills.add(bill)
            raw.append(row)
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


def record_closes_before_flat(client: OKXClient, reset_ms: int = 0) -> int:
    """OKX 已空仓但本地仍有 tranche 时，用平仓 fill 回补 realized_leg（战报真源）。"""
    import build_war_report as b  # noqa: E402

    state = load_state(BASE)
    open_tranches = [
        tr
        for tr in state.get("tranches", [])
        if float(tr.get("remaining_qty", tr.get("qty", 0)) or 0) > 0
    ]
    if not open_tranches:
        return 0

    fills = _fetch_bot_fills(client)
    recorded = 0
    for tr in open_tranches:
        sid = (tr.get("strategy_id") or "").strip()
        if sid not in STRATEGY_IDS:
            continue
        entry_ms = int(float(tr.get("entry_time", 0) or 0) * 1000)
        qty = float(tr.get("qty", tr.get("remaining_qty", 0)) or 0)
        if qty <= 0:
            continue
        open_oid = (tr.get("open_ord_id") or "").strip()

        close_candidates = []
        for row in fills:
            cl = row.get("clOrdId", "") or ""
            m = CL_PAT.search(cl)
            if not m or m.group(1) != sid or m.group(2) != "close":
                continue
            ts = int(row.get("ts") or 0)
            if reset_ms > 0 and ts < reset_ms:
                continue
            if entry_ms > 0 and ts < entry_ms:
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
            close_ts = float(best["fillTime"]) / 1000.0
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

    for sid, data in tracker.items():
        tmp = os.path.join(BASE, f"position_{sid}.json.tmp")
        with open(tmp, "w", encoding="utf-8") as fp:
            json.dump(data, fp)
        os.replace(tmp, os.path.join(BASE, f"position_{sid}.json"))

    state = load_state(BASE)
    tranches = []
    for i, a in enumerate(attribution):
        sid = a["sid"]
        qty = float(a["qty"])
        ep = float(a["entry_price"] or okx_avg or 0)
        et = float(a.get("entry_time") or okx_entry_time)
        tranches.append(
            {
                "tranche_id": f"{sid}-{int(et * 1000)}-{i + 1}",
                "strategy_id": sid,
                "direction": a["direction"],
                "entry_price": round(ep, 2),
                "entry_time": et,
                "qty": qty,
                "remaining_qty": qty,
                "margin_locked": round((qty * ep * 0.01) / 5, 2) if ep else 0,
                "open_ord_id": a.get("open_ord_id") or "",
                "open_fee": 0.0,
                "hold_reason": "okx对账",
            }
        )
    state["tranches"] = tranches
    save_state(state, BASE)
    return tracker


def main():
    client = OKXClient()
    net_pos, okx_avg, okx_entry_time = fetch_okx_net(client)

    reset_ms = 0
    reset_file = os.path.join(BASE, "war_reset_after_ms.txt")
    if os.path.exists(reset_file):
        try:
            reset_ms = int(open(reset_file).read().strip())
        except (OSError, ValueError):
            reset_ms = 0

    orders = fetch_bot_open_orders(client, reset_ms)
    attr = lifo_attribution(net_pos, orders)

    from okx_net_alignment import check_alignment, pad_attribution_to_net  # noqa: E402

    attr = pad_attribution_to_net(net_pos, attr, okx_avg, okx_entry_time, orders)
    attr_qty = sum(float(a.get("qty", 0) or 0) for a in attr)
    print(
        f"OKX net={net_pos} avgPx={okx_avg:.2f} open_orders={len(orders)} "
        f"attribution={len(attr)} attr_qty={attr_qty:.2f}"
    )
    backup()

    if net_pos == 0:
        n_close = record_closes_before_flat(client, reset_ms)
        if n_close:
            print(f"recorded {n_close} close leg(s) before flat clear")
        tracker = {sid: empty_position() for sid in STRATEGY_IDS}
        for sid, data in tracker.items():
            path = os.path.join(BASE, f"position_{sid}.json")
            with open(path + ".tmp", "w", encoding="utf-8") as fp:
                json.dump(data, fp)
            os.replace(path + ".tmp", path)
        reconcile_state_from_tracker(tracker, BASE, logger=None)
        print("CLEARED all local positions (OKX flat)")
    else:
        save_tracker(attr, okx_avg, okx_entry_time)

    import build_war_report as b  # noqa: E402

    # 1) 有仓时已由 save_tracker 写入多 tranche；仅空仓时允许 position 同步
    if net_pos == 0:
        b.reconcile_state_from_position_files(BASE)

    # 2) 剔除 OKX回补 膨胀腿
    try:
        b.prune_inflated_state_legs(base_dir=BASE)
    except Exception as ex:
        print(f"WARN prune_inflated: {ex}")

    # 3) safe backfill（48h 内、最多 8 条）
    bf: dict = {}
    try:
        from backfill_missing_legs import backfill_missing_legs  # noqa: E402

        bf = backfill_missing_legs(refresh_war=False, max_add=8, safe=True)
        print(f"backfill: {bf}")
    except Exception as ex:
        print(f"WARN backfill_missing_legs: {ex}")

    # 4) dedupe realized_legs by close_ord_id
    state = load_state(BASE)
    legs = state.get("realized_legs") or []
    deduped = b.dedupe_realized_legs(legs)
    if len(deduped) != len(legs):
        state["realized_legs"] = deduped
        save_state(state, BASE)
        print(f"dedupe: {len(legs)} -> {len(deduped)} legs")

    # 5) rebuild trades.csv
    n = b.rebuild_trades_from_state()
    b.dedup_trades_csv()
    b.clean_ghost_rows()
    print(f"trades rebuilt: {n} rows")

    # 6) refresh war report
    added = int(bf.get("added", 0) or 0)
    updated = int(bf.get("updated", 0) or 0)
    if added > 0 or updated > 0:
        b.refresh_war_report_accurate(trigger_sid="reconcile")
    else:
        b.refresh_war_report_accurate(trigger_sid="reconcile")

    state = load_state(BASE)
    total_legs = len(state.get("realized_legs") or [])
    align = check_alignment(client, BASE)
    print(
        f"SUMMARY | 新增 {added} 笔 | 更新 {updated} 笔 | "
        f"realized_legs 总数 {total_legs} | net {state.get('net_position')} | "
        f"tranches {[(t['strategy_id'], t['direction'], t.get('remaining_qty', t.get('qty'))) for t in state.get('tranches', [])]}"
    )
    print(
        f"ALIGN | okx={align.get('okx_net')} state={align.get('state_net')} "
        f"pos_files={align.get('position_net')} aligned={align.get('aligned')}"
    )
    if not align.get("aligned"):
        print("CRITICAL | OKX 与本地仍未对齐，请人工核查 fills/LIFO")
        sys.exit(2)


if __name__ == "__main__":
    main()
