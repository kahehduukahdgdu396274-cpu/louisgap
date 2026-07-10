"""
P20-14 Observation Daily Merge Check

Readonly validation that daily evidence exists and is schema-safe.
- Does not modify runtime / bot / cron
- Does not write audit/writer_events.jsonl
- Does not auto git-merge
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIT_DIR = REPO_ROOT / "audit" / "observation"
DEFAULT_DAILY_DIR = REPO_ROOT / "docs" / "P20" / "reports" / "P20_14_DAILY"

REQUIRED_FIELDS = [
    "timestamp",
    "runtime_status",
    "bot_status",
    "shadow_events",
    "known_writers",
    "unknown_writers",
    "permission_blocks",
    "pipeline_status",
    "safety_check",
]


def evidence_paths(
    date_str: str,
    *,
    audit_dir: Optional[Path] = None,
    daily_dir: Optional[Path] = None,
) -> Tuple[Path, Path]:
    audit = Path(audit_dir) if audit_dir else DEFAULT_AUDIT_DIR
    daily = Path(daily_dir) if daily_dir else DEFAULT_DAILY_DIR
    json_path = audit / f"daily_observation_{date_str}.json"
    md_path = daily / f"P20_14_RUNTIME_EVIDENCE_{date_str}.md"
    return json_path, md_path


def check_evidence_present(json_path: Path, md_path: Path) -> Tuple[str, List[str]]:
    errors: List[str] = []
    if not json_path.exists():
        errors.append(f"missing json: {json_path}")
    if not md_path.exists():
        errors.append(f"missing md: {md_path}")
    return ("PASS" if not errors else "FAIL"), errors


def check_schema(data: Any) -> Tuple[str, List[str]]:
    errors: List[str] = []
    if not isinstance(data, dict):
        return "FAIL", ["json root must be object"]
    for key in REQUIRED_FIELDS:
        if key not in data:
            errors.append(f"missing field: {key}")
    return ("PASS" if not errors else "FAIL"), errors


def check_safety(data: Dict[str, Any]) -> Tuple[str, List[str]]:
    errors: List[str] = []
    safety = data.get("safety_check")
    if not isinstance(safety, dict):
        return "FAIL", ["safety_check must be object"]
    if safety.get("readonly") is not True:
        errors.append("safety_check.readonly must be true")
    return ("PASS" if not errors else "FAIL"), errors


def run_daily_check(
    *,
    date_str: Optional[str] = None,
    audit_dir: Optional[Path] = None,
    daily_dir: Optional[Path] = None,
    out_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    day = date_str or datetime.now(timezone.utc).strftime("%Y%m%d")
    json_path, md_path = evidence_paths(
        day, audit_dir=audit_dir, daily_dir=daily_dir
    )

    evidence_status, evidence_errors = check_evidence_present(json_path, md_path)
    schema_status, schema_errors = "FAIL", ["json not loaded"]
    safety_status, safety_errors = "FAIL", ["json not loaded"]
    data: Optional[Dict[str, Any]] = None

    if json_path.exists():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            schema_status, schema_errors = check_schema(data)
            if schema_status == "PASS":
                safety_status, safety_errors = check_safety(data)
            else:
                safety_status, safety_errors = "FAIL", ["schema failed"]
        except json.JSONDecodeError as exc:
            schema_status = "FAIL"
            schema_errors = [f"invalid json: {exc}"]
            safety_status, safety_errors = "FAIL", ["invalid json"]

    overall = (
        "PASS"
        if evidence_status == schema_status == safety_status == "PASS"
        else "FAIL"
    )
    result = {
        "date": day,
        "evidence": evidence_status,
        "schema": schema_status,
        "safety": safety_status,
        "overall": overall,
        "decision": "CONTINUE_OBSERVATION",
        "errors": {
            "evidence": evidence_errors,
            "schema": schema_errors,
            "safety": safety_errors,
        },
        "json_path": str(json_path),
        "md_path": str(md_path),
        "observe_only": True,
    }

    target_dir = Path(out_dir) if out_dir else (
        Path(daily_dir) if daily_dir else DEFAULT_DAILY_DIR
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    out_path = target_dir / f"P20_14_DAILY_CHECK_{day}.md"
    out_path.write_text(render_check_markdown(result), encoding="utf-8")
    result["report_path"] = str(out_path)
    return result


def render_check_markdown(result: Dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Daily Check",
            f"Date: {result['date']}",
            "",
            "Evidence:",
            result["evidence"],
            "",
            "Schema:",
            result["schema"],
            "",
            "Safety:",
            result["safety"],
            "",
            "Decision:",
            result["decision"],
            "",
        ]
    )


def main() -> None:
    result = run_daily_check()
    print(
        "P20_14_DAILY_CHECK:"
        f"{result['overall']} "
        f"evidence={result['evidence']} "
        f"schema={result['schema']} "
        f"safety={result['safety']}"
    )
    print(f"REPORT:{result['report_path']}")


if __name__ == "__main__":
    main()
