"""
P20-9.1 Worker Gate Adapter
Adapter layer only.
Does not replace existing worker checks.
"""
from core.write_gate import check_writer
from core.maintenance_gate import check_maintenance_write
def authorize_worker_write():
    result = check_writer(
        "state_maintenance_worker.py",
        mode="maintenance"
    )
    if not result.get("allowed"):
        raise RuntimeError(
            "P20 WRITE GATE BLOCKED WORKER"
        )
    check_maintenance_write()
    return True
