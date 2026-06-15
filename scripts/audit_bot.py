#!/usr/bin/env python3
"""Full audit of bot state, code, and runtime issues."""
import json

# 1. health_snapshot.json
h = json.load(open("/home/admin/okx_bot/logs/health_snapshot.json"))
print("=== health_snapshot ===")
for k in ["status","okx_aligned","state_synced","heartbeat_stale","heartbeat_desync","critical_alerts_today","ws_rest_warn_count_today"]:
    print(f"  {k} = {h.get(k)}")
okx = h.get("okx_alignment", {})
print(f"  okx_net={okx.get('okx_net')} state_net={okx.get('state_net')} aligned={okx.get('aligned')}")

# 2. state.json
s = json.load(open("/home/admin/okx_bot/state.json"))
print("\n=== state.json ===")
print(f"  schema_version: {s.get('schema_version')}")
print(f"  net: {s.get('net_position')}")
t = s.get("tranches", [])
print(f"  tranches: {len(t)}")
for tr in t:
    print(f"    {tr['tranche_id']} {tr['direction']} @ {tr['entry_price']} qty={tr['remaining_qty']}")
nlegs = len(s.get("realized_legs", []))
print(f"  realized_legs: {nlegs}")
total_pnl = sum(leg.get("net_pnl", 0) for leg in s.get("realized_legs", []))
print(f"  total realized pnl: {total_pnl:+.2f}")

# 3. position_*.json
import os, glob
print("\n=== position_*.json ===")
for f in sorted(glob.glob("/home/admin/okx_bot/position_*.json")):
    sid = os.path.basename(f).replace("position_","").replace(".json","")
    try:
        p = json.load(open(f))
        if p.get("position"):
            print(f"  {sid}: pos={p['position']} dir={p.get('direction','?')} entry={p['entry_price']} qty={p.get('remaining_qty',0)}")
        else:
            print(f"  {sid}: 空仓")
    except:
        print(f"  {sid}: 读取失败")

# 4. strategy_eq.json
eq = json.load(open("/home/admin/okx_bot/strategy_eq.json"))
print("\n=== strategy_eq.json ===")
for k,v in sorted(eq.items()):
    print(f"  {k}: {v}")

# 5. cooldown.json
cd = json.load(open("/home/admin/okx_bot/cooldown.json"))
import time
now = time.time()
print("\n=== cooldown ===")
for k,v in sorted(cd.items()):
    remaining = max(0, v - now)
    print(f"  {k}: {remaining:.0f}s remaining (until {time.strftime('%H:%M:%S', time.localtime(v))})")

# 6. Check position files vs state.json consistency
print("\n=== 一致性检查 ===")
state_sids = set(tr.get("tranche_id","").split("-")[0] for tr in t)
for tr in t:
    sid = tr["tranche_id"].split("-")[0]
    pf = f"/home/admin/okx_bot/position_{sid}.json"
    try:
        pp = json.load(open(pf))
        if pp.get("position") and pp.get("entry_price") != tr["entry_price"]:
            print(f"  ✗ {sid}: state entry={tr['entry_price']} vs position entry={pp['entry_price']}")
        elif pp.get("position") and pp.get("direction") != tr["direction"]:
            print(f"  ✗ {sid}: state dir={tr['direction']} vs position dir={pp.get('direction')}")
        else:
            print(f"  ✓ {sid}: state 与 position 一致")
    except:
        print(f"  ? {sid}: 无法读取position文件")
