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
