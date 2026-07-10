from datetime import datetime


class ShadowDailySnapshotGenerator:
    """
    P20-12.4
    Generate readonly shadow observation snapshots.
    """
    def generate(self, events):
        writers = {}
        for event in events:
            writer = event.get("writer", "UNKNOWN")
            if writer not in writers:
                writers[writer] = {
                    "count": 0,
                    "observe_only": True,
                }
            writers[writer]["count"] += 1
        return {
            "generated_at": datetime.utcnow().isoformat(),
            "mode": "shadow",
            "observe_only": True,
            "writers": writers,
            "total_events": len(events),
        }


class ShadowDailySnapshot:
    """
    P20-13.4 Shadow Daily Snapshot
    Readonly snapshot generator.
    No production mutation.
    """
    def __init__(self, events=None):
        self.events = events or []

    def generate(self):
        writers = {}
        for event in self.events:
            writer = event.get(
                "writer",
                "UNKNOWN"
            )
            writers[writer] = (
                writers.get(writer, 0) + 1
            )
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "event_count": len(self.events),
            "writers": writers,
            "observe_only": True,
        }
