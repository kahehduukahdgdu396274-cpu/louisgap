from core.writer_shadow_collector import WriterShadowCollector
class FakePipeline:
    def record(self, event):
        return {
            **event,
            "observe_only": True
        }
def run():
    collector = WriterShadowCollector(FakePipeline())
    known = collector.observe({
        "writer": "state_maintenance_worker.py",
        "action": "write_state",
        "target": "state.json"
    })
    unknown = collector.observe({
        "writer": "unknown_writer.py",
        "action": "write_state",
        "target": "state.json"
    })
    report = collector.report()
    assert known["observe_only"] is True
    assert unknown["observe_only"] is True
    assert report["event_count"] == 2
    print("P20_11_1_SHADOW_COLLECTOR_FIXTURE_PASS")
if __name__ == "__main__":
    run()
