# P20-10 Writer Ownership Summary

## Ownership Model

| Level | Writer | Permission |
|---|---|---|
| L0 | main.py / position_state.py | runtime writer |
| L1 | state_maintenance_worker.py | maintenance writer |
| L2 | reconcile_all_from_okx.py | readonly / repair routed |
| L3 | build_war_report.py | report only |
| L4 | govern_state_legs.py / prune_old_realized_legs.py | blocked |

## Production Gate (P20-9)

| Component | Status |
|---|---|
| core/write_gate.py | production (worker path) |
| core/maintenance_gate.py | production (worker path) |
| core/worker_gate_adapter.py | production (worker path) |
| scripts/state_maintenance_worker.py | production (gate invoke) |

## Audit Layer (P20-10)

| Component | Status |
|---|---|
| core/writer_audit.py | design / fixture only |
| core/writer_audit_adapter.py | design / fixture only |
| core/writer_registry.py | design / fixture only |
| core/writer_audit_schema.py | design / fixture only |
| core/writer_audit_storage.py | design / fixture only |
| core/writer_audit_pipeline.py | design / fixture only |
| core/writer_audit_replay.py | design / fixture only |

## Governance Rule

One writer.
One gate.
One audit trail.

All P20-10 audit components remain **observe-only** and are **not** integrated into production writer paths.

## Rollback

- Production gate rollback: `P19_FINAL_BASELINE_20260710`
- Audit design rollback: remove `core/writer_audit*` from future promote only
