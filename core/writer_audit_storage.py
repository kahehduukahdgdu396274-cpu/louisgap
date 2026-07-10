import hashlib
import json
from datetime import datetime
from pathlib import Path


class WriterAuditStorage:
    def __init__(self, path="audit/writer_events.jsonl"):
        self.path = Path(path)

    def append_event(self, event):
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True
        )
        with self.path.open(
            "a",
            encoding="utf-8"
        ) as f:
            f.write(
                json.dumps(
                    event,
                    ensure_ascii=False
                )
                + "\n"
            )

    def read_events(self):
        if not self.path.exists():
            return []
        result = []
        with self.path.open(
            encoding="utf-8"
        ) as f:
            for line in f:
                if line.strip():
                    result.append(
                        json.loads(line)
                    )
        return result

    def checksum(self):
        if not self.path.exists():
            return None
        sha256 = hashlib.sha256()
        with self.path.open("rb") as f:
            sha256.update(f.read())
        return sha256.hexdigest()

    def snapshot(self):
        return {
            "file": str(self.path),
            "exists": self.path.exists(),
            "checksum": self.checksum(),
            "timestamp": datetime.utcnow().isoformat(),
        }
