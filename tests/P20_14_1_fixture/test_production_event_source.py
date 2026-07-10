from core.production_event_source import (
    FakeProductionEventSource,
    ProductionEventSource,
)
def main():
    assert issubclass(
        FakeProductionEventSource,
        ProductionEventSource,
    )
    source = FakeProductionEventSource(
        [
            {
                "writer": "state_maintenance_worker.py",
                "action": "observe",
                "target": "state.json",
                "observe_only": True,
            }
        ]
    )
    events = source.read_events()
    assert len(events) == 1
    assert events[0]["writer"] == "state_maintenance_worker.py"
    assert events[0]["observe_only"] is True
    # second call returns independent copy
    events[0]["writer"] = "mutated"
    assert source.read_events()[0]["writer"] == (
        "state_maintenance_worker.py"
    )
    print(
        "P20_14_1_READONLY_PRODUCTION_EVENT_SOURCE_FIXTURE_PASS"
    )
if __name__ == "__main__":
    main()
