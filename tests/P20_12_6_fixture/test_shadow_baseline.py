from pathlib import Path
def main():
    required = [
        "core/shadow_observation_storage.py",
        "core/shadow_daily_snapshot.py",
        "core/shadow_governance_report.py",
    ]
    for item in required:
        assert Path(item).exists(), item
    print(
        "P20_12_6_SHADOW_OBSERVATION_BASELINE_FIXTURE_PASS"
    )
if __name__ == "__main__":
    main()
