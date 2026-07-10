import json
import tempfile
from pathlib import Path

from core.p20_observation_daily_check import run_daily_check


def _valid_payload():
    return {
        "timestamp": "2026-07-10T12:00:00Z",
        "runtime_status": {"ok": True},
        "bot_status": {"active": True},
        "shadow_events": {"count": 1},
        "known_writers": ["state_maintenance_worker.py"],
        "unknown_writers": [],
        "permission_blocks": {},
        "pipeline_status": {"ok": True},
        "safety_check": {"readonly": True},
    }


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        audit = root / "audit" / "observation"
        daily = root / "daily"
        audit.mkdir(parents=True)
        daily.mkdir(parents=True)
        day = "20260710"

        # missing evidence -> FAIL
        miss = run_daily_check(
            date_str=day,
            audit_dir=audit,
            daily_dir=daily,
            out_dir=daily,
        )
        assert miss["evidence"] == "FAIL"
        assert miss["decision"] == "CONTINUE_OBSERVATION"
        assert (daily / f"P20_14_DAILY_CHECK_{day}.md").exists()

        # valid evidence -> PASS
        (audit / f"daily_observation_{day}.json").write_text(
            json.dumps(_valid_payload()),
            encoding="utf-8",
        )
        (daily / f"P20_14_RUNTIME_EVIDENCE_{day}.md").write_text(
            "# evidence\n",
            encoding="utf-8",
        )
        ok = run_daily_check(
            date_str=day,
            audit_dir=audit,
            daily_dir=daily,
            out_dir=daily,
        )
        assert ok["evidence"] == "PASS"
        assert ok["schema"] == "PASS"
        assert ok["safety"] == "PASS"
        assert ok["overall"] == "PASS"

        # safety without readonly -> FAIL
        bad = _valid_payload()
        bad["safety_check"] = {"readonly": False}
        (audit / f"daily_observation_{day}.json").write_text(
            json.dumps(bad),
            encoding="utf-8",
        )
        unsafe = run_daily_check(
            date_str=day,
            audit_dir=audit,
            daily_dir=daily,
            out_dir=daily,
        )
        assert unsafe["safety"] == "FAIL"
        assert unsafe["overall"] == "FAIL"
        text = (daily / f"P20_14_DAILY_CHECK_{day}.md").read_text(
            encoding="utf-8"
        )
        assert "# Daily Check" in text
        assert "CONTINUE_OBSERVATION" in text

    print("P20_14_OBSERVATION_DAILY_CHECK_FIXTURE_PASS")


if __name__ == "__main__":
    main()
