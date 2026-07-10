from core.staging_readonly_event_source import (
    StagingReadonlyEventSource,
)
from core.shadow_observer_wiring import (
    ShadowObserverWiring,
)
class FakeObserver:
    def __init__(self):
        self.events = []
    def observe(self, event):
        self.events.append(event)
        return {
            "writer": event["writer"],
            "observe_only": True,
        }
def main():
    source = StagingReadonlyEventSource(
        [
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
    observer = FakeObserver()
    wiring = ShadowObserverWiring(
        source,
        observer,
    )
    result = wiring.collect()
    assert len(result) == 2
    assert result[0]["observe_only"] is True
    assert len(observer.events) == 2
    print(
        "P20_14_2_STAGING_READONLY_WIRING_FIXTURE_PASS"
    )
if __name__ == "__main__":
    main()
