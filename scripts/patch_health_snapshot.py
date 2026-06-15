#!/usr/bin/env python3
"""Patch health_snapshot.py: don't let historic criticals override healthy state."""
import sys

with open("/home/admin/okx_bot/scripts/health_snapshot.py", "r") as f:
    src = f.read()

old = """    crit = _critical_count_24h()
    if crit > 0:
        status = "critical\""""

new = """    crit = _critical_count_24h()
    # 历史critical告警不覆盖当前健康状态（三源一致+运行中就不算critical）
    if crit > 0 and status not in ("holding_ok", "idle_ok"):
        status = "critical\""""

if old in src:
    src = src.replace(old, new, 1)
    with open("/home/admin/okx_bot/scripts/health_snapshot.py", "w") as f:
        f.write(src)
    print("✓ health_snapshot.py patched")
else:
    print("✗ block not found")
    sys.exit(1)
