from core.writer_audit_adapter import WriterAuditAdapter
from core.writer_audit_schema import validate_event


def main():
    adapter = WriterAuditAdapter()
    event = adapter.audit_event(
        "state_maintenance_worker.py",
        "write_attempt",
        "state.json",
    )
    ok, errors = validate_event(event)
    assert ok, errors
    assert event["level"] == "L1"
    assert event["owner"] == "maintenance"
    assert event["permission"] == "ALLOW_MAINTENANCE"
    assert event["observe_only"] is True
    unknown = adapter.audit_event(
        "unknown_writer.py",
        "write_attempt",
    )
    ok, errors = validate_event(unknown)
    assert ok, errors
    assert unknown["level"] == "UNKNOWN"
    assert unknown["permission"] == "BLOCK"
    print("P20_10_4_WRITER_EVENT_SCHEMA_FIXTURE_PASS")


if __name__ == "__main__":
    main()
