from core.legacy_writer_guard import (
    check_legacy_writer
)
import os
def run():
    print("CASE legacy dev")
    os.environ["HERMES_PRODUCTION"]="0"
    print(
        check_legacy_writer(
            "govern_state_legs.py"
        )
    )
    print("CASE legacy production")
    os.environ["HERMES_PRODUCTION"]="1"
    try:
        check_legacy_writer(
            "govern_state_legs.py"
        )
        print("FAIL")
    except Exception as e:
        print(
            "BLOCK",
            e
        )
    print("CASE normal writer")
    print(
        check_legacy_writer(
            "main.py"
        )
    )
if __name__=="__main__":
    run()
