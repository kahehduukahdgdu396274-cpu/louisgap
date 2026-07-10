from datetime import datetime

from core.writer_registry import WriterRegistry


class WriterAuditAdapter:
    def __init__(self, registry_path="config/writer_registry.json"):
        self.registry = WriterRegistry(registry_path)

    def audit_event(
        self,
        writer,
        action,
        target=None,
    ):
        registry_info = self.registry.get_writer(writer)
        if registry_info is None:
            registry_info = {
                "level": "UNKNOWN",
                "owner": "unknown",
                "permission": "BLOCK",
            }
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "writer": writer,
            "level": registry_info["level"],
            "owner": registry_info["owner"],
            "permission": registry_info["permission"],
            "action": action,
            "target": target,
            "observe_only": True,
        }
