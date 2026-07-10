from core.shadow_daily_snapshot import ShadowDailySnapshotGenerator
def main():
    generator = ShadowDailySnapshotGenerator()
    snapshot = generator.generate([
        {
            "writer": "state_maintenance_worker.py",
            "observe_only": True,
        },
        {
            "writer": "state_maintenance_worker.py",
            "observe_only": True,
        },
        {
            "writer": "unknown_shadow_writer.py",
            "observe_only": True,
        },
    ])
    assert snapshot["mode"] == "shadow"
    assert snapshot["observe_only"] is True
    assert snapshot["total_events"] == 3
    assert (
        snapshot["writers"]
        ["state_maintenance_worker.py"]
        ["count"]
        == 2
    )
    print(
        "P20_12_4_SHADOW_DAILY_SNAPSHOT_FIXTURE_PASS"
    )
if __name__ == "__main__":
    main()
