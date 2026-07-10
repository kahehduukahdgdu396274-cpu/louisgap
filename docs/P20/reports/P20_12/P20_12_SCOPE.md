# P20-12 Shadow Observation Window Scope
## Status
INITIALIZED
## Goal
建立 P20 Writer Shadow Observation Window，
在不改变生产 writer 权限、不影响交易逻辑的前提下，
观察 writer 行为并生成治理报告。
## Non-Goals
- 不修改 main.py
- 不修改 position_state.py
- 不修改 writer authority
- 不修改 write path
- 不修改 cron
- 不 restart bot
- 不执行 repair/apply
## Architecture
Production Events
        |
        v
Writer Audit Pipeline
        |
        v
Shadow Observation Layer
        |
        v
Governance Reports
## Observation Period
7-14 days
## Safety Boundary
Mode:
Shadow Only
Permission:
Observe Only
