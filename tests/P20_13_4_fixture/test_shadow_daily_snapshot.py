from core.shadow_daily_snapshot import (
    ShadowDailySnapshot,
)
def main():
    snapshot = ShadowDailySnapshot(
        [
            {
                "writer": "state_maintenance_worker.py",
                "action": "observe",
            },
            {
                "writer": "state_maintenance_worker.py",
                "action": "observe",
            },
            {
                "writer": "unknown_writer.py",
                "action": "observe",
            },
        ]
    )
    result = snapshot.generate()
    assert result["observe_only"] is True
    assert result["event_count"] == 3
    assert (
        result["writers"]
        ["state_maintenance_worker.py"]
        == 2
    )
    print(
        "P20_13_4_SHADOW_DAILY_SNAPSHOT_FIXTURE_PASS"
    )
if __name__ == "__main__":
    main()
