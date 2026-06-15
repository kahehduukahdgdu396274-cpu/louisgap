#!/usr/bin/env python3
"""按 close_ord_id 安全回补 state.json 缺失平仓腿（禁止 OKX回补 / size-FIFO 膨胀）。"""
from __future__ import annotations

import json
import os
import sys
import time

BASE = os.environ.get("OKX_BOT_DIR", "/home/admin/okx_bot")
sys.path.insert(0, BASE)
SCRIPTS = os.path.join(BASE, "scripts")
if os.path.isdir(SCRIPTS):
    sys.path.insert(0, SCRIPTS)

import build_war_report as b  # noqa: E402

STATE_JSON = os.path.join(BASE, "state.json")
LEG_COUNT_HARD_STOP = 80
DEFAULT_MAX_ADD = 8
LOOKBACK_HOURS = 48


def _state_close_ord_ids(state: dict) -> set[str]:
    return {
        (leg.get("close_ord_id") or "").strip()
        for leg in state.get("realized_legs") or []
        if (leg.get("close_ord_id") or "").strip()
    }


def _missing_close_candidates(
    *,
    state_close_ids: set[str],
    max_add: int = DEFAULT_MAX_ADD,
    safe: bool = True,
    lookback_hours: int = LOOKBACK_HOURS,
):
    """safe=True：仅时间序 pair_round_trips + verify；仅最近 lookback_hours 小时。"""
    if len(state_close_ids) >= LEG_COUNT_HARD_STOP:
        b.log(f"[backfill] HARD_STOP state={len(state_close_ids)} legs，拒绝自动回补")
        return []

    if not safe:
        b.log("[backfill] WARN --unsafe 已弃用 size-FIFO，仍走 pair_round_trips")

    cutoff = time.time() - lookback_hours * 3600
    fills = b.fetch_fills() or []
    reset_ms = b.load_reset_after_ms()
    if reset_ms > 0:
        fills = [f for f in fills if int(f.get("fillTime", 0) or 0) >= reset_ms]

    pending = []
    for trip in b.pair_round_trips(fills):
        cid = (trip.get("ordId") or "").strip()
        if not cid or cid in state_close_ids:
            continue
        leg = b.round_trip_to_realized_leg(trip)
        if not leg:
            continue
        if float(leg.get("close_time", 0) or 0) < cutoff:
            continue
        ok, reason = b.verify_realized_leg(leg, strict_open=False)
        if not ok:
            b.log(f"[backfill] skip close={cid} reason={reason}")
            continue
        row = dict(leg)
        row["reason"] = "对账平仓回补"
        # 用策略归因重算 pnl，避免 OKX fillPnl 写入 state
        direction = row.get("direction", "long")
        ep = float(row.get("entry_price", 0) or 0)
        xp = float(row.get("exit_price", 0) or 0)
        qty = float(row.get("qty", 1) or 1)
        fee = float(row.get("fee", 0) or 0)
        attr = b.attributed_pnl_from_prices(direction, ep, xp, qty, fee)
        if attr is not None:
            row["net_pnl"] = attr
        pending.append(row)
    pending.sort(key=lambda x: float(x.get("close_time", 0) or 0), reverse=True)
    return pending[:max_add]


def backfill_missing_legs(
    *,
    dry_run: bool = False,
    refresh_war: bool = True,
    max_add: int = DEFAULT_MAX_ADD,
    safe: bool = True,
    lookback_hours: int = LOOKBACK_HOURS,
):
    """仅追加 state 缺失的 verified close_ord_id；已有 ordId 走 merge_realized_leg。"""
    with open(STATE_JSON, encoding="utf-8") as f:
        state = json.load(f)

    existing = state.get("realized_legs") or []
    state_ids = _state_close_ord_ids(state)
    candidates = _missing_close_candidates(
        state_close_ids=set(state_ids),
        max_add=max_add,
        safe=safe,
        lookback_hours=lookback_hours,
    )

    if not candidates:
        b.log(f"[backfill] 无缺失 close_ord_id（state={len(state_ids)} safe={safe}）")
        return {
            "added": 0,
            "updated": 0,
            "skipped": 0,
            "state_legs": len(state_ids),
            "total_legs": len(existing),
        }

    if dry_run:
        b.log(f"[backfill] dry-run 候选 {len(candidates)} 条（{lookback_hours}h 内）")
        for leg in candidates:
            b.log(
                f"  {leg.get('strategy_id')} {leg.get('direction')} "
                f"pnl={leg.get('net_pnl')} close={leg.get('close_ord_id')}"
            )
        return {
            "added": len(candidates),
            "dry_run": True,
            "candidates": [leg.get("close_ord_id") for leg in candidates],
            "state_legs": len(state_ids),
        }

    merged, stats = b.merge_realized_legs_by_ord_id(existing, candidates)
    state["realized_legs"] = b.dedupe_realized_legs(merged)
    tmp = STATE_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(tmp, STATE_JSON)
    total = len(state["realized_legs"])
    b.log(
        f"[backfill] added={stats['added']} updated={stats['updated']} "
        f"total_legs={total} safe={safe}"
    )

    if refresh_war and (stats["added"] > 0 or stats["updated"] > 0):
        b.refresh_war_report_accurate(trigger_sid="backfill")

    stats["state_legs"] = len(state_ids)
    stats["total_legs"] = total
    return stats


def run_self_test() -> bool:
    with open(STATE_JSON, encoding="utf-8") as f:
        state = json.load(f)
    legs = state.get("realized_legs") or []
    if not legs:
        print("SELF_TEST SKIP: no realized_legs")
        return False

    pick = max(legs, key=lambda x: float(x.get("close_time", 0) or 0))
    cid = (pick.get("close_ord_id") or "").strip()
    if not cid:
        print("SELF_TEST SKIP: leg without close_ord_id")
        return False

    bak = STATE_JSON + ".selftest.bak"
    with open(bak, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)

    state["realized_legs"] = [
        leg for leg in legs if (leg.get("close_ord_id") or "").strip() != cid
    ]
    with open(STATE_JSON, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    print(f"SELF_TEST removed close_ord_id={cid}")

    stats = backfill_missing_legs(refresh_war=False, max_add=5)
    with open(STATE_JSON, encoding="utf-8") as f:
        after = json.load(f)
    restored = any(
        (leg.get("close_ord_id") or "").strip() == cid
        for leg in after.get("realized_legs") or []
    )

    if not restored:
        with open(bak, encoding="utf-8") as f:
            json.dump(json.load(f), open(STATE_JSON, "w", encoding="utf-8"), ensure_ascii=False)
        os.remove(bak)
        print(f"SELF_TEST FAIL: not restored stats={stats}")
        return False

    with open(bak, encoding="utf-8") as f:
        orig = json.load(f)
    os.replace(bak, STATE_JSON)
    with open(STATE_JSON, "w", encoding="utf-8") as f:
        json.dump(orig, f, ensure_ascii=False)

    print(f"SELF_TEST PASS restored={restored} stats={stats}")
    return True


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        ok = run_self_test()
        sys.exit(0 if ok else 1)
    dry = "--dry-run" in sys.argv
    no_war = "--no-war" in sys.argv
    unsafe = "--unsafe" in sys.argv
    stats = backfill_missing_legs(dry_run=dry, refresh_war=not no_war, safe=not unsafe)
    print(stats)
