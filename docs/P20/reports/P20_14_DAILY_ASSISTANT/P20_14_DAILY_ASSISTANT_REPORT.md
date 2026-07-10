# P20-14 Observation Daily Assistant
Status:
COMPLETE
## Purpose
Generate readonly daily observation reports under:
`docs/P20/reports/P20_14_DAILY/P20_14_DAILY_YYYYMMDD.md`
## Inputs (readonly)
- Shadow Observer status (in-memory / caller-provided)
- Snapshot status
- Governance report fields
- Git branch / working tree (readonly `git` queries)
## Outputs
- Markdown daily report only
## Safety
- No production write path
- No main.py / worker / cron changes
- No audit/writer_events.jsonl writes
- Fixture uses tempfile isolation
Mode:
STAGING READONLY
Decision default:
CONTINUE_OBSERVATION
