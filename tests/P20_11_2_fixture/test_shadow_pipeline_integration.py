import tempfile
from pathlib import Path

from core.writer_shadow_collector import WriterShadowCollector
from core.writer_audit_pipeline import WriterAuditPipeline


def main():
    with tempfile.TemporaryDirectory() as td:
        storage_path = Path(td) / "writer_events.jsonl"
        pipeline = WriterAuditPipeline(
            storage_path=str(storage_path)
        )
        collector = WriterShadowCollector(
            pipeline=pipeline
        )

        event1 = collector.observe(
            writer="state_maintenance_worker.py",
            action="write_state",
            target="state.json",
        )
        assert event1["observe_only"] is True
        assert event1["writer"] == "state_maintenance_worker.py"
        assert event1["level"] == "L1"

        event2 = collector.observe(
            writer="unknown_shadow_writer.py",
            action="write_state",
            target="unknown.json",
        )
        assert event2["observe_only"] is True
        assert event2["level"] == "UNKNOWN"
        assert event2["permission"] == "BLOCK"

        events = pipeline.storage.read_events()
        assert len(events) == 2

        print(
            "P20_11_2_SHADOW_PIPELINE_INTEGRATION_FIXTURE_PASS"
        )


if __name__ == "__main__":
    main()
