from datetime import datetime
class ShadowCollectorFixture:
    def collect(self, writer, action, target):
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "writer": writer,
            "action": action,
            "target": target,
            "mode": "shadow",
            "observe_only": True,
        }
def main():
    collector = ShadowCollectorFixture()
    event = collector.collect(
        writer="state_maintenance_worker.py",
        action="observe_write",
        target="state.json",
    )
    assert event["writer"] == "state_maintenance_worker.py"
    assert event["mode"] == "shadow"
    assert event["observe_only"] is True
    forbidden = [
        "apply",
        "repair",
        "block",
    ]
    assert event["action"] not in forbidden
    print(
        "P20_12_2_SHADOW_OBSERVATION_COLLECTOR_CONTRACT_PASS"
    )
if __name__ == "__main__":
    main()
