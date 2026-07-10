import json
from pathlib import Path
from datetime import datetime
class ShadowObservationStorage:
    """
    P20-12.3
    Read-only observation storage abstraction.
    This module stores shadow observations only.
    It does not control production writers.
    """
    def __init__(self, path):
        self.path = Path(path)
    def append(self, event):
        record = dict(event)
        record["stored_at"] = datetime.utcnow().isoformat()
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    def snapshot(self):
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as f:
            return [
                json.loads(line)
                for line in f
                if line.strip()
            ]
