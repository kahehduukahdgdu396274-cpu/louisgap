from core.shadow_readonly_adapter import (
    ShadowReadonlyAdapter,
    FakeReadonlySource,
)
def main():
    source = FakeReadonlySource(
        [
            {
                "writer": "state_maintenance_worker",
                "action": "observe",
            }
        ]
    )
    adapter = ShadowReadonlyAdapter(
        source=source
    )
    events = adapter.read_events()
    assert len(events) == 1
    assert events[0]["writer"] == "state_maintenance_worker"
    print(
        "P20_13_1_SHADOW_READONLY_ADAPTER_FIXTURE_PASS"
    )
if __name__ == "__main__":
    main()
