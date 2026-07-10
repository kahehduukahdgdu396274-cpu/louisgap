"""
P20-10.1 Writer Audit Adapter
Only observe.
No write interception.
No runtime behavior change.
"""
from core.writer_audit import writer_audit_event

WRITER_LEVELS = {
    "main.py": "L0_RUNTIME",
    "position_state.py": "L0_RUNTIME",
    "state_maintenance_worker.py": "L1_MAINTENANCE",
    "reconcile_all_from_okx.py": "L2_READONLY",
    "build_war_report.py": "L3_REPORT",
}


def resolve_writer_level(writer):
    return WRITER_LEVELS.get(writer, "UNKNOWN")


def audit_writer_action(
    writer,
    target,
    mode,
    sha_before=None,
    sha_after=None,
):
    level = resolve_writer_level(writer)
    event = writer_audit_event(
        writer=writer,
        target=target,
        mode=mode,
        sha_before=sha_before,
        sha_after=sha_after,
    )
    event["writer_level"] = level
    return event
