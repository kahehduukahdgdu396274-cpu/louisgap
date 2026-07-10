# P20-5 Rollback Plan
Before every migration:
1. git tag
2. code SHA snapshot
3. runtime SHA snapshot
Rollback:
git checkout previous tag
No runtime restore unless runtime changed.
