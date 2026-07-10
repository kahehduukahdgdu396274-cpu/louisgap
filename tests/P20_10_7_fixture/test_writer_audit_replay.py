from core.writer_audit_replay import WriterAuditReplay


def main():
    replay = WriterAuditReplay()
    events = [
        {
            "timestamp": "2026-07-10T00:00:00",
            "writer": "state_maintenance_worker.py",
            "level": "L1",
            "owner": "maintenance",
            "permission": "ALLOW_MAINTENANCE",
            "action": "write_attempt",
            "target": "state.json",
            "observe_only": True,
        },
        {
            "timestamp": "2026-07-10T00:00:01",
            "writer": "unknown_writer.py",
            "level": "UNKNOWN",
            "owner": "unknown",
            "permission": "BLOCK",
            "action": "write_attempt",
            "target": "state.json",
            "observe_only": True,
        },
    ]
    result = replay.replay(events)
    assert result[0]["schema"] == "PASS"
    assert result[0]["ownership"] == "PASS"
    assert result[0]["level"] == "L1"
    assert result[1]["schema"] == "PASS"
    assert result[1]["permission"] == "BLOCK"
    print("P20_10_7_WRITER_AUDIT_REPLAY_FIXTURE_PASS")


if __name__ == "__main__":
    main()
