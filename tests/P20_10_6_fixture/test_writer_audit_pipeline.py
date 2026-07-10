from pathlib import Path
import tempfile

from core.writer_audit_pipeline import WriterAuditPipeline


def main():
    with tempfile.TemporaryDirectory() as d:
        pipeline = WriterAuditPipeline(
            Path(d) / "writer_events.jsonl"
        )
        event = pipeline.record(
            "state_maintenance_worker.py",
            "write_attempt",
            "state.json",
        )
        assert event["level"] == "L1"
        assert event["permission"] == "ALLOW_MAINTENANCE"
        assert event["observe_only"] is True
        events = pipeline.storage.read_events()
        assert len(events) == 1
        assert events[0]["writer"] == "state_maintenance_worker.py"
        checksum = pipeline.storage.checksum()
        assert checksum is not None
        print("P20_10_6_WRITER_AUDIT_PIPELINE_FIXTURE_PASS")


if __name__ == "__main__":
    main()
