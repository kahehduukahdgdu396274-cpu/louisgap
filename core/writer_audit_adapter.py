from datetime import datetime

from core.writer_registry import WriterRegistry


class WriterAuditAdapter:
    def __init__(self, registry_path="config/writer_registry.json"):
        self.registry = WriterRegistry(registry_path)

    def audit_event(self, writer, action, target=None):
        info = self.registry.get_writer(writer)
        return {
            "time": datetime.utcnow().isoformat(),
            "writer": writer,
            "action": action,
            "target": target,
            "registry": info,
            "observe_only": True,
        }
