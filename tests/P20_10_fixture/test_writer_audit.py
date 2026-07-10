from core.writer_audit import writer_audit_event


def test_runtime_audit():
    event = writer_audit_event(
        writer="main.py",
        target="state.json",
        mode="runtime",
        sha_before="aaa",
        sha_after="bbb",
    )
    assert event["writer"] == "main.py"
    assert event["mode"] == "runtime"


def test_maintenance_audit():
    event = writer_audit_event(
        writer="state_maintenance_worker.py",
        target="state.json",
        mode="maintenance",
    )
    assert event["mode"] == "maintenance"


if __name__ == "__main__":
    test_runtime_audit()
    test_maintenance_audit()
    print("P20_10_WRITER_AUDIT_FIXTURE_PASS")
