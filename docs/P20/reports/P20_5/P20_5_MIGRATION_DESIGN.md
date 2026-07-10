# P20-5 Writer Migration Design
## Objective
Move Hermes toward controlled writer ownership.
No production behavior change.
---
# Phase 1
## L1 Maintenance Gate Integration
Target:
state_maintenance_worker.py
Rules:
- explicit maintenance mode only
- write_gate required
- audit before write
- backup before apply
Status:
Adapter ready.
---
# Phase 2
## L4 Legacy Writer Isolation
Targets:
- govern_state_legs.py
- prune_old_realized_legs.py
- old sync scripts
Action:
- mark deprecated
- add warning
- block production usage
---
# Phase 3
## L2 Repair Flow
Target:
reconcile_all_from_okx.py
Rules:
readonly default.
repair:
reconcile
    |
    v
worker
---
# Phase 4
## L0 Runtime Audit Hook
Targets:
main.py
position_state.py
Rules:
- keep performance path
- optional gate audit
- no behavior change
---
Rollback:
Each phase requires:
- git commit
- SHA snapshot
- runtime SHA check
