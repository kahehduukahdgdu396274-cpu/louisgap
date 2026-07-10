from collections import Counter
class WriterShadowReportGenerator:
    def generate(self, events):
        writer_count = Counter()
        level_count = Counter()
        permission_count = Counter()
        for event in events:
            writer_count[event.get("writer", "UNKNOWN")] += 1
            level_count[event.get("level", "UNKNOWN")] += 1
            permission_count[event.get("permission", "UNKNOWN")] += 1
        return {
            "total_events": len(events),
            "writers": dict(writer_count),
            "levels": dict(level_count),
            "permissions": dict(permission_count),
            "observe_only": True,
        }
