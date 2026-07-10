# P20-14 Controlled Observation Enablement
## Status
INITIALIZED
## Goal
在不改变生产写路径、交易逻辑、risk、cron、bot 的前提下，
将 Shadow Observer 接到**只读生产事件源**，
生成 Daily Governance Report。
## Architecture
Production Readonly Event Source
        ↓
Readonly Adapter
        ↓
Shadow Observer
        ↓
Writer Audit Pipeline
        ↓
Daily Governance Report
## Allowed
- readonly event sampling
- shadow observation
- governance reporting
## Forbidden
- write state / position
- modify bot / main.py
- modify cron
- writer interception
- permission / gate changes
- repair / apply
- trading logic / risk changes
## Observation Period
7-14 days after enablement approval
## Decision Gate (post-window)
CONTINUE_OBSERVATION
or
READY_FOR_P20_15_GOVERNANCE_REVIEW
## Mode
CONTROLLED OBSERVATION
SHADOW ONLY
NO PROMOTE
