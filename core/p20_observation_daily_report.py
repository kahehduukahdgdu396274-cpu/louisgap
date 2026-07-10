"""
P20-14 Observation Assistant — Daily Report Generator

Readonly report generation only.
- Does not modify production files
- Does not write audit/writer_events.jsonl
- Does not call workers
- Does not change cron / bot / main.py
"""
from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = REPO_ROOT / "docs" / "P20" / "reports" / "P20_14_DAILY"


def _git_readonly(args: list[str], cwd: Path) -> str:
    try:
        out = subprocess.check_output(
            ["git", *args],
            cwd=str(cwd),
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return "UNKNOWN"


def collect_git_safety(repo_root: Optional[Path] = None) -> Dict[str, str]:
    root = repo_root or REPO_ROOT
    branch = _git_readonly(["branch", "--show-current"], root)
    status = _git_readonly(["status", "--porcelain"], root)
    working_tree = "clean" if not status else "dirty"
    return {
        "branch": branch or "UNKNOWN",
        "working_tree": working_tree,
        "status_detail": status or "(clean)",
    }


def build_report_payload(
    *,
    date_str: Optional[str] = None,
    shadow: Optional[Dict[str, Any]] = None,
    snapshot: Optional[Dict[str, Any]] = None,
    governance: Optional[Dict[str, Any]] = None,
    runtime: Optional[Dict[str, Any]] = None,
    git_info: Optional[Dict[str, str]] = None,
    decision: str = "CONTINUE_OBSERVATION",
) -> Dict[str, Any]:
    shadow = shadow or {}
    snapshot = snapshot or {}
    governance = governance or {}
    runtime = runtime or {}
    git_info = git_info or collect_git_safety()

    writers = shadow.get("writers") or snapshot.get("writers") or {}
    known = [
        w for w in writers
        if not str(w).startswith("unknown")
    ]
    unknown = [
        w for w in writers
        if str(w).startswith("unknown")
    ]
    blocks = int(shadow.get("permission_blocks", 0))
    if blocks == 0 and unknown:
        blocks = sum(int(writers.get(w, 0) or 0) for w in unknown)

    return {
        "date": date_str or datetime.now(timezone.utc).strftime("%Y%m%d"),
        "runtime_status": runtime.get("status", "STAGING_READONLY"),
        "runtime_errors": runtime.get("errors", "none"),
        "events": int(
            shadow.get("events")
            or snapshot.get("event_count")
            or 0
        ),
        "known_writers": known,
        "unknown_writers": unknown,
        "permission_blocks": blocks,
        "pipeline": governance.get("pipeline", snapshot.get("pipeline", "PASS")),
        "snapshot_status": snapshot.get("status", governance.get("status", "PASS")),
        "branch": git_info.get("branch", "UNKNOWN"),
        "working_tree": git_info.get("working_tree", "UNKNOWN"),
        "decision": decision,
        "observe_only": True,
    }


def render_markdown(payload: Dict[str, Any]) -> str:
    known = ", ".join(payload["known_writers"]) or "(none)"
    unknown = ", ".join(payload["unknown_writers"]) or "(none)"
    return "\n".join(
        [
            "# P20-14 Daily Observation Report",
            f"Date: {payload['date']}",
            "",
            "## Runtime",
            f"- Status: {payload['runtime_status']}",
            f"- Errors: {payload['runtime_errors']}",
            "",
            "## Shadow Observer",
            f"- Events: {payload['events']}",
            f"- Known Writers: {known}",
            f"- Unknown Writers: {unknown}",
            f"- Permission Blocks: {payload['permission_blocks']}",
            "",
            "## Governance",
            f"- Pipeline: {payload['pipeline']}",
            f"- Snapshot: {payload['snapshot_status']}",
            "",
            "## Git Safety",
            f"- Branch: {payload['branch']}",
            f"- Working tree: {payload['working_tree']}",
            "",
            "## Decision",
            payload["decision"],
            "",
        ]
    )


def generate_daily_report(
    *,
    out_dir: Optional[Path] = None,
    date_str: Optional[str] = None,
    shadow: Optional[Dict[str, Any]] = None,
    snapshot: Optional[Dict[str, Any]] = None,
    governance: Optional[Dict[str, Any]] = None,
    runtime: Optional[Dict[str, Any]] = None,
    git_info: Optional[Dict[str, str]] = None,
    decision: str = "CONTINUE_OBSERVATION",
) -> Path:
    """Write P20_14_DAILY_YYYYMMDD.md under docs/P20/reports/P20_14_DAILY/."""
    payload = build_report_payload(
        date_str=date_str,
        shadow=shadow,
        snapshot=snapshot,
        governance=governance,
        runtime=runtime,
        git_info=git_info,
        decision=decision,
    )
    target_dir = Path(out_dir) if out_dir else DEFAULT_OUT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"P20_14_DAILY_{payload['date']}.md"
    path.write_text(render_markdown(payload), encoding="utf-8")
    return path


def main() -> None:
    path = generate_daily_report()
    print(f"P20_14_DAILY_REPORT_WRITTEN:{path}")


if __name__ == "__main__":
    main()
