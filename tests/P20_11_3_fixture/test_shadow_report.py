from core.writer_shadow_report import WriterShadowReportGenerator
def main():
    events = [
        {
            "writer": "state_maintenance_worker.py",
            "level": "L1",
            "permission": "ALLOW_MAINTENANCE",
            "observe_only": True,
        },
        {
            "writer": "state_maintenance_worker.py",
            "level": "L1",
            "permission": "ALLOW_MAINTENANCE",
            "observe_only": True,
        },
        {
            "writer": "unknown_shadow_writer.py",
            "level": "UNKNOWN",
            "permission": "BLOCK",
            "observe_only": True,
        },
    ]
    report = WriterShadowReportGenerator().generate(events)
    assert report["total_events"] == 3
    assert report["writers"]["state_maintenance_worker.py"] == 2
    assert report["writers"]["unknown_shadow_writer.py"] == 1
    assert report["levels"]["L1"] == 2
    assert report["levels"]["UNKNOWN"] == 1
    assert report["observe_only"] is True
    print(
        "P20_11_3_SHADOW_GOVERNANCE_REPORT_FIXTURE_PASS"
    )
if __name__ == "__main__":
    main()
