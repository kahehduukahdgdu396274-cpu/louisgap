# P20-3 Writer Ownership Matrix
## Level 0 - Primary Runtime Writer
### main.py
Authority:
BOT EXECUTION PATH
Allowed:
- position update
- state update
- strategy equity update
Conditions:
- live bot process
- trade execution event
### position_state.py
Authority:
STATE CORE
Allowed:
- save_all
- save_state
- position persistence
Conditions:
- bot runtime only
---
# Level 1 - Controlled Maintenance Writer
## state_maintenance_worker.py
Authority:
MAINTENANCE ONLY
Allowed:
- prune
- rebuild trades
- sync equity
Conditions:
- explicit --repair
- confirmation flag
- maintenance gate
---
# Level 2 - Audit Only
## reconcile_all_from_okx.py
Default:
READ ONLY
Allowed:
- compare OKX/state/position
- generate audit
Forbidden:
- runtime mutation
Repair mode:
Route:
reconcile
  |
  v
state_maintenance_worker
---
# Level 3 - Report Writer
## build_war_report.py
Allowed:
- xlsx
- markdown
- report artifacts
Forbidden:
- state mutation
---
# Level 4 - Deprecated / Historical Writers
Examples:
- govern_state_legs.py
- prune_old_realized_legs.py
- old sync directories
Action:
Move to:
archive / maintenance only
---
# SSOT RULE
Runtime state writers:
1. main.py
2. position_state.py
3. state_maintenance_worker.py
All others:
READ ONLY
