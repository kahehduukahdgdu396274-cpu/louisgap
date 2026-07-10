# P20-12.3 Shadow Observation Storage Design
Status:
COMPLETE
Pipeline:
Shadow Event
    |
    v
Readonly Observation Storage
    |
    v
Snapshot
Validation:
- append shadow event PASS
- snapshot read PASS
- tempfile isolation PASS
Safety:
- no production writer
- no runtime modification
- no cron modification
- no bot restart
Mode:
SHADOW ONLY
