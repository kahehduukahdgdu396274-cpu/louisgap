"""
P20-9.2 staging worker integration fixture
No production worker modification.
"""
from core.worker_gate_adapter import authorize_worker_write
from core.write_gate import check_writer
def test_worker_gate():
    results = []
    # Case 1:
    # maintenance worker write
    try:
        authorize_worker_write()
        results.append(
            (
                "worker maintenance",
                "ALLOW"
            )
        )
    except Exception as e:
        results.append(
            (
                "worker maintenance",
                f"FAIL {e}"
            )
        )
    # Case 2:
    # runtime misuse
    try:
        r = check_writer(
            "state_maintenance_worker.py",
            mode="runtime"
        )
        if r.get("allowed"):
            results.append(
                (
                    "worker runtime misuse",
                    "FAIL"
                )
            )
        else:
            results.append(
                (
                    "worker runtime misuse",
                    "BLOCK"
                )
            )
    except Exception as e:
        results.append(
            (
                "worker runtime misuse",
                "BLOCK"
            )
        )
    # Case 3:
    # unknown writer
    try:
        r = check_writer(
            "unknown_writer.py",
            mode="maintenance"
        )
        if r.get("allowed"):
            results.append(
                (
                    "unknown writer",
                    "FAIL"
                )
            )
        else:
            results.append(
                (
                    "unknown writer",
                    "BLOCK"
                )
            )
    except Exception:
        results.append(
            (
                "unknown writer",
                "BLOCK"
            )
        )
    for item in results:
        print(item)
if __name__ == "__main__":
    test_worker_gate()
