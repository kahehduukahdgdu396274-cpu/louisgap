"""
P20-13.1 Shadow Readonly Adapter
Readonly abstraction layer.
No production connection.
No write operation.
No interception.
"""
class ShadowReadonlyAdapter:
    def __init__(self, source=None):
        self.source = source
    def read_events(self):
        if self.source is None:
            return []
        return list(self.source.read_events())
class FakeReadonlySource:
    def __init__(self, events=None):
        self.events = events or []
    def read_events(self):
        return self.events
