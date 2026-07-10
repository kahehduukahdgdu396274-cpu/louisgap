from pathlib import Path
def main():
    files = [
        "docs/P20/reports/P20_12_11/"
        "P20_12_11_OBSERVATION_RESULT_RECORD.md",
        "docs/P20/reports/P20_12_11/"
        "P20_12_11_RESULT_SUMMARY_TEMPLATE.md",
    ]
    for file in files:
        assert Path(file).exists(), file
    print(
        "P20_12_11_OBSERVATION_RESULT_RECORD_FIXTURE_PASS"
    )
if __name__ == "__main__":
    main()
