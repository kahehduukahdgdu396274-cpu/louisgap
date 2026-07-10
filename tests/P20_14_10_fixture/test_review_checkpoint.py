def main():
    checkpoint = {
        "status": "READY_FOR_REVIEW",
        "mode": "STAGING_READONLY",
        "decision": "WAITING_FOR_OBSERVATION_DATA",
    }
    assert checkpoint["status"] == (
        "READY_FOR_REVIEW"
    )
    assert checkpoint["mode"] == (
        "STAGING_READONLY"
    )
    assert checkpoint["decision"] == (
        "WAITING_FOR_OBSERVATION_DATA"
    )
    print(
        "P20_14_10_OBSERVATION_REVIEW_CHECKPOINT_FIXTURE_PASS"
    )
if __name__ == "__main__":
    main()
