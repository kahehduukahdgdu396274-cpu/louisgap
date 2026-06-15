#!/usr/bin/env python3
"""治理 state.json realized_legs：剔除 OKX回补 膨胀腿，保留 bot 可信归因。"""
from __future__ import annotations

import argparse
import json
import os
import sys

BASE = os.environ.get("OKX_BOT_DIR", "/home/admin/okx_bot")
sys.path.insert(0, BASE)
SCRIPTS = os.path.join(BASE, "scripts")
if os.path.isdir(SCRIPTS):
    sys.path.insert(0, SCRIPTS)

import build_war_report as b  # noqa: E402
from position_state import load_state, save_state  # noqa: E402

STATE_JSON = os.path.join(BASE, "state.json")

# bot 运行时写入的归因；禁止 cron/backfill 写入 OKX回补（历史膨胀源）
TRUSTED_LEG_REASONS = frozenset(
    {"OKX开平配对", "bot平仓", "对账平仓回补", "策略归因"}
)
UNTRUSTED_REASONS = frozenset({"OKX回补"})
LEG_COUNT_WARN = 25
LEG_COUNT_HARD_STOP = 80


def govern_state_legs(
    *,
    dry_run: bool = False,
    allow_untrusted: bool = False,
    refresh_war: bool = False,
) -> dict:
    state = load_state(BASE)
    legs = state.get("realized_legs") or []
    before = len(legs)
    untrusted = [l for l in legs if (l.get("reason") or "") in UNTRUSTED_REASONS]
    kept = legs if allow_untrusted else [l for l in legs if (l.get("reason") or "") in TRUSTED_LEG_REASONS]

    kept = b.dedupe_realized_legs(kept)
    kept, removed_verify = b.prune_unverified_legs(kept, strict_open=False)
    kept = b.prune_overlap_independent_legs(kept)

    stats = {
        "before": before,
        "after": len(kept),
        "dropped_untrusted": before - len(kept) - len(untrusted) if allow_untrusted else len(untrusted),
        "dropped_untrusted_reason": len(untrusted) if not allow_untrusted else 0,
        "pruned_verify": len(removed_verify),
        "pnl_after": round(sum(float(l.get("net_pnl", 0) or 0) for l in kept), 2),
    }

    if len(kept) > LEG_COUNT_HARD_STOP:
        b.log(
            f"[govern] HARD_STOP legs={len(kept)} > {LEG_COUNT_HARD_STOP}，"
            "请人工核对后再 --allow-untrusted"
        )
        stats["hard_stop"] = True
        return stats
    if len(kept) > LEG_COUNT_WARN:
        b.log(f"[govern] WARN legs={len(kept)} > {LEG_COUNT_WARN}")

    if dry_run:
        b.log(f"[govern] dry-run {stats}")
        return stats

    state["realized_legs"] = kept
    save_state(state, BASE)
    b.log(
        f"[govern] {before}→{len(kept)} legs "
        f"drop_untrusted={stats['dropped_untrusted_reason']} "
        f"verify_removed={stats['pruned_verify']} pnl={stats['pnl_after']}"
    )

    if refresh_war:
        b.refresh_war_report_accurate(trigger_sid="govern")

    return stats


def catch_up_missing_closes(*, dry_run: bool = False, max_add: int = 5) -> dict:
    """bot 离线期间遗漏的平仓：仅补 verified 且 state 缺失的 close_ord_id（对账平仓回补）。"""
    state = load_state(BASE)
    existing = state.get("realized_legs") or []
    state_ids = {
        (leg.get("close_ord_id") or "").strip()
        for leg in existing
        if (leg.get("close_ord_id") or "").strip()
    }

    if len(state_ids) >= LEG_COUNT_HARD_STOP:
        b.log(f"[catchup] skip state already {len(state_ids)} legs (hard stop)")
        return {"added": 0, "skipped": "hard_stop"}

    fills = b.fetch_fills() or []
    reset_ms = b.load_reset_after_ms()
    if reset_ms > 0:
        fills = [f for f in fills if int(f.get("fillTime", 0) or 0) >= reset_ms]

    candidates = []
    for trip in b.pair_round_trips(fills):
        cid = (trip.get("ordId") or "").strip()
        if not cid or cid in state_ids:
            continue
        leg = b.round_trip_to_realized_leg(trip)
        if not leg:
            continue
        ok, reason = b.verify_realized_leg(leg, strict_open=False)
        if not ok:
            b.log(f"[catchup] skip close={cid} reason={reason}")
            continue
        leg["reason"] = "对账平仓回补"
        candidates.append(leg)

    candidates.sort(key=lambda x: float(x.get("close_time", 0) or 0), reverse=True)
    candidates = candidates[:max_add]

    if not candidates:
        return {"added": 0, "updated": 0}

    if dry_run:
        for leg in candidates:
            b.log(
                f"[catchup] dry-run {leg.get('strategy_id')} "
                f"pnl={leg.get('net_pnl')} close={leg.get('close_ord_id')}"
            )
        return {"added": len(candidates), "dry_run": True}

    merged, stats = b.merge_realized_legs_by_ord_id(existing, candidates)
    state["realized_legs"] = b.dedupe_realized_legs(merged)
    save_state(state, BASE)
    b.log(f"[catchup] added={stats.get('added', 0)} total={len(state['realized_legs'])}")
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-untrusted", action="store_true")
    ap.add_argument("--refresh-war", action="store_true")
    ap.add_argument("--catch-up", action="store_true", help="仅补缺失 verified close")
    args = ap.parse_args()

    if args.catch_up:
        print(catch_up_missing_closes(dry_run=args.dry_run))
    else:
        print(
            govern_state_legs(
                dry_run=args.dry_run,
                allow_untrusted=args.allow_untrusted,
                refresh_war=args.refresh_war,
            )
        )
