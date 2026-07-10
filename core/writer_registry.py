import json
from pathlib import Path


class WriterRegistry:
    def __init__(self, path="config/writer_registry.json"):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text())

    def get_writer(self, name):
        return self.data.get("writers", {}).get(name)

    def list_writers(self):
        return self.data.get("writers", {})

    def get_level(self, name):
        writer = self.get_writer(name)
        return writer.get("level") if writer else None

    def get_permission(self, name):
        writer = self.get_writer(name)
        return writer.get("permission") if writer else None
