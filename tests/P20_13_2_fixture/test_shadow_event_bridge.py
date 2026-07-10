from core.shadow_event_bridge import (
    ShadowEventBridge,
)
class FakeAdapter:
    def read_events(self):
        return [
            {
                "writer": "state_maintenance_worker",
                "action": "observe",
                "target": "state.json",
            }
        ]
class FakeHook:
    def __init__(self):
        self.events = []
    def observe(self, event):
        self.events.append(event)
class FakePipeline:
    def __init__(self):
        self.events = []
    def record(self, event):
        self.events.append(event)
        return {
            "observe_only": True,
            "writer": event["writer"],
        }
def main():
    hook = FakeHook()
    pipeline = FakePipeline()
    bridge = ShadowEventBridge(
        adapter=FakeAdapter(),
        hook=hook,
        pipeline=pipeline,
    )
    result = bridge.collect()
    assert len(result) == 1
    assert result[0]["observe_only"] is True
    assert len(hook.events) == 1
    assert len(pipeline.events) == 1
    print(
        "P20_13_2_SHADOW_EVENT_BRIDGE_FIXTURE_PASS"
    )
if __name__ == "__main__":
    main()
