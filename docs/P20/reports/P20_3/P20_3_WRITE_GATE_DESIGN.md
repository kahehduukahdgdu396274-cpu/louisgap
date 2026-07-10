# P20-3 Write Gate Design
## Objective
Prevent unauthorized runtime mutation.
## Required Controls
### Runtime Writer Token
Only approved writer can modify:
- state.json
- trades.csv
- strategy_eq.json
### Maintenance Gate
Requires:
--repair
+
explicit confirmation
### Audit
Every write records:
- writer
- timestamp
- operation
- before sha256
- after sha256
## Rollback
Every maintenance write:
backup first
then apply
then verify hash
Status:
DESIGN READY
