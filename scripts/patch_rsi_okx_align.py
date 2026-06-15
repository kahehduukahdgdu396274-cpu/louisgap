#!/usr/bin/env python3
"""Add RSI_LIVE (forming) for OKX panel alignment; RSI (closed) for 009/011/013."""
from pathlib import Path

PATH = Path("/home/admin/okx_bot/indicators.py")
text = PATH.read_text(encoding="utf-8")

OLD = '''    # RSI
    result["RSI"] = _compute_rsi_local(df_calc["close"])
    
    # Stoch RSI'''

NEW = '''    # RSI — 收盘棒供 009/011/013；forming 供 OKX 面板对照
    result["RSI"] = _compute_rsi_local(df_calc["close"])
    result["RSI_LIVE"] = _compute_rsi_local(df["close"])
    
    # Stoch RSI'''

OLD_ALIGN = '            "RSI": result.get("RSI"),'
NEW_ALIGN = '''            "RSI": result.get("RSI"),
            "RSI_LIVE": result.get("RSI_LIVE"),'''

changed = []
if OLD not in text:
    raise SystemExit("RSI block not found — already patched?")
text = text.replace(OLD, NEW, 1)
changed.append("RSI_LIVE in build_snapshot")

if OLD_ALIGN not in text:
    raise SystemExit("align RSI key not found")
text = text.replace(OLD_ALIGN, NEW_ALIGN, 1)
changed.append("RSI_LIVE in align json")

PATH.write_text(text, encoding="utf-8")
print("OK:", ", ".join(changed))
