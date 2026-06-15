#!/usr/bin/env python3
"""Fix main.py: last_equity_check must init even when VWAP boot succeeds."""
from pathlib import Path

MAIN = Path("/home/admin/okx_bot/main.py")

OLD = """last_vwap_update = 0; cached_vwap = 0; last_kline_ts = 0
try:
    _boot_vwap = calculate_session_vwap(symbol="BTC/USDT:USDT", timeframe="15m", verbose=False)
    if _boot_vwap > 0:
        cached_vwap = _boot_vwap
        last_vwap_update = time.time()
except Exception:
    pass; last_pos_check = 0; last_equity_check = 0"""

NEW = """last_vwap_update = 0; cached_vwap = 0; last_kline_ts = 0; last_pos_check = 0; last_equity_check = 0
try:
    _boot_vwap = calculate_session_vwap(symbol="BTC/USDT:USDT", timeframe="15m", verbose=False)
    if _boot_vwap > 0:
        cached_vwap = _boot_vwap
        last_vwap_update = time.time()
except Exception:
    pass"""

if __name__ == "__main__":
    text = MAIN.read_text()
    if NEW.strip() not in text:
        if OLD not in text:
            raise SystemExit("anchor missing")
        MAIN.write_text(text.replace(OLD, NEW, 1))
        print("patched main.py boot init")
    else:
        print("already ok")
