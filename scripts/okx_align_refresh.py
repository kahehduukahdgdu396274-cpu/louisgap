#!/usr/bin/env python3
"""独立刷新 okx_indicators_align.json（与 main.py fc() 同源 OKX API，禁止 ccxt 量纲）。"""
import json
import sys

sys.path.insert(0, "/home/admin/okx_bot")

from api import OKXClient
from config import SYMBOL
from indicators import build_snapshot, _write_align_json
from session_vwap import calculate_session_vwap


def fetch_candles(client: OKXClient):
    data = client.request("GET", f"/api/v5/market/candles?instId={SYMBOL}&bar=15m&limit=1000")
    if data.get("code") != "0":
        raise RuntimeError(f"candles API error: {data}")
    candles = data["data"]
    if len(candles) < 50:
        raise RuntimeError("insufficient candles")
    ts = [int(c[0]) for c in candles]
    o = [float(c[1]) for c in candles]
    h = [float(c[2]) for c in candles]
    l = [float(c[3]) for c in candles]
    cl = [float(c[4]) for c in candles]
    v = [float(c[5]) for c in candles]
    ts.reverse()
    o.reverse()
    h.reverse()
    l.reverse()
    cl.reverse()
    v.reverse()
    return o, h, l, cl, v, ts


def main() -> None:
    client = OKXClient()
    ticker = client.fetch_ticker(SYMBOL)
    live = float(ticker["data"][0]["last"])
    o, h, l, cl, v, ts = fetch_candles(client)
    vwap = calculate_session_vwap(verbose=False)
    snap = build_snapshot(o, h, l, cl, v, t=ts, live_price=live, vwap_override=vwap)
    _write_align_json(snap)
    out = "/home/admin/okx_bot/okx_indicators_align.json"
    data = json.load(open(out))
    print(json.dumps({k: data.get(k) for k in [
        "price", "RSI", "RSI_LIVE", "KDJ_K_LIVE", "KDJ_D_LIVE", "KDJ_J_LIVE",
        "SRSI_K", "SRSI_D", "ADX_LIVE", "ATR_LIVE",
        "EMA8", "EMA20_LIVE", "MACD12_HIST", "VWAP", "VOLUME_LIVE",
    ]}, indent=2))


if __name__ == "__main__":
    main()
