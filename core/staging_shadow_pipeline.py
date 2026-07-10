"""
P20-14.3 Staging Shadow Pipeline Wiring
Readonly staging integration only.
"""
from core.writer_audit_pipeline import WriterAuditPipeline
class StagingShadowPipeline:
    def __init__(
        self,
        source,
        storage_path,
    ):
        self.source = source
        self.pipeline = WriterAuditPipeline(
            storage_path=storage_path
        )
    def collect(self):
        results = []
        events = self.source.read_events()
        for event in events:
            result = self.pipeline.record(
                writer=event["writer"],
                action=event.get(
                    "action",
                    "observe",
                ),
                target=event.get(
                    "target",
                    "unknown",
                ),
            )
            results.append(result)
        return results
