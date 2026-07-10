from core.write_gate import (
    check_writer,
    WriteGateError
)
from core.maintenance_gate import (
    check_maintenance_write
)
def check():
    results = []
    # worker maintenance path
    try:
        r = check_maintenance_write()
        results.append({
            "case": "worker maintenance",
            "result": "ALLOW",
            "detail": r
        })
    except Exception as e:
        results.append({
            "case": "worker maintenance",
            "result": "FAIL",
            "detail": str(e)
        })
    # worker runtime misuse
    try:
        check_writer(
            "state_maintenance_worker.py",
            mode="runtime"
        )
        results.append({
            "case": "worker runtime misuse",
            "result": "FAIL"
        })
    except Exception as e:
        results.append({
            "case": "worker runtime misuse",
            "result": "BLOCK",
            "detail": str(e)
        })
    # reconcile readonly
    r = check_writer(
        "reconcile_all_from_okx.py",
        mode="runtime"
    )
    results.append({
        "case": "reconcile readonly",
        "result": "BLOCK" if not r["allowed"] else "FAIL",
        "detail": r
    })
    # unknown writer
    r = check_writer(
        "unknown_writer.py",
        mode="runtime"
    )
    results.append({
        "case": "unknown writer",
        "result": "BLOCK" if not r["allowed"] else "FAIL",
        "detail": r
    })
    for item in results:
        print(item)
if __name__ == "__main__":
    check()
