"""
P20-14.1 Readonly Production Event Source Interface
Design only.
No VPS connection.
No state.json / bot runtime access.
No write / intercept.
"""
import copy


class ProductionEventSource:
    """Abstract readonly event source."""

    def read_events(self):
        raise NotImplementedError


class FakeProductionEventSource(ProductionEventSource):
    """Fixture-only source. Never connects to production."""

    def __init__(self, events=None):
        self._events = list(events or [])

    def read_events(self):
        return copy.deepcopy(self._events)
