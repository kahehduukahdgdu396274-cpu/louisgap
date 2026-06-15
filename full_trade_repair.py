#!/usr/bin/env python3
"""全量交易数据修复：position↔state 同步、去重、超额平仓剔除、盈亏归因、重建战报。"""
import json
import os
import shutil
import sys
from datetime import datetime

BASE = "/home/admin/okx_bot"
sys.path.insert(0, BASE)

import build_war_report as b  # noqa: E402
import generate_war_report_v3 as g  # noqa: E402

POOL_MEMBERS = b.POOL_MEMBERS
STATE_JSON = b.STATE_JSON
EQ_PATH = os.path.join(BASE, "strategy_eq.json")


def backup_files():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    for name in ("trades.csv", "state.json", "strategy_eq.json"):
        src = os.path.join(BASE, name)
        if os.path.exists(src):
            dst = os.path.join(BASE, f"{name}.bak_repair_{ts}")
            shutil.copy2(src, dst)
            print(f"backup {src} -> {dst}")


def recalc_strategy_eq_from_legs(legs):
    """按修正后 realized_legs 重算各策略权益（reset 后 FIFO 回放）。"""
    eq = dict(b.DEFAULT_EQ)
    if os.path.exists(EQ_PATH):
        try:
            with open(EQ_PATH, encoding="utf-8") as f:
                saved = json.load(f)
            for k, v in saved.items():
                eq[k] = float(v)
        except (OSError, ValueError, TypeError):
            pass

    reset_ms = b.load_reset_after_ms()
    ordered = sorted(
        [
            leg
            for leg in legs
            if (leg.get("close_ord_id") or "").strip()
            and (reset_ms <= 0 or int(float(leg.get("close_time", 0) or 0) * 1000) >= reset_ms)
        ],
        key=lambda x: float(x.get("close_time", 0) or 0),
    )

    # 从当前权益倒推基线，再用修正腿正向回放
    closed_rows = []
    for leg in ordered:
        row = b.realized_leg_to_row(leg, eq)
        if row:
            closed_rows.append(row)
    baseline = b._rewind_equity_baseline(eq, closed_rows)
    running = dict(baseline)
    for leg in ordered:
        sid = (leg.get("strategy_id") or "").strip()
        try:
            pnl = float(leg.get("net_pnl") or 0)
        except (TypeError, ValueError):
            pnl = 0.0
        if sid in POOL_MEMBERS:
            running["POOL_009_012"] = max(1, round(running.get("POOL_009_012", 250) + pnl, 2))
        elif sid:
            running[sid] = max(1, round(running.get(sid, b.DEFAULT_EQ.get(sid, 200)) + pnl, 2))
        leg["equity_after"] = (
            running["POOL_009_012"] if sid in POOL_MEMBERS else running.get(sid)
        )

    tmp = EQ_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(running, f)
    os.replace(tmp, EQ_PATH)
    print(f"OK: strategy_eq replayed -> {running}")
    return running


def main():
    print("=== FULL TRADE REPAIR START ===")
    backup_files()

    b.reconcile_state_from_position_files(BASE)
    stats = b.fix_state_realized_legs(save=True)
    print(f"state legs: {stats}")

    with open(STATE_JSON, encoding="utf-8") as f:
        state = json.load(f)
    recalc_strategy_eq_from_legs(state.get("realized_legs") or [])
    with open(STATE_JSON, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)

    n = b.rebuild_trades_from_state()
    print(f"rebuilt trades rows: {n}")
    b.repair_closed_pnl()
    b.dedup_trades_csv()
    b.dedup_same_moment_trades()
    b.stamp_closed_equity(force=True)

    g.main()
    print("=== FULL TRADE REPAIR DONE ===")


if __name__ == "__main__":
    main()
