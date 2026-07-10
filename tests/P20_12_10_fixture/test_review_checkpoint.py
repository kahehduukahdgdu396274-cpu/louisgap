from pathlib import Path
def main():
    files = [
        "docs/P20/reports/P20_12_10/"
        "P20_12_10_REVIEW_CHECKPOINT.md",
        "docs/P20/reports/P20_12_10/"
        "P20_12_10_REVIEW_SUMMARY_TEMPLATE.md",
    ]
    for file in files:
        assert Path(file).exists(), file
    print(
        "P20_12_10_OBSERVATION_REVIEW_CHECKPOINT_FIXTURE_PASS"
    )
if __name__ == "__main__":
    main()
