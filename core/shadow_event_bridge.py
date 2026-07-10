"""
P20-13.2 Shadow Observer Event Bridge
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
    def collect(self):
        events = self.adapter.read_events()
        results = []
        for event in events:
            if self.hook:
                self.hook.observe(event)
            if self.pipeline:
                result = self.pipeline.record(
                    event
                )
                results.append(result)
        return results
