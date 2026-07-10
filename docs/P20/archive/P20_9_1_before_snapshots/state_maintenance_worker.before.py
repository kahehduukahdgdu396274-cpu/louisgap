#!/usr/bin/env python3
"""
P19-2C State Maintenance Worker

Purpose:
    唯一 state/trades 维护写入入口（reconcile --repair / --apply 尾段路由至此）。

Default:
    readonly（dry-run 计算 + JSON summary）

Production write:
    --repair --confirm --no-dry-run
    AND (HERMES_A2_FIXTURE=1 OR HERMES_MAINTENANCE_APPLY=1)
    AND bot.lock 非活跃
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import sys
import time

VERSION = "P19-2C-A2.7"
SUMMARY_PREFIX = "HERMES_MAINT_SUMMARY="
DEFAULT_BASE_DIR = "/home/admin/okx_bot"
BOT_LOCK_MAX_AGE_SEC = 300


def log(msg: str) -> None:
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    print(f"[{ts}] {msg}")


def parse_args():
    parser = argparse.ArgumentParser(description="Hermes state maintenance worker")
    parser.add_argument("--repair", action="store_true", help="enable maintenance write mode")
    parser.add_argument("--prune", action="store_true", help="prune invalid state entries")
    parser.add_argument("--rebuild-trades", action="store_true", help="rebuild trades projection")
    parser.add_argument("--sync-equity", action="store_true", help="sync equity_after fields")
    parser.add_argument("--confirm", action="store_true", help="allow state write (requires --repair)")
    parser.add_argument(
        "--no-dry-run",
        action="store_true",
        help="disable dry-run (requires --repair --confirm)",
    )
    parser.add_argument("--base-dir", default=DEFAULT_BASE_DIR, help="okx_bot base directory")
    return parser.parse_args()


def resolve_base_dir(args) -> str:
    if os.environ.get("HERMES_A2_FIXTURE") == "1":
        state_path = os.environ.get("HERMES_STATE_PATH", "").strip()
        if state_path and os.path.isfile(state_path):
            return os.path.dirname(os.path.abspath(state_path))
    return args.base_dir


def effective_dry_run(args) -> bool:
    if not args.repair:
        return True
    if args.no_dry_run and args.confirm:
        return False
    return True


def emit_summary(summary: dict) -> None:
    print(f"{SUMMARY_PREFIX}{json.dumps(summary, ensure_ascii=False)}")


def _repo_paths():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    scripts = os.path.join(root, "scripts")
    for p in (root, scripts):
        if p not in sys.path:
            sys.path.insert(0, p)
    return root, scripts


def _import_bwr():
    _repo_paths()
    import build_war_report as b  # noqa: E402

    return b


def _configure_bwr(b, base_dir: str) -> dict:
    """临时绑定 BWR 路径，返回还原用快照。"""
    snap = {
        "BASE_DIR": b.BASE_DIR,
        "TRADES_CSV": b.TRADES_CSV,
        "STATE_JSON": b.STATE_JSON,
        "TRADES_LOCKFILE": b.TRADES_LOCKFILE,
    }
    b.BASE_DIR = base_dir
    b.TRADES_CSV = os.path.join(base_dir, "trades.csv")
    b.STATE_JSON = os.path.join(base_dir, "state.json")
    b.TRADES_LOCKFILE = os.path.join(base_dir, "trades.lock")
    return snap


def _restore_bwr(b, snap: dict) -> None:
    for key, val in snap.items():
        setattr(b, key, val)


def _bot_active(base_dir: str) -> bool:
    lock = os.path.join(base_dir, "bot.lock")
    if not os.path.exists(lock):
        return False
    try:
        age = time.time() - os.path.getmtime(lock)
        return age < BOT_LOCK_MAX_AGE_SEC
    except OSError:
        return False


def maintenance_write_allowed(dry_run: bool, confirm: bool, base_dir: str) -> bool:
    if dry_run or not confirm:
        return False
    if _bot_active(base_dir):
        log("BLOCK: bot.lock active — refuse maintenance write")
        return False
    if os.environ.get("HERMES_A2_FIXTURE") == "1":
        return True
    if os.environ.get("HERMES_MAINTENANCE_APPLY") == "1":
        return True
    log("BLOCK: maintenance write requires HERMES_A2_FIXTURE or HERMES_MAINTENANCE_APPLY")
    return False


def _backup_state(base_dir: str, label: str = "state.json.bak") -> str | None:
    backup_dir = os.environ.get("HERMES_A2_FIXTURE_BACKUP", "").strip()
    state_path = os.path.join(base_dir, "state.json")
    if not os.path.isfile(state_path):
        return None
    if backup_dir:
        os.makedirs(backup_dir, exist_ok=True)
        dest = os.path.join(backup_dir, label)
    else:
        dest = state_path + f".maint_bak_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(state_path, dest)
    log(f"backup: {dest}")
    return dest


def run_prune_inflated(dry_run: bool, confirm: bool, base_dir: str) -> dict:
    stats = {"prune_changed": 0, "prune_before": 0, "prune_after": 0, "written": False}
    try:
        from position_state import load_state, save_state
        b = _import_bwr()
    except Exception as ex:
        log(f"WARN prune_inflated unavailable ({ex})")
        return stats

    state_path = os.path.join(base_dir, "state.json")
    if not os.path.exists(state_path):
        log(f"WARN {state_path} missing")
        return stats

    state = load_state(base_dir)
    before, after, filtered = b.compute_prune_inflated_legs(state)
    stats.update({"prune_changed": max(0, before - after), "prune_before": before, "prune_after": after})

    if dry_run:
        if stats["prune_changed"]:
            log(f"DRY RUN prune_inflated: {before}→{after}")
        return stats

    if not maintenance_write_allowed(dry_run, confirm, base_dir):
        return stats

    if before == after:
        return stats

    _backup_state(base_dir)
    b.set_bwr_write_mode(True)
    try:
        state["realized_legs"] = filtered
        save_state(state, base_dir)
        stats["written"] = True
        log(f"APPLY prune_inflated: {before}→{after}")
    finally:
        b.set_bwr_write_mode(False)
    return stats


def run_prune_synthetic_dedupe(dry_run: bool, confirm: bool, base_dir: str) -> dict:
    stats = {"pruned_syn": 0, "legs_deduped": False, "written": False}
    try:
        b = _import_bwr()
        from position_state import load_state, save_state
    except Exception as ex:
        log(f"WARN prune_synthetic/dedupe unavailable ({ex})")
        return stats

    snap = _configure_bwr(b, base_dir)
    try:
        state = load_state(base_dir)
        tranches = state.get("tranches") or []
        kept = [
            tr
            for tr in tranches
            if not b.is_synthetic_open_ord(tr.get("open_ord_id") or "")
        ]
        pruned_syn = len(tranches) - len(kept)
        legs = state.get("realized_legs") or []
        deduped = b.dedupe_realized_legs(legs)
        legs_deduped = len(deduped) != len(legs)
        stats["pruned_syn"] = pruned_syn
        stats["legs_deduped"] = legs_deduped

        if dry_run:
            if pruned_syn:
                log(f"DRY RUN prune_synthetic: would remove {pruned_syn}")
            if legs_deduped:
                log(f"DRY RUN dedupe: {len(legs)}→{len(deduped)}")
            return stats

        if not maintenance_write_allowed(dry_run, confirm, base_dir):
            return stats

        _backup_state(base_dir)
        b.set_bwr_write_mode(True)
        try:
            if pruned_syn > 0:
                state["tranches"] = kept
                from position_state import compute_net_position

                state["net_position"] = compute_net_position(kept)
                save_state(state, base_dir)
                stats["written"] = True
                log(f"APPLY prune_synthetic: removed {pruned_syn}")
            if legs_deduped:
                state = load_state(base_dir)
                state["realized_legs"] = deduped
                save_state(state, base_dir)
                stats["written"] = True
                log(f"APPLY dedupe: {len(legs)}→{len(deduped)}")
        finally:
            b.set_bwr_write_mode(False)
    finally:
        _restore_bwr(b, snap)
    return stats


def run_rebuild_trades(dry_run: bool, confirm: bool, base_dir: str) -> dict:
    stats = {"rebuild_rows": 0, "written": False}
    state_path = os.path.join(base_dir, "state.json")
    if not os.path.exists(state_path):
        return stats

    if dry_run:
        try:
            from position_state import load_state

            state = load_state(base_dir)
            n = len(state.get("realized_legs") or []) + len(state.get("tranches") or [])
            log(f"DRY RUN rebuild_trades: would project ~{n} source entries")
        except Exception as ex:
            log(f"DRY RUN rebuild_trades skipped ({ex})")
        return stats

    if not maintenance_write_allowed(dry_run, confirm, base_dir):
        return stats

    try:
        b = _import_bwr()
        snap = _configure_bwr(b, base_dir)
        b.set_bwr_write_mode(True)
        try:
            n = int(b.rebuild_trades_from_state() or 0)
            b.dedup_trades_csv()
            b.clean_ghost_rows()
            stats["rebuild_rows"] = n
            stats["written"] = True
            log(f"APPLY rebuild_trades: {n} rows")
        finally:
            b.set_bwr_write_mode(False)
            _restore_bwr(b, snap)
    except Exception as ex:
        log(f"WARN rebuild_trades: {ex}")
    return stats


def run_sync_equity(dry_run: bool, confirm: bool, base_dir: str) -> dict:
    stats = {"equity_updated": 0, "written": False}
    state_path = os.path.join(base_dir, "state.json")
    if not os.path.exists(state_path):
        return stats

    try:
        b = _import_bwr()
        from position_state import load_state
    except Exception as ex:
        log(f"WARN sync_equity unavailable ({ex})")
        return stats

    state = load_state(base_dir)
    missing = sum(
        1
        for leg in state.get("realized_legs") or []
        if leg.get("equity_after") in (None, "")
    )

    if dry_run:
        log(f"DRY RUN sync_equity: {missing} legs missing equity_after")
        return stats

    if not maintenance_write_allowed(dry_run, confirm, base_dir):
        return stats

    try:
        import csv

        snap = _configure_bwr(b, base_dir)
        b.set_bwr_write_mode(True)
        try:
            trades_path = os.path.join(base_dir, "trades.csv")
            closed = []
            if os.path.isfile(trades_path) and os.path.getsize(trades_path) > 0:
                with open(trades_path, encoding="utf-8") as fp:
                    closed = [
                        row
                        for row in csv.DictReader(fp)
                        if (row.get("状态") or "").strip() == "已平仓"
                    ]
            if not closed:
                log("sync_equity: no closed trades rows; skip")
                return stats
            replay_map, _ = b._replay_equity_after_close(closed)
            updated = int(b.sync_state_equity_after_from_replay(replay_map) or 0)
            stats["equity_updated"] = updated
            stats["written"] = updated > 0
            log(f"APPLY sync_equity: updated {updated} legs")
        finally:
            b.set_bwr_write_mode(False)
            _restore_bwr(b, snap)
    except Exception as ex:
        log(f"WARN sync_equity: {ex}")
    return stats


def run_maintenance(
    *,
    repair: bool,
    dry_run: bool,
    confirm: bool,
    base_dir: str,
    do_prune: bool,
    do_rebuild: bool,
    do_sync_equity: bool,
) -> dict:
    op_dry = dry_run or not repair
    summary = {
        "version": VERSION,
        "repair": repair,
        "dry_run": op_dry,
        "base_dir": base_dir,
        "prune_changed": 0,
        "prune_before": 0,
        "prune_after": 0,
        "pruned_syn": 0,
        "legs_deduped": False,
        "rebuild_rows": 0,
        "equity_updated": 0,
        "would_change": False,
        "state_changed": False,
        "written": False,
    }

    if do_prune:
        p1 = run_prune_inflated(op_dry, confirm, base_dir)
        p2 = run_prune_synthetic_dedupe(op_dry, confirm, base_dir)
        summary["prune_changed"] = p1.get("prune_changed", 0)
        summary["prune_before"] = p1.get("prune_before", 0)
        summary["prune_after"] = p1.get("prune_after", 0)
        summary["pruned_syn"] = p2.get("pruned_syn", 0)
        summary["legs_deduped"] = bool(p2.get("legs_deduped"))
        summary["written"] = summary["written"] or p1.get("written") or p2.get("written")

    if do_rebuild:
        rb = run_rebuild_trades(op_dry, confirm, base_dir)
        summary["rebuild_rows"] = rb.get("rebuild_rows", 0)
        summary["written"] = summary["written"] or rb.get("written")

    if do_sync_equity:
        eq = run_sync_equity(op_dry, confirm, base_dir)
        summary["equity_updated"] = eq.get("equity_updated", 0)
        summary["written"] = summary["written"] or eq.get("written")

    summary["would_change"] = (
        summary["prune_changed"] > 0
        or summary["pruned_syn"] > 0
        or summary["legs_deduped"]
        or summary["equity_updated"] > 0
    )
    summary["state_changed"] = bool(summary["written"])
    return summary


def main() -> int:
    args = parse_args()
    base_dir = resolve_base_dir(args)
    dry_run = effective_dry_run(args)
    repair = bool(args.repair)

    log(f"STATE_MAINTENANCE_WORKER {VERSION}")
    log(f"repair={repair} dry_run={dry_run} confirm={args.confirm} base_dir={base_dir}")
    if os.environ.get("HERMES_A2_FIXTURE") == "1":
        log("HERMES_A2_FIXTURE=1")
    if os.environ.get("HERMES_MAINTENANCE_APPLY") == "1":
        log("HERMES_MAINTENANCE_APPLY=1")

    do_prune = args.prune
    do_rebuild = args.rebuild_trades
    do_sync = args.sync_equity
    if not (do_prune or do_rebuild or do_sync):
        do_prune = do_rebuild = do_sync = True

    try:
        summary = run_maintenance(
            repair=repair,
            dry_run=dry_run,
            confirm=args.confirm,
            base_dir=base_dir,
            do_prune=do_prune,
            do_rebuild=do_rebuild,
            do_sync_equity=do_sync,
        )
    except Exception as ex:
        log(f"CRITICAL worker error: {ex}")
        emit_summary({"version": VERSION, "error": str(ex), "written": False})
        return 2

    if summary.get("would_change") and not repair:
        log("AUDIT_WOULD_CHANGE: maintenance needed but readonly (no --repair)")
    elif summary.get("would_change") and repair and dry_run:
        log("AUDIT_WOULD_CHANGE: dry-run only; use --confirm --no-dry-run to apply")

    if not repair:
        log("READONLY: reconcile/worker audit mode")

    emit_summary(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
