#!/usr/bin/env python3
"""Add KDJ(9,3,3) forming+closed for OKX panel alignment."""
from pathlib import Path

PATH = Path("/home/admin/okx_bot/indicators.py")
text = PATH.read_text(encoding="utf-8")

FUNC = '''

def _compute_kdj_series(df: pd.DataFrame, n: int = 9) -> tuple[float, float, float]:
    """KDJ(9,3,3) — RSV(9); K/D recursive 1/3 smooth; J=3K-2D (OKX 默认)."""
    low_min = df["low"].rolling(window=n, min_periods=n).min()
    high_max = df["high"].rolling(window=n, min_periods=n).max()
    rsv = (df["close"] - low_min) / (high_max - low_min + 1e-8) * 100
    k_prev = d_prev = 50.0
    k_last = d_last = 50.0
    for r in rsv:
        if pd.isna(r):
            continue
        k_last = (2.0 / 3.0) * k_prev + (1.0 / 3.0) * float(r)
        d_last = (2.0 / 3.0) * d_prev + (1.0 / 3.0) * k_last
        k_prev, d_prev = k_last, d_last
    j_last = 3.0 * k_last - 2.0 * d_last
    return round(k_last, 2), round(d_last, 2), round(j_last, 2)
'''

MARKER = "def _compute_adx_local"
if "_compute_kdj_series" not in text:
    if MARKER not in text:
        raise SystemExit("marker not found for KDJ insert")
    text = text.replace(MARKER, FUNC.lstrip("\n") + "\n\n" + MARKER, 1)

OLD = '''    result["RSI_LIVE"] = _compute_rsi_local(df["close"])
    
    # Stoch RSI'''

NEW = '''    result["RSI_LIVE"] = _compute_rsi_local(df["close"])
    kdj_k, kdj_d, kdj_j = _compute_kdj_series(df)
    kdj_k_c, kdj_d_c, kdj_j_c = _compute_kdj_series(df_calc)
    result["KDJ_K_LIVE"] = kdj_k
    result["KDJ_D_LIVE"] = kdj_d
    result["KDJ_J_LIVE"] = kdj_j
    result["KDJ_K"] = kdj_k_c
    result["KDJ_D"] = kdj_d_c
    result["KDJ_J"] = kdj_j_c
    
    # Stoch RSI'''

if OLD not in text:
    raise SystemExit("RSI_LIVE block not found")
text = text.replace(OLD, NEW, 1)

OLD_ALIGN = '            "RSI_LIVE": result.get("RSI_LIVE"),'
NEW_ALIGN = '''            "RSI_LIVE": result.get("RSI_LIVE"),
            "KDJ_K_LIVE": result.get("KDJ_K_LIVE"),
            "KDJ_D_LIVE": result.get("KDJ_D_LIVE"),
            "KDJ_J_LIVE": result.get("KDJ_J_LIVE"),
            "KDJ_K": result.get("KDJ_K"),
            "KDJ_D": result.get("KDJ_D"),
            "KDJ_J": result.get("KDJ_J"),'''

if OLD_ALIGN not in text:
    raise SystemExit("align RSI_LIVE block not found")
text = text.replace(OLD_ALIGN, NEW_ALIGN, 1)

PATH.write_text(text, encoding="utf-8")
print("OK: KDJ(9,3,3) LIVE + closed in indicators.py")
