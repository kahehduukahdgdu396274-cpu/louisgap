def main():
    marker = {
        "status": "ACTIVE",
        "mode": "STAGING_READONLY",
        "decision": "WAITING_FOR_OBSERVATION_RESULT",
    }
    assert marker["status"] == "ACTIVE"
    assert marker["mode"] == "STAGING_READONLY"
    assert (
        marker["decision"]
        ==
        "WAITING_FOR_OBSERVATION_RESULT"
    )
    print(
        "P20_14_7_CONTROLLED_OBSERVATION_WINDOW_START_FIXTURE_PASS"
    )
if __name__ == "__main__":
    main()
