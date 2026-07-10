"""
P20-6 Legacy Writer Isolation
Legacy writers are not allowed
in production runtime paths.
"""
import os
import warnings
LEGACY_WRITERS = {
    "govern_state_legs.py",
    "prune_old_realized_legs.py",
}
def is_production_context():
    return os.environ.get(
        "HERMES_PRODUCTION",
        "0"
    ) == "1"
def check_legacy_writer(writer):
    if writer in LEGACY_WRITERS:
        if is_production_context():
            raise RuntimeError(
                f"LEGACY WRITER BLOCKED: {writer}"
            )
        warnings.warn(
            f"LEGACY WRITER DEPRECATED: {writer}"
        )
        return False
    return True
