from core.writer_audit_adapter import (
    audit_writer_action,
    resolve_writer_level,
)


def test_l0_runtime():
    result = audit_writer_action(
        writer="main.py",
        target="state.json",
        mode="runtime",
    )
    assert result["writer_level"] == "L0_RUNTIME"


def test_l1_maintenance():
    result = audit_writer_action(
        writer="state_maintenance_worker.py",
        target="state.json",
        mode="maintenance",
    )
    assert result["writer_level"] == "L1_MAINTENANCE"


def test_unknown():
    assert resolve_writer_level("unknown.py") == "UNKNOWN"


if __name__ == "__main__":
    test_l0_runtime()
    test_l1_maintenance()
    test_unknown()
    print("P20_10_1_WRITER_AUDIT_ADAPTER_PASS")
