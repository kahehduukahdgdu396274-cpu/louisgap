"""
P20-4.3 Maintenance Gate Adapter
Adapter between maintenance workers
and central write_gate.
No production integration yet.
"""
from core.write_gate import (
    assert_write_allowed,
    WriteGateError
)
WRITER_ID = "state_maintenance_worker.py"
def check_maintenance_write():
    return assert_write_allowed(
        WRITER_ID,
        mode="maintenance"
    )
def check_runtime_write_attempt():
    return assert_write_allowed(
        WRITER_ID,
        mode="runtime"
    )
__all__ = [
    "check_maintenance_write",
    "check_runtime_write_attempt",
    "WriteGateError",
]
