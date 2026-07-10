# P20-14 Cleanup Candidates

Status: CANDIDATES ONLY — do not delete without separate approval.

## Overlapping / Parallel APIs

| File | Purpose | References | Suggestion |
|---|---|---|---|
| `core/writer_audit.py` | Early P20-10 audit hook | `tests/P20_10_fixture` | Keep for regression; superseded by pipeline |
| `core/shadow_daily_snapshot.py` (`ShadowDailySnapshot` + `ShadowDailySnapshotGenerator`) | P20-12.4 / P20-13.4 dual API | P20_12_4 / P20_13_4 fixtures | Keep both classes until fixture unify |
| `core/shadow_governance_report.py` (`ShadowGovernanceReport`) | P20-13.5 API | P20_13_5 fixture | Note: P20-12.5 Generator removed on this lineage |
| `core/staging_shadow_snapshot.py` | P20-14.4 staging snapshot | P20_14_4 fixture | Parallel to shadow_* — keep |
| `core/staging_shadow_governance.py` | P20-14.4 staging governance | P20_14_4 fixture | Parallel to shadow_* — keep |
| `core/staging_readonly_event_source.py` | P20-14.2 staging source | P20_14_2 / 14_3 | Overlaps FakeProductionEventSource — keep |
| `core/production_event_source.py` | P20-14.1 interface | P20_14_1 fixture | Keep abstract interface |
| `core/shadow_readonly_adapter.py` | P20-13.1 adapter | P20_13_1 / 13_3 | Keep |
| `core/writer_shadow_collector.py` / `writer_shadow_report.py` | P20-11 shadow | P20_11_* fixtures | Keep for baseline chain |

## Empty / Placeholder Tests

| Path | Notes | Suggestion |
|---|---|---|
| `tests/P20_12_1_fixture/.gitkeep` | Design-only placeholder | Keep |
| `tests/P20_11_fixture/` | Empty local dir (untracked) | Removed locally if present |

## Docs

| Path | Notes | Suggestion |
|---|---|---|
| Phase report dirs `P20_1`…`P20_14_*` | Historical phase SSOT | Keep — audit trail |
| `docs/P20/reports/P20_14_DAILY_ASSISTANT/` | Assistant design report | Keep (not duplicate of DAILY evidence) |

## Do Not Delete

- `audit/observation/*.json`
- `docs/P20/reports/P20_14_DAILY/*`
- `docs/P20/reports/*_FINAL/*`
- Any `core/*` still imported by fixtures
