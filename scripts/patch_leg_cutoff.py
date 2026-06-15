#!/usr/bin/env python3
"""Patch merge_okx_legs_into_state to respect close_time cutoff (only keep legs closed on or after 2026-06-15)."""
import datetime, time

with open("/home/admin/okx_bot/build_war_report.py", "r") as f:
    src = f.read()

# 6月15日 00:00:00 CST 的时间戳
cutoff_ts = datetime.datetime(2026, 6, 15, 0, 0, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=8))).timestamp()

old_block = '''    okx_by_close = {(l.get("close_ord_id") or "").strip(): l for l in okx_legs}
    out, replaced = [], 0
    seen_close = set()
    for leg in legs:
        cid = (leg.get("close_ord_id") or "").strip()
        if cid in okx_by_close:
            if cid not in seen_close:
                out.append(okx_by_close[cid])
                seen_close.add(cid)
                replaced += 1
            continue
        out.append(leg)
    for cid, leg in okx_by_close.items():
        if cid not in seen_close:
            out.append(leg)
            replaced += 1
    out.sort(key=lambda x: float(x.get("close_time", 0) or 0))
    return out, replaced'''

new_block = f'''    okx_by_close = {{(l.get("close_ord_id") or "").strip(): l for l in okx_legs}}
    out, replaced = [], 0
    seen_close = set()
    for leg in legs:
        cid = (leg.get("close_ord_id") or "").strip()
        if cid in okx_by_close:
            if cid not in seen_close:
                out.append(okx_by_close[cid])
                seen_close.add(cid)
                replaced += 1
            continue
        out.append(leg)
    for cid, leg in okx_by_close.items():
        if cid not in seen_close:
            # 硬性截断：禁止回填6月15日之前的leg
            ct = float(leg.get("close_time", 0) or 0)
            if ct >= {cutoff_ts}:
                out.append(leg)
                replaced += 1
    out.sort(key=lambda x: float(x.get("close_time", 0) or 0))
    return out, replaced'''

if old_block in src:
    src = src.replace(old_block, new_block, 1)
    with open("/home/admin/okx_bot/build_war_report.py", "w") as f:
        f.write(src)
    print(f"✓ build_war_report.py patched: close_time cutoff >= {cutoff_ts} (2026-06-15 CST)")
else:
    print("✗ old block not found")
    import sys
    sys.exit(1)
