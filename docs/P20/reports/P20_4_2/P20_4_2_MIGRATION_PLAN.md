# P20-4.2 Migration Plan
Phase 1:
Gate adapter only.
No behavior change.
Phase 2:
Connect maintenance worker.
Phase 3:
Connect legacy maintenance scripts.
Phase 4:
Runtime writer optional audit hook.
Safety:
- no production modification
- no cron modification
- no runtime write
- rollback by git commit
