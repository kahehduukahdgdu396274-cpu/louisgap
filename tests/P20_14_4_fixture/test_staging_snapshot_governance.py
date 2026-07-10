from core.staging_shadow_snapshot import (
    StagingShadowSnapshot,
)
from core.staging_shadow_governance import (
    StagingShadowGovernance,
)
def main():
    events = [
        {
            "writer":
            "state_maintenance_worker.py",
            "observe_only":
            True,
        },
        {
            "writer":
            "unknown_writer.py",
            "observe_only":
            True,
        },
    ]
    snapshot = (
        StagingShadowSnapshot(events)
        .generate()
    )
    report = (
        StagingShadowGovernance()
        .generate(snapshot)
    )
    assert snapshot["event_count"] == 2
    assert report["status"] == (
        "STAGING_READONLY"
    )
    assert report["observe_only"] is True
    print(
        "P20_14_4_STAGING_SHADOW_SNAPSHOT_GOVERNANCE_FIXTURE_PASS"
    )
if __name__ == "__main__":
    main()
