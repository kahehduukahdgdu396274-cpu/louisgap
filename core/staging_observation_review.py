"""
P20-14.5 Staging Observation Review
Readonly review gate only.
"""
class StagingObservationReview:
    def evaluate(self, snapshot, report):
        event_count = snapshot.get(
            "event_count",
            0,
        )
        observe_only = report.get(
            "observe_only",
            False,
        )
        if event_count >= 0 and observe_only:
            decision = "PASS"
        else:
            decision = "HOLD"
        return {
            "decision": decision,
            "mode": "STAGING_READONLY",
            "observe_only": True,
            "event_count": event_count,
        }
