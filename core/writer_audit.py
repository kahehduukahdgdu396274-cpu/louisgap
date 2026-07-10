"""
P20-10 Runtime Writer Audit Hook
Design:
- observe only
- no write interception
- no runtime behavior change
"""
import json
import os
import time
from pathlib import Path

AUDIT_FILE = Path("audit/writer_events.jsonl")


def writer_audit_event(
    writer,
    target,
    mode,
    sha_before=None,
    sha_after=None,
):
    event = {
        "timestamp": int(time.time()),
        "writer": writer,
        "target": target,
        "mode": mode,
        "sha_before": sha_before,
        "sha_after": sha_after,
        "pid": os.getpid(),
    }
    AUDIT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )
    with AUDIT_FILE.open("a") as f:
        f.write(
            json.dumps(event)
            + "\n"
        )
    return event
