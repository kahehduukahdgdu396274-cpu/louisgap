# P20-14 Observation Note
Date: 20260711

## Issue
Repeated ghost open_positions in war report

## Root Cause
Readonly war report skipped trades.csv projection sync

## Fix
Enable trades.csv reconciliation in readonly report build path

## Safety
No trading/runtime logic changed

## Validation
CSV/state/report aligned

## Status
RESOLVED

## Evidence
- VPS deploy: `build_war_report.py` (`_BWR_TRADES_CSV_OPS` always-on)
- Backup: `build_war_report.py.bak_bwr_trades_ops_20260711_060232`
- Smoke: `python3 build_war_report.py` (no `--repair`) synced open 021
- Align: CSV / state / war `total_open=1` (021 only) @ 2026-07-11 06:03
