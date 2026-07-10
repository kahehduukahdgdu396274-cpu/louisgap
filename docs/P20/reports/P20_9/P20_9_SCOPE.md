# P20-9 Worker Gate Controlled Migration
Scope:
- state_maintenance_worker.py only
Rules:
- no bot restart
- no cron modification
- no repair execution
- no runtime state write
Flow:
development
 -> fixture
 -> staging
 -> readonly observation
 -> production approval
