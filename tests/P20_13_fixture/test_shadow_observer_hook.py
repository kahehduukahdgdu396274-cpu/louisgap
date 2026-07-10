from core.shadow_observer_hook import ShadowObserverHook
class FakeCollector:
    def __init__(self):
        self.events = []
    def observe(self, event):
        self.events.append(event)
        return {
            "observe_only": True
        }
def main():
    collector = FakeCollector()
    hook = ShadowObserverHook(
        collector=collector
    )
    result = hook.observe(
        {
            "writer": "shadow_writer"
        }
    )
    assert result["observe_only"] is True
    assert len(collector.events) == 1
    print(
        "P20_13_SHADOW_OBSERVER_HOOK_FIXTURE_PASS"
    )
if __name__ == "__main__":
    main()
