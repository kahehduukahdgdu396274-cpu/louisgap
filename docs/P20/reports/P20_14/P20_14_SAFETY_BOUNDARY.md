# P20-14 Safety Boundary
## Production Write Path (unchanged)
bot → trading logic → P20 Worker Gate → safe writes
## Observation Sidecar (new, readonly)
readonly event source → adapter → shadow observer → audit → report
## Hard Rules
- No state.json writes from observer
- No position_*.json writes from observer
- No bot restart
- No cron change in this phase (unless Louis explicit approve)
- No repair/apply
- No permission promotion
