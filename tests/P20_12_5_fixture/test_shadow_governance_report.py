from core.shadow_governance_report import (
    ShadowGovernanceReportGenerator
)
def main():
    generator = ShadowGovernanceReportGenerator()
    snapshot = {
        "mode": "shadow",
        "observe_only": True,
        "total_events": 3,
        "writers": {
            "state_maintenance_worker.py": {
                "count": 2,
                "observe_only": True,
            },
            "unknown_shadow_writer.py": {
                "count": 1,
                "observe_only": True,
            },
        },
    }
    report = generator.generate(snapshot)
    assert report["mode"] == "shadow"
    assert report["observe_only"] is True
    assert report["total_events"] == 3
    assert len(report["violations"]) == 1
    assert (
        report["violations"][0]["permission"]
        == "BLOCK"
    )
    print(
        "P20_12_5_SHADOW_GOVERNANCE_REPORT_FIXTURE_PASS"
    )
if __name__ == "__main__":
    main()
