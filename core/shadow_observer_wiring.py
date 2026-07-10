"""
P20-14.2 Shadow Observer Wiring
Readonly bridge only.
"""
class ShadowObserverWiring:
    def __init__(
        self,
        source,
        observer,
    ):
        self.source = source
        self.observer = observer
    def collect(self):
        events = self.source.read_events()
        results = []
        for event in events:
            results.append(
                self.observer.observe(event)
            )
        return results
