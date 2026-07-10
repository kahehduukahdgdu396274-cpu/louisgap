# P20-4.2 Writer Migration Matrix
## L0 Runtime Writer
| Component | Action |
|---|---|
| main.py | KEEP, future gate injection |
| position_state.py | KEEP, future gate injection |
## L1 Maintenance Writer
| Component | Action |
|---|---|
| state_maintenance_worker.py | CONNECT write_gate |
## L2 Repair / Audit
| Component | Action |
|---|---|
| reconcile_all_from_okx.py | READONLY |
| --repair route | worker only |
## L3 Report Writer
| Component | Action |
|---|---|
| build_war_report.py | READONLY |
## L4 Legacy Writer
| Component | Action |
|---|---|
| govern_state_legs.py | BLOCK / migrate |
| prune_old_realized_legs.py | BLOCK / migrate |
| old sync scripts | archive |
Migration Rules:
1. No direct state writer without gate.
2. Runtime writer keeps priority.
3. Maintenance writes require explicit mode.
4. Unknown writers blocked.
5. Every migration tested in fixture first.
