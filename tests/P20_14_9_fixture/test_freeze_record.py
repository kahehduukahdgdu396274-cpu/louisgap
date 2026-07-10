def main():
    record = {
        "status": "FROZEN",
        "mode": "STAGING_READONLY",
        "observation": "ACTIVE",
        "decision": "WAITING_FOR_OBSERVATION_DATA",
    }
    assert record["status"] == "FROZEN"
    assert record["mode"] == "STAGING_READONLY"
    assert record["observation"] == "ACTIVE"
    assert (
        record["decision"]
        ==
        "WAITING_FOR_OBSERVATION_DATA"
    )
    print(
        "P20_14_9_OBSERVATION_WINDOW_FREEZE_RECORD_FIXTURE_PASS"
    )
if __name__ == "__main__":
    main()
