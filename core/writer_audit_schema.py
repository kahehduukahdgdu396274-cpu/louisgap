REQUIRED_FIELDS = {
    "timestamp",
    "writer",
    "level",
    "owner",
    "permission",
    "action",
    "target",
    "observe_only",
}


def validate_event(event):
    missing = REQUIRED_FIELDS - set(event.keys())
    if missing:
        return False, sorted(list(missing))
    if event["observe_only"] is not True:
        return False, ["observe_only must be True"]
    return True, []
