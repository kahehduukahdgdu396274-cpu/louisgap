from core.writer_audit_schema import validate_event
from core.writer_registry import WriterRegistry


class WriterAuditReplay:
    def __init__(
        self,
        registry_path="config/writer_registry.json",
    ):
        self.registry = WriterRegistry(
            registry_path
        )

    def replay(self, events):
        result = []
        for event in events:
            valid, errors = validate_event(
                event
            )
            if not valid:
                result.append(
                    {
                        "writer": event.get(
                            "writer"
                        ),
                        "schema": "FAIL",
                        "errors": errors,
                    }
                )
                continue
            registry = self.registry.get_writer(
                event["writer"]
            )
            if registry is None:
                result.append(
                    {
                        "writer": event["writer"],
                        "schema": "PASS",
                        "ownership": "UNKNOWN",
                        "permission": "BLOCK",
                    }
                )
                continue
            result.append(
                {
                    "writer": event["writer"],
                    "schema": "PASS",
                    "ownership": "PASS",
                    "level": registry["level"],
                    "permission": registry["permission"],
                }
            )
        return result
