# P20-5 Ownership Transition
| Writer | Current | Future |
|---|---|---|
| main.py | L0 | L0 |
| position_state.py | L0 | L0 |
| state_maintenance_worker.py | L1 | L1 + Gate |
| reconcile repair | mixed | worker only |
| build_war_report | report | report |
| legacy scripts | writer | blocked |
Principle:
One writer.
One gate.
One audit trail.
