from pathlib import Path
def main():
    files = [
        "docs/P20/reports/P20_12_FINAL/"
        "P20_12_9_OBSERVATION_WINDOW_FREEZE.md",
        "docs/P20/reports/P20_12_FINAL/"
        "P20_12_9_STATUS.md",
    ]
    for file in files:
        assert Path(file).exists(), file
    print(
        "P20_12_9_OBSERVATION_WINDOW_FREEZE_FIXTURE_PASS"
    )
if __name__ == "__main__":
    main()
