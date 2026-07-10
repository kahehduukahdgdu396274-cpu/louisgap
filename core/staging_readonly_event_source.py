"""
P20-14.2 Staging Readonly Event Source
Only provides readonly event access.
No mutation capability.
"""
class StagingReadonlyEventSource:
    def __init__(self, events=None):
        self._events = events or []
    def read_events(self):
        return list(self._events)
