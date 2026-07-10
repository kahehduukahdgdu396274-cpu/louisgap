# P20-14.1 Readonly Production Event Source Interface
Status:
COMPLETE
## Purpose
Define abstract readonly production event source
for Controlled Observation Enablement.
## Interface
ProductionEventSource.read_events()
FakeProductionEventSource (fixture only)
## Safety
- No VPS connection
- No real state.json read
- No bot runtime access
- No cron / systemd change
- No writer interception
Mode:
DESIGN ONLY / SHADOW READY
## Next
P20-14.2 staging read-only wiring
requires Louis approval
