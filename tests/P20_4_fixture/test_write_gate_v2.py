from core.write_gate import (
    check_writer,
    assert_write_allowed,
    WriteGateError
)
def test():
    cases = [
        ("main.py", "runtime"),
        ("position_state.py", "runtime"),
        ("state_maintenance_worker.py", "maintenance"),
        ("state_maintenance_worker.py", "runtime"),
        ("reconcile_all_from_okx.py", "runtime"),
        ("unknown.py", "runtime"),
    ]
    for writer, mode in cases:
        try:
            result = assert_write_allowed(
                writer,
                mode
            )
            print(
                writer,
                mode,
                "ALLOW",
                result
            )
        except WriteGateError as e:
            print(
                writer,
                mode,
                "BLOCK",
                e
            )
if __name__ == "__main__":
    test()
