import tempfile
from pathlib import Path
from core.shadow_event_bridge import ShadowEventBridge
from core.shadow_readonly_adapter import (
    ShadowReadonlyAdapter,
    FakeReadonlySource,
)
from core.writer_audit_pipeline import WriterAuditPipeline
def main():
    with tempfile.TemporaryDirectory() as tmp:
        storage_path = Path(tmp) / "writer_events.jsonl"
        pipeline = WriterAuditPipeline(
            storage_path=str(storage_path)
        )
        source = FakeReadonlySource(
            [
                {
                    "writer": "state_maintenance_worker.py",
                    "action": "observe",
                    "target": "state.json",
                }
            ]
        )
        adapter = ShadowReadonlyAdapter(
            source=source
        )
        bridge = ShadowEventBridge(
            adapter=adapter,
            pipeline=pipeline,
        )
        results = bridge.collect()
        assert len(results) == 1
        assert results[0]["observe_only"] is True
        assert results[0]["writer"] == "state_maintenance_worker.py"
        assert storage_path.exists()
        content = storage_path.read_text()
        assert "state_maintenance_worker.py" in content
        print(
            "P20_13_3_SHADOW_PIPELINE_INTEGRATION_FIXTURE_PASS"
        )
if __name__ == "__main__":
    main()
