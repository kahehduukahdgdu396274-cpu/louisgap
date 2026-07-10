"""
P20-14.4 Staging Shadow Snapshot
Readonly staging aggregation only.
"""
class StagingShadowSnapshot:
    def __init__(self, events):
        self.events = list(events)
    def generate(self):
        writers = {}
        for event in self.events:
            writer = event.get(
                "writer",
                "UNKNOWN",
            )
            writers[writer] = (
                writers.get(writer, 0) + 1
            )
        return {
            "event_count": len(self.events),
            "writers": writers,
            "observe_only": True,
        }
