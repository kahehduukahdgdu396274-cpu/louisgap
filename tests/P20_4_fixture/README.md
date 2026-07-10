# P20-4 Write Gate Fixture
Purpose:
Validate writer ownership without touching production.
Fake Runtime:
- state.json
- trades.csv
- strategy_eq.json
- position files
Test Cases:
## Case 1
Approved runtime writer
Expected:
ALLOW
## Case 2
Maintenance worker
Expected:
ALLOW only with repair gate
## Case 3
Reconcile default
Expected:
READ ONLY
## Case 4
Report generator
Expected:
REPORT ONLY
## Case 5
Unknown writer
Expected:
BLOCK
Safety:
No production path.
