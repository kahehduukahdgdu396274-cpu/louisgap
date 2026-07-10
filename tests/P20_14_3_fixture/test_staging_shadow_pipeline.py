import tempfile
from core.staging_readonly_event_source import (
    StagingReadonlyEventSource,
)
from core.staging_shadow_pipeline import (
    StagingShadowPipeline,
)
def main():
    with tempfile.NamedTemporaryFile() as f:
        source = StagingReadonlyEventSource(
            [
                {
                    "writer":
                    "state_maintenance_worker.py",
                    "action":
                    "observe",
                    "target":
                    "maintenance",
                },
                {
                    "writer":
                    "unknown_writer.py",
                    "action":
                    "observe",
                    "target":
                    "unknown",
                },
            ]
        )
        pipeline = StagingShadowPipeline(
            source,
            f.name,
        )
        result = pipeline.collect()
        assert len(result) == 2
        assert result[0]["observe_only"] is True
        assert result[1]["permission"] == "BLOCK"
    print(
        "P20_14_3_STAGING_SHADOW_PIPELINE_WIRING_FIXTURE_PASS"
    )
if __name__ == "__main__":
    main()
