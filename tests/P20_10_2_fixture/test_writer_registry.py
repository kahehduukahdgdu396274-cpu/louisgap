from core.writer_registry import WriterRegistry


def main():
    registry = WriterRegistry()
    cases = {
        "main.py": "ALLOW_RUNTIME",
        "state_maintenance_worker.py": "ALLOW_MAINTENANCE",
        "reconcile_all_from_okx.py": "READONLY",
        "build_war_report.py": "READONLY",
        "govern_state_legs.py": "BLOCK",
    }
    for writer, expected in cases.items():
        actual = registry.get_permission(writer)
        assert actual == expected, (
            f"{writer}: {actual} != {expected}"
        )
    assert registry.get_level("main.py") == "L0"
    assert registry.get_level("govern_state_legs.py") == "L4"
    print("P20_10_2_WRITER_REGISTRY_FIXTURE_PASS")


if __name__ == "__main__":
    main()
