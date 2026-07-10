"""
P20-13 Shadow Observer Hook
Design placeholder only.
No production connection.
No write interception.
"""
class ShadowObserverHook:
    def __init__(self, collector=None):
        self.collector = collector
    def observe(self, event):
        if self.collector:
            return self.collector.observe(event)
        return {
            "status": "NO_COLLECTOR",
            "observe_only": True,
        }
