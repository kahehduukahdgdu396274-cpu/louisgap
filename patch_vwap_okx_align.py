#!/usr/bin/env python3
"""VPS session_vwap.py: 对齐 OKX 日内 VWAP（UTC+8 零点，不含未收盘 K）。"""
from pathlib import Path

VWAP = Path("/home/admin/okx_bot/session_vwap.py")

OLD = '''import ccxt
import numpy as np
from datetime import datetime, timezone, timedelta

def calculate_session_vwap(symbol='BTC/USDT:USDT', timeframe='15m', verbose=True):
    try:
        exchange = ccxt.okx()
        exchange.set_sandbox_mode(True)
        now = datetime.now(timezone.utc)
        start_of_day_utc = now.replace(hour=0, minute=0, second=0, microsecond=0)
        since = int((start_of_day_utc - timedelta(hours=8)).timestamp() * 1000)'''

NEW = '''import ccxt
import numpy as np
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))

def calculate_session_vwap(symbol='BTC/USDT:USDT', timeframe='15m', verbose=True):
    try:
        exchange = ccxt.okx()
        exchange.set_sandbox_mode(True)
        now = datetime.now(CST)
        start_of_session = now.replace(hour=0, minute=0, second=0, microsecond=0)
        since = int(start_of_session.timestamp() * 1000)'''

OLD2 = '''        if not all_ohlcv:
            if verbose: print(f"[VWAP-Audit] Time: {now.strftime('%Y-%m-%d %H:%M')} | WARNING: No candles found")
            return 0.0
        data = np.array(all_ohlcv)'''

NEW2 = '''        if not all_ohlcv:
            if verbose: print(f"[VWAP-Audit] Time: {now.strftime('%Y-%m-%d %H:%M')} | WARNING: No candles found")
            return 0.0
        # OKX 日内 VWAP：会话从 UTC+8 0 点起，不含当前未收盘 K
        if len(all_ohlcv) > 1:
            all_ohlcv = all_ohlcv[:-1]
        data = np.array(all_ohlcv)'''


def main() -> None:
    text = VWAP.read_text()
    for old, new, label in [(OLD, NEW, "cst anchor"), (OLD2, NEW2, "drop forming")]:
        if new.strip() not in text:
            if old not in text:
                raise SystemExit(f"missing: {label}")
            text = text.replace(old, new)
            print(f"patched: {label}")
        else:
            print(f"skip: {label}")
    VWAP.write_text(text)
    print("session_vwap.py OK")


if __name__ == "__main__":
    main()
