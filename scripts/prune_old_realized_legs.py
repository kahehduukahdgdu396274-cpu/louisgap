#!/usr/bin/env python3
"""每日瘦身 state.json realized_legs：仅保留最近 N 天（默认 40，允许 30–45）。"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from datetime import datetime

BASE = os.environ.get("OKX_BOT_DIR", "/home/admin/okx_bot")
sys.path.insert(0, BASE)
SCRIPTS = os.path.join(BASE, "scripts")
if os.path.isdir(SCRIPTS):
    sys.path.insert(0, SCRIPTS)

import build_war_report as b  # noqa: E402
from position_state import load_state, save_state  # noqa: E402

STATE_JSON = os.path.join(BASE, "state.json")
DEFAULT_KEEP_DAYS = 40
MIN_KEEP_DAYS = 30
MAX_KEEP_DAYS = 45


def _clamp_days(days: int) -> int:
    return max(MIN_KEEP_DAYS, min(MAX_KEEP_DAYS, days))


def _leg_close_epoch(leg: dict) -> float:
    return float(leg.get("close_time", 0) or 0)


def prune_old_realized_legs(
    *,
    keep_days: int = DEFAULT_KEEP_DAYS,
    dry_run: bool = False,
    refresh_war: bool = False,
) -> dict:
    keep_days = _clamp_days(keep_days)
    cutoff = time.time() - keep_days * 86400
    reset_ms = b.load_reset_after_ms()

    state = load_state(BASE)
    legs = state.get("realized_legs") or []
    before = len(legs)
    before_pnl = round(sum(float(l.get("net_pnl", 0) or 0) for l in legs), 2)

    kept = []
    removed_old = 0
    removed_reset = 0
    for leg in legs:
        ct = _leg_close_epoch(leg)
        if ct <= 0:
            kept.append(leg)
            continue
        if reset_ms > 0 and int(ct * 1000) < reset_ms:
            removed_reset += 1
            continue
        if ct < cutoff:
            removed_old += 1
            continue
        kept.append(leg)

    kept = b.dedupe_realized_legs(kept)
    after_pnl = round(sum(float(l.get("net_pnl", 0) or 0) for l in kept), 2)
    stats = {
        "keep_days": keep_days,
        "cutoff_ts": cutoff,
        "cutoff_iso": datetime.fromtimestamp(cutoff).strftime("%Y-%m-%d %H:%M:%S"),
        "before": before,
        "after": len(kept),
        "removed_old": removed_old,
        "removed_pre_reset": removed_reset,
        "pnl_before": before_pnl,
        "pnl_after": after_pnl,
    }

    if dry_run:
        b.log(f"[prune_legs] dry-run {stats}")
        return stats

    if removed_old == 0 and removed_reset == 0 and before == len(kept):
        b.log(f"[prune_legs] noop legs={before} keep_days={keep_days}")
        return stats

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if os.path.exists(STATE_JSON):
        shutil.copy2(STATE_JSON, f"{STATE_JSON}.bak_prune_{ts}")

    state["realized_legs"] = kept
    save_state(state, BASE)
    b.log(
        f"[prune_legs] {before}→{len(kept)} "
        f"old={removed_old} pre_reset={removed_reset} "
        f"pnl {before_pnl}→{after_pnl} keep_days={keep_days}"
    )

    if refresh_war:
        b.rebuild_trades_from_state()
        b.refresh_war_report_accurate(trigger_sid="prune_legs")

    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--days",
        type=int,
        default=DEFAULT_KEEP_DAYS,
        help=f"保留最近 N 天已平仓腿（{MIN_KEEP_DAYS}–{MAX_KEEP_DAYS}，默认 {DEFAULT_KEEP_DAYS}）",
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--refresh-war", action="store_true", help="瘦身後重建 trades.csv 并刷新战报")
    args = ap.parse_args()
    print(prune_old_realized_legs(keep_days=args.days, dry_run=args.dry_run, refresh_war=args.refresh_war))
