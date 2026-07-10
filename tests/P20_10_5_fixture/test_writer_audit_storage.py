from pathlib import Path
import tempfile

from core.writer_audit_storage import WriterAuditStorage


def main():
    with tempfile.TemporaryDirectory() as d:
        storage = WriterAuditStorage(
            Path(d) / "writer_events.jsonl"
        )
        event = {
            "timestamp": "2026-07-10T00:00:00",
            "writer": "state_maintenance_worker.py",
            "level": "L1",
            "owner": "maintenance",
            "permission": "ALLOW_MAINTENANCE",
            "action": "write_attempt",
            "target": "state.json",
            "observe_only": True,
        }
        storage.append_event(event)
        events = storage.read_events()
        assert len(events) == 1
        assert events[0]["writer"] == "state_maintenance_worker.py"
        checksum = storage.checksum()
        assert checksum is not None
        snapshot = storage.snapshot()
        assert snapshot["exists"] is True
        print("P20_10_5_WRITER_AUDIT_STORAGE_FIXTURE_PASS")


if __name__ == "__main__":
    main()
