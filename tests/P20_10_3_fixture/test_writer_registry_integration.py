from core.writer_audit_adapter import WriterAuditAdapter


def main():
    adapter = WriterAuditAdapter()
    event = adapter.audit_event(
        "state_maintenance_worker.py",
        "write_attempt",
        "state.json",
    )
    assert event["observe_only"] is True
    assert event["registry"]["level"] == "L1"
    assert event["registry"]["permission"] == "ALLOW_MAINTENANCE"
    event2 = adapter.audit_event(
        "govern_state_legs.py",
        "write_attempt",
    )
    assert event2["registry"]["level"] == "L4"
    assert event2["registry"]["permission"] == "BLOCK"
    print("P20_10_3_WRITER_REGISTRY_INTEGRATION_PASS")


if __name__ == "__main__":
    main()
