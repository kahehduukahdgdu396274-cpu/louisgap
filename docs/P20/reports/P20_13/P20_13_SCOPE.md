# P20-13 Shadow Observer Production Hook
Status:
DESIGN ONLY
Goal:
Connect shadow observer to production observation source
without modifying production behavior.
## Allowed
- read-only observation
- event sampling
- governance reporting
## Forbidden
- writer interception
- permission changes
- runtime mutation
- cron changes
- repair/apply execution
- trading logic changes
## Architecture
Production Event Source
        ↓
Shadow Observer Hook
        ↓
WriterShadowCollector
        ↓
Governance Report
Mode:
SHADOW ONLY
