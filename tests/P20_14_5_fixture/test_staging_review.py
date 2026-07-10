from core.staging_observation_review import (
    StagingObservationReview,
)
def main():
    snapshot = {
        "event_count": 2,
        "writers": {
            "state_maintenance_worker.py": 1,
            "unknown_writer.py": 1,
        },
    }
    report = {
        "status": "STAGING_READONLY",
        "observe_only": True,
    }
    result = (
        StagingObservationReview()
        .evaluate(
            snapshot,
            report,
        )
    )
    assert result["decision"] == "PASS"
    assert result["observe_only"] is True
    assert result["mode"] == (
        "STAGING_READONLY"
    )
    print(
        "P20_14_5_STAGING_OBSERVATION_REVIEW_FIXTURE_PASS"
    )
if __name__ == "__main__":
    main()
