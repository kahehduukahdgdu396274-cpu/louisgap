# P20-10 Event Schema Version

## Version

`P20-10.4`

Frozen at commit: `c31c88f` (P20-10.4 freeze writer audit event schema)

## Required Fields

| Field | Type | Description |
|---|---|---|
| timestamp | string (ISO8601 UTC) | event time |
| writer | string | writer module name |
| level | string | L0 / L1 / L2 / L3 / L4 / UNKNOWN |
| owner | string | runtime / maintenance / audit / report / legacy / unknown |
| permission | string | ALLOW_RUNTIME / ALLOW_MAINTENANCE / READONLY / BLOCK |
| action | string | e.g. write_attempt |
| target | string \| null | e.g. state.json |
| observe_only | bool | **must be true** |

## Validator

Module: `core/writer_audit_schema.py`

```python
validate_event(event) -> (bool, errors)
```

## Unknown Writer Defaults

When writer not in registry:

```json
{
  "level": "UNKNOWN",
  "owner": "unknown",
  "permission": "BLOCK"
}
```

## Storage Format

- File: `audit/writer_events.jsonl`
- Format: one JSON object per line (append-only)
- Gitignored: `audit/writer_events.jsonl`

## Changelog

| Version | Change |
|---|---|
| P20-10 | Initial writer_audit_event (flat fields + writer_level) |
| P20-10.3 | Nested registry object in adapter output |
| P20-10.4 | **Frozen** flat 8-field schema (current) |
