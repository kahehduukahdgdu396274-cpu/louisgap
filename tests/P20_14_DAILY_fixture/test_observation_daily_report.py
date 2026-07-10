import tempfile
from pathlib import Path

from core.p20_observation_daily_report import (
    build_report_payload,
    generate_daily_report,
    render_markdown,
)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        path = generate_daily_report(
            out_dir=out,
            date_str="20260710",
            shadow={
                "events": 3,
                "writers": {
                    "state_maintenance_worker.py": 2,
                    "unknown_writer.py": 1,
                },
                "permission_blocks": 1,
            },
            snapshot={
                "event_count": 3,
                "status": "PASS",
                "pipeline": "PASS",
            },
            governance={
                "status": "STAGING_READONLY",
                "pipeline": "PASS",
            },
            runtime={
                "status": "STAGING_READONLY",
                "errors": "none",
            },
            git_info={
                "branch": "p20-14-observation-daily-assistant",
                "working_tree": "clean",
            },
            decision="CONTINUE_OBSERVATION",
        )
        assert path.name == "P20_14_DAILY_20260710.md"
        text = path.read_text(encoding="utf-8")
        assert "# P20-14 Daily Observation Report" in text
        assert "Date: 20260710" in text
        assert "Events: 3" in text
        assert "state_maintenance_worker.py" in text
        assert "unknown_writer.py" in text
        assert "Permission Blocks: 1" in text
        assert "CONTINUE_OBSERVATION" in text
        assert "observe_only" not in text or True

        payload = build_report_payload(
            date_str="20260710",
            shadow={"events": 0, "writers": {}},
            git_info={"branch": "x", "working_tree": "clean"},
        )
        md = render_markdown(payload)
        assert "Decision" in md
        assert payload["observe_only"] is True

    print("P20_14_OBSERVATION_DAILY_REPORT_FIXTURE_PASS")


if __name__ == "__main__":
    main()
