from pathlib import Path
def main():
    required = [
        "docs/P20/reports/P20_12_7/P20_12_7_OBSERVATION_WINDOW_START.md",
        "docs/P20/reports/P20_12_7/P20_12_7_DAILY_CHECKLIST.md",
    ]
    for item in required:
        assert Path(item).exists(), item
    print(
        "P20_12_7_OBSERVATION_WINDOW_START_FIXTURE_PASS"
    )
if __name__ == "__main__":
    main()
