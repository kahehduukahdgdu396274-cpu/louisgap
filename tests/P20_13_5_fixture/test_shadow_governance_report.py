from core.shadow_governance_report import (
    ShadowGovernanceReport,
)
def main():
    snapshot = {
        "event_count": 3,
        "writers": {
            "state_maintenance_worker.py": 2,
            "unknown_writer.py": 1,
        },
        "observe_only": True,
    }
    report = ShadowGovernanceReport()
    result = report.generate(snapshot)
    assert result["observe_only"] is True
    assert result["status"] == "SHADOW_ONLY"
    assert result["writer_count"] == 2
    assert result["event_count"] == 3
    print(
        "P20_13_5_SHADOW_GOVERNANCE_REPORT_FIXTURE_PASS"
    )
if __name__ == "__main__":
    main()
