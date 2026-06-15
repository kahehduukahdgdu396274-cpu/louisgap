import ccxt
import numpy as np
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))

def calculate_session_vwap(symbol='BTC/USDT:USDT', timeframe='15m', verbose=True):
    try:
        exchange = ccxt.okx()
        exchange.set_sandbox_mode(True)
        now = datetime.now(CST)
        start_of_session = now.replace(hour=0, minute=0, second=0, microsecond=0)
        since = int(start_of_session.timestamp() * 1000)
        all_ohlcv = []
        cursor = since
        for _ in range(50):
            chunk = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=cursor, limit=100)
            if not chunk: break
            all_ohlcv.extend(chunk)
            cursor = int(chunk[-1][0]) + 1
            if len(chunk) < 100: break
        if not all_ohlcv:
            if verbose: print(f"[VWAP-Audit] Time: {now.strftime('%Y-%m-%d %H:%M')} | WARNING: No candles found")
            return 0.0
        # OKX 日内 VWAP：会话从 UTC+8 0 点起，不含当前未收盘 K
        if len(all_ohlcv) > 1:
            all_ohlcv = all_ohlcv[:-1]
        data = np.array(all_ohlcv)
        highs = data[:, 2].astype(np.float64)
        lows = data[:, 3].astype(np.float64)
        closes = data[:, 4].astype(np.float64)
        volumes = data[:, 5].astype(np.float64)
        tp = (highs + lows + closes) / 3.0
        cum_pv = np.sum(tp * volumes)
        cum_v = np.sum(volumes)
        vwap = float(cum_pv / cum_v) if cum_v > 0 else 0.0
        if verbose:
            print(f"[VWAP-Audit] Time: {now.strftime('%Y-%m-%d %H:%M')} | CandlesCount: {len(all_ohlcv)} | SumPV: {cum_pv:.6e} | SumV: {cum_v:.6e} | FinalVWAP: {vwap:.1f}")
        return vwap
    except Exception as e:
        print(f"[VWAP-Critical-Error] {e}")
        return 0.0

if __name__ == '__main__':
    print(f'Session VWAP: {calculate_session_vwap():.1f}')
