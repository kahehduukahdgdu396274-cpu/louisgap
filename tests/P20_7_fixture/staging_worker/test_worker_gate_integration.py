"""
P20-7 Worker Gate Integration Fixture
Staging only.
No production worker modification.
"""
from core.maintenance_gate import (
    check_maintenance_write
)
from core.write_gate import (
    check_writer
)
def run():
    result = []
    # Worker maintenance path
    try:
        r = check_maintenance_write()
        result.append(
            {
                "case":
                "worker maintenance",
                "status":
                "ALLOW",
                "detail":
                r
            }
        )
    except Exception as e:
        result.append(
            {
                "case":
                "worker maintenance",
                "status":
                "FAIL",
                "detail":
                str(e)
            }
        )
    # Worker runtime misuse
    r = check_writer(
        "state_maintenance_worker.py",
        mode="runtime"
    )
    result.append(
        {
            "case":
            "worker runtime misuse",
            "status":
            "BLOCK"
            if not r["allowed"]
            else "FAIL",
            "detail":
            r
        }
    )
    # Unknown writer
    r = check_writer(
        "unknown_writer.py",
        mode="maintenance"
    )
    result.append(
        {
            "case":
            "unknown writer",
            "status":
            "BLOCK"
            if not r["allowed"]
            else "FAIL",
            "detail":
            r
        }
    )
    for x in result:
        print(x)
if __name__ == "__main__":
    run()
