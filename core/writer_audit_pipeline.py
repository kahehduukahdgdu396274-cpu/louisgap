from core.writer_audit_adapter import WriterAuditAdapter
from core.writer_audit_schema import validate_event
from core.writer_audit_storage import WriterAuditStorage


class WriterAuditPipeline:
    def __init__(
        self,
        storage_path="audit/writer_events.jsonl",
    ):
        self.adapter = WriterAuditAdapter()
        self.storage = WriterAuditStorage(
            storage_path
        )

    def record(
        self,
        writer,
        action,
        target=None,
    ):
        event = self.adapter.audit_event(
            writer,
            action,
            target,
        )
        valid, errors = validate_event(
            event
        )
        if not valid:
            raise ValueError(
                f"invalid audit event: {errors}"
            )
        self.storage.append_event(
            event
        )
        return event
