"""
P20 Write Gate
Purpose:
Central permission layer for runtime state writers.
This module is NOT connected to production runtime yet.
P20-4.1 only implements isolated gate logic.
"""
import os
import json
import hashlib
from pathlib import Path
from datetime import datetime
DEFAULT_POLICY = {
    "runtime_writers": [
        "main.py",
        "position_state.py"
    ],
    "maintenance_writers": [
        "state_maintenance_worker.py"
    ],
    "readonly_components": [
        "reconcile_all_from_okx.py",
        "build_war_report.py"
    ]
}
class WriteGateError(Exception):
    pass
def load_policy(policy_path=None):
    if policy_path:
        path = Path(policy_path)
        if path.exists():
            return json.loads(path.read_text())
    return DEFAULT_POLICY
def writer_hash(writer):
    return hashlib.sha256(
        writer.encode()
    ).hexdigest()[:16]
def check_writer(writer, mode="runtime", policy=None):
    policy = policy or DEFAULT_POLICY
    if writer in policy.get("runtime_writers", []):
        return {
            "allowed": True,
            "level": "L0_RUNTIME",
            "writer": writer
        }
    if writer in policy.get("maintenance_writers", []):
        if mode == "maintenance":
            return {
                "allowed": True,
                "level": "L1_MAINTENANCE",
                "writer": writer
            }
        return {
            "allowed": False,
            "reason": "maintenance writer requires maintenance mode",
            "writer": writer
        }
    if writer in policy.get("readonly_components", []):
        return {
            "allowed": False,
            "reason": "readonly component",
            "writer": writer
        }
    return {
        "allowed": False,
        "reason": "unknown writer blocked",
        "writer": writer
    }
def audit_event(writer, action, result):
    return {
        "time": datetime.utcnow().isoformat(),
        "writer": writer,
        "writer_hash": writer_hash(writer),
        "action": action,
        "result": result
    }
def assert_write_allowed(writer, mode="runtime"):
    result = check_writer(writer, mode)
    if not result["allowed"]:
        raise WriteGateError(
            json.dumps(result, ensure_ascii=False)
        )
    return result
