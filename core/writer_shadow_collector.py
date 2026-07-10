from __future__ import annotations
from typing import Dict, Any, List
from core.writer_audit_pipeline import WriterAuditPipeline
class WriterShadowCollector:
    """
    P20-11 Shadow Observe Collector
    observe-only:
    - no blocking
    - no runtime mutation
    - no writer interception
    """
    def __init__(self, pipeline: WriterAuditPipeline):
        self.pipeline = pipeline
        self.events: List[Dict[str, Any]] = []
    def observe(
        self,
        event: Dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        payload = dict(kwargs) if kwargs else dict(event or {})
        if not payload:
            raise ValueError("observe requires event dict or kwargs")
        try:
            result = self.pipeline.record(
                payload["writer"],
                payload.get("action"),
                payload.get("target"),
            )
        except TypeError:
            result = self.pipeline.record(payload)
        self.events.append(result)
        return result
    def report(self) -> Dict[str, Any]:
        return {
            "event_count": len(self.events),
            "observe_only": True,
            "events": self.events,
        }
