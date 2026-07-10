import tempfile
from pathlib import Path
from core.shadow_observation_storage import ShadowObservationStorage
def main():
    with tempfile.TemporaryDirectory() as tmp:
        storage = ShadowObservationStorage(
            Path(tmp) / "shadow_events.jsonl"
        )
        storage.append({
            "writer": "state_maintenance_worker.py",
            "mode": "shadow",
            "observe_only": True,
        })
        events = storage.snapshot()
        assert len(events) == 1
        assert events[0]["writer"] == "state_maintenance_worker.py"
        assert events[0]["observe_only"] is True
    print(
        "P20_12_3_SHADOW_OBSERVATION_STORAGE_FIXTURE_PASS"
    )
if __name__ == "__main__":
    main()
