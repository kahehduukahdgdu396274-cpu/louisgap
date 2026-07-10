# P20 DEVELOPMENT SCOPE FREEZE
Base:
P19_FINAL_BASELINE_20260710
Branch:
p20-development
Purpose:
Develop next generation improvements without changing P19 production baseline.
## Frozen Components (DO NOT MODIFY DIRECTLY)
- scripts/reconcile_all_from_okx.py
- scripts/state_maintenance_worker.py
- scripts/build_war_report.py
- state.json
- trades.csv
- strategy_eq.json
## Production Safety Rules
1. No bot restart during development
2. No cron modification
3. No production --repair
4. No production --apply
5. No direct runtime state editing
## Development Rules
All changes must:
- happen on p20-development
- have fixture validation
- have py_compile validation
- have rollback point
Status:
P20 DESIGN FREEZE CREATED
