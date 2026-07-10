"""
P20-13.2 / P20-13.3 Shadow Observer Event Bridge
Readonly event forwarding layer.
Adapter
    ->
Shadow Hook
    ->
Audit Pipeline
No write interception.
"""
class ShadowEventBridge:
    def __init__(
        self,
        adapter=None,
        hook=None,
        pipeline=None,
    ):
        self.adapter = adapter
        self.hook = hook
        self.pipeline = pipeline

    def _record(self, event):
        """Support FakePipeline.record(event) and WriterAuditPipeline.record(writer, action, target)."""
        try:
            return self.pipeline.record(
                event.get("writer"),
                event.get("action"),
                event.get("target"),
            )
        except TypeError:
            return self.pipeline.record(event)

    def collect(self):
        events = self.adapter.read_events()
        results = []
        for event in events:
            if self.hook:
                self.hook.observe(event)
            if self.pipeline:
                results.append(self._record(event))
        return results
