from pathlib import Path
def main():
    files = [
        "docs/P20/reports/P20_12_8/"
        "P20_12_8_DAILY_REPORT_TEMPLATE.md",
        "docs/P20/reports/P20_12_8/"
        "P20_12_8_OBSERVATION_SUMMARY_TEMPLATE.md",
    ]
    for file in files:
        assert Path(file).exists(), file
    print(
        "P20_12_8_DAILY_REVIEW_FRAMEWORK_FIXTURE_PASS"
    )
if __name__ == "__main__":
    main()
