import json
from pathlib import Path
BASE = Path(__file__).parent
def load_policy():
    return json.loads(
        (BASE / "fixture_policy.json").read_text()
    )
def check(writer):
    p = load_policy()
    if writer in p["allowed_runtime_writers"]:
        return "ALLOW_RUNTIME"
    if writer in p["allowed_maintenance_writer"]:
        return "ALLOW_MAINTENANCE"
    if writer in p["readonly_components"]:
        return "READONLY"
    return "BLOCK"
def main():
    cases = [
        "main.py",
        "position_state.py",
        "state_maintenance_worker.py",
        "reconcile_all_from_okx.py",
        "build_war_report.py",
        "unknown_writer.py",
    ]
    for c in cases:
        print(c, "=>", check(c))
if __name__ == "__main__":
    main()
