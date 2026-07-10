from core.maintenance_gate import (
    check_maintenance_write,
    check_runtime_write_attempt,
    WriteGateError
)
def run():
    print("TEST 1 maintenance mode")
    try:
        result = check_maintenance_write()
        print("ALLOW", result)
    except Exception as e:
        print("FAIL", e)
    print("TEST 2 runtime mode")
    try:
        result = check_runtime_write_attempt()
        print("ALLOW", result)
    except WriteGateError as e:
        print("BLOCK", e)
if __name__ == "__main__":
    run()
