#!/usr/bin/env python3
import time, json, logging, hmac, base64
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import traceback
import requests, pandas as pd, numpy as np

try:
    from config import API_KEY, SECRET_KEY, PASSPHRASE, SYMBOL
except ImportError:
    SYMBOL = "BTC-USDT-SWAP"
    API_KEY = SECRET_KEY = PASSPHRASE = ""

try:
    from session_vwap import calculate_session_vwap
except ImportError:
    calculate_session_vwap = None

logger = logging.getLogger(__name__)
BASE_URL = "https://openapi.okx.com"; REQUEST_TIMEOUT = 5
BTC_SWAP = "BTC-USDT-SWAP"; BTC_SPOT = "BTC-USDT"

def _sign_request(method: str, request_path: str, body: str = "") -> Dict[str, str]:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    msg = ts + method.upper() + request_path + body
    mac = hmac.new(bytes(SECRET_KEY, "utf-8"), bytes(msg, "utf-8"), digestmod="sha256")
    dgst = base64.b64encode(mac.digest()).decode("utf-8")
    return {"OK-ACCESS-KEY": API_KEY, "OK-ACCESS-SIGN": dgst, "OK-ACCESS-TIMESTAMP": ts, "OK-ACCESS-PASSPHRASE": PASSPHRASE, "Content-Type": "application/json"}


def _compute_rsi_local(series: pd.Series, period: int = 14) -> float:
    delta = series.diff()
    gain, loss = delta.where(delta > 0, 0.0), -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    for i in range(period, len(avg_gain)):
        avg_gain.iloc[i] = (avg_gain.iloc[i - 1] * (period - 1) + gain.iloc[i]) / period
        avg_loss.iloc[i] = (avg_loss.iloc[i - 1] * (period - 1) + loss.iloc[i]) / period
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return round(rsi.iloc[-1], 2) if not pd.isna(rsi.iloc[-1]) else 50.0

def _compute_stochrsi_local(series: pd.Series, rsi_period: int = 14, stoch_period: int = 14, k_period: int = 3, d_period: int = 3):
    """最终优化版 Stoch RSI (14,14,3,3) - 更接近OKX App"""
    if len(series) < 40:
        return 50.0, 50.0

    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)

    ma_up = up.ewm(alpha=1.0/rsi_period, adjust=False).mean()
    ma_down = down.ewm(alpha=1.0/rsi_period, adjust=False).mean()

    rs = ma_up / ma_down
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi = rsi.fillna(50.0).clip(0, 100)

    rsi_min = rsi.rolling(window=stoch_period, min_periods=rsi_period).min()
    rsi_max = rsi.rolling(window=stoch_period, min_periods=rsi_period).max()

    stoch = (rsi - rsi_min) / (rsi_max - rsi_min + 1e-8) * 100
    stoch = stoch.fillna(50.0).clip(0, 100)

    # K/D: SMA(3) — OKX App StochRSI(14,14,3,3) 标准算法
    K = stoch.rolling(window=k_period, min_periods=k_period).mean()
    D = K.rolling(window=d_period, min_periods=d_period).mean()

    k_val = round(K.iloc[-1], 2) if not pd.isna(K.iloc[-1]) else 50.0
    d_val = round(D.iloc[-1], 2) if not pd.isna(D.iloc[-1]) else 50.0
    return k_val, d_val

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


def _compute_adx_local(df: pd.DataFrame, period: int = 14) -> float:
    """本地ADX - Wilder平滑版，对齐OKX App"""
    high, low, close = df["high"].values, df["low"].values, df["close"].values
    n = len(close)
    tr = np.zeros(n)
    pdm = np.zeros(n)
    ndm = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1]))
        up = high[i]-high[i-1]
        dn = low[i-1]-low[i]
        if up > dn and up > 0: pdm[i] = up
        if dn > up and dn > 0: ndm[i] = dn
    
    atr = np.zeros(n); pdi_s = np.zeros(n); ndi_s = np.zeros(n)
    atr[period] = np.mean(tr[1:period+1])
    pdi_s[period] = np.mean(pdm[1:period+1])
    ndi_s[period] = np.mean(ndm[1:period+1])
    for i in range(period+1, n):
        atr[i] = (atr[i-1]*(period-1)+tr[i])/period
        pdi_s[i] = (pdi_s[i-1]*(period-1)+pdm[i])/period
        ndi_s[i] = (ndi_s[i-1]*(period-1)+ndm[i])/period
    
    pdi = 100 * pdi_s / np.where(atr==0, 1, atr)
    ndi = 100 * ndi_s / np.where(atr==0, 1, atr)
    dx = 100 * np.abs(pdi-ndi) / np.where(pdi+ndi==0, 1, pdi+ndi)
    
    adx = np.zeros(n)
    adx[period*2-1] = np.mean(dx[period:period*2])
    for i in range(period*2, n):
        adx[i] = (adx[i-1]*(period-1)+dx[i])/period
    val = adx[-1]
    atr_val = atr[-1]
    return (round(val, 2) if not np.isnan(val) else 0.0,
            round(atr_val, 2) if not np.isnan(atr_val) else 0.0)

def _compute_ema_local(series: pd.Series, period: int) -> Optional[float]:
    return round(series.ewm(span=period, adjust=False).mean().iloc[-1], 2) if len(series) >= period else None

def _compute_macd_local(df: pd.DataFrame) -> Dict[str, float]:
    close = df["close"]; ef = close.ewm(span=8, adjust=False).mean(); es = close.ewm(span=17, adjust=False).mean()
    ml = ef - es; sig = ml.ewm(span=9, adjust=False).mean()
    return {"MACD": round(ml.iloc[-1], 4), "MACD_SIGNAL": round(sig.iloc[-1], 4), "MACD_HISTOGRAM": round((ml - sig).iloc[-1], 4)}

def _compute_bb_local(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0) -> Dict[str, float]:
    close = df["close"]; sma = close.rolling(window=period, min_periods=period).mean(); std = close.rolling(window=period, min_periods=period).std()
    u, l = sma + std_dev * std, sma - std_dev * std
    curr = close.iloc[-1]
    return {"BB_UPPER": round(u.iloc[-1], 2), "BB_MIDDLE": round(sma.iloc[-1], 2), "BB_LOWER": round(l.iloc[-1], 2), "BB_BANDWIDTH": round((u.iloc[-1] - l.iloc[-1]) / sma.iloc[-1] * 100, 2), "BB_POSITION_PCT": round((curr - l.iloc[-1]) / (u.iloc[-1] - l.iloc[-1]) * 100, 2)}

def _compute_vwap_local(df: pd.DataFrame) -> float:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    pv = tp * df["vol"]
    return round(pv.sum() / df["vol"].sum(), 2) if df["vol"].sum() > 0 else df["close"].iloc[-1]



def _df_closed(df: pd.DataFrame) -> pd.DataFrame:
    """Use last closed 15m bar only (drop forming bar) — matches OKX App display."""
    return df.iloc[:-1] if len(df) > 1 else df


def _write_align_json(result: dict) -> None:
    try:
        payload = {
            "instId": SYMBOL,
            "bar": "15m",
            "env": "demo",
            "source": result.get("source"),
            "bar_ts": result.get("bar_ts"),
            "price": result.get("price"),
            "ADX": result.get("ADX"),
            "ATR": result.get("ATR"),
            "RSI": result.get("RSI"),
            "RSI_LIVE": result.get("RSI_LIVE"),
            "KDJ_K_LIVE": result.get("KDJ_K_LIVE"),
            "KDJ_D_LIVE": result.get("KDJ_D_LIVE"),
            "KDJ_J_LIVE": result.get("KDJ_J_LIVE"),
            "KDJ_K": result.get("KDJ_K"),
            "KDJ_D": result.get("KDJ_D"),
            "KDJ_J": result.get("KDJ_J"),
            "SRSI_K": result.get("SRSI_K"),
            "SRSI_D": result.get("SRSI_D"),
            "SRSI_K_CLOSED": result.get("SRSI_K_CLOSED"),
            "SRSI_D_CLOSED": result.get("SRSI_D_CLOSED"),
            "bar_ts_closed": result.get("bar_ts_closed"),
            "VWAP": result.get("VWAP"),
            "VWAP_SOURCE": result.get("VWAP_SOURCE"),
            "EMA9": result.get("EMA9"),
            "EMA21": result.get("EMA21"),
            "EMA8": result.get("EMA8"),
            "EMA20_LIVE": result.get("EMA20_LIVE"),
            "ADX_LIVE": result.get("ADX_LIVE"),
            "ATR_LIVE": result.get("ATR_LIVE"),
            "MACD12": result.get("MACD12"),
            "MACD12_SIGNAL": result.get("MACD12_SIGNAL"),
            "MACD12_HIST": result.get("MACD12_HIST"),
            "VOLUME_LIVE": result.get("VOLUME_LIVE"),
            "price_live": result.get("price_live"),
            "updated_ms": result.get("timestamp"),
        }
        with open("/home/admin/okx_bot/okx_indicators_align.json", "w") as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception as e:
        logger.debug("align json write failed: %s", e)

def build_snapshot(o, h, l, c, v, t=None, live_price=None, vwap_override=None):
    t0 = time.time(); df = pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "vol": v})
    display_price = float(live_price) if live_price is not None else c[-1]
    # forming 指标用原始 K 线；勿用 WS 价覆写 df（会破坏已与 OKX 对齐的读数）
    result = {"timestamp": int(t0 * 1000), "price": display_price, "close": display_price, "source": "demo_swap_closed_bar", "instId": SYMBOL, "bar": "15m"}
    df_calc = _df_closed(df)
    if t:
        result["bar_ts"] = int(t[-1])
        result["bar_ts_closed"] = int(t[-2]) if len(t) >= 2 else int(t[-1])
    candle_count = len(df_calc)
    if candle_count < 28:
        logger.warning(f"Candle count low for ADX: {candle_count}")
    
    # ADX + ATR（纯本地计算，禁止用实盘API）
    adx_val_x, atr_val_x = _compute_adx_local(df_calc)
    adx_live, atr_live = _compute_adx_local(df)
    result["ADX"] = adx_val_x
    result["ATR"] = atr_val_x
    
    # RSI — 收盘棒供 009/011/013；forming 供 OKX 面板对照
    result["RSI"] = _compute_rsi_local(df_calc["close"])
    result["RSI_LIVE"] = _compute_rsi_local(df["close"])
    kdj_k, kdj_d, kdj_j = _compute_kdj_series(df)
    kdj_k_c, kdj_d_c, kdj_j_c = _compute_kdj_series(df_calc)
    result["KDJ_K_LIVE"] = kdj_k
    result["KDJ_D_LIVE"] = kdj_d
    result["KDJ_J_LIVE"] = kdj_j
    result["KDJ_K"] = kdj_k_c
    result["KDJ_D"] = kdj_d_c
    result["KDJ_J"] = kdj_j_c
    
    # Stoch RSI — OKX App 显示当前K线(含未收盘)的 SMA StochRSI
    srsi_k, srsi_d = _compute_stochrsi_local(df["close"])
    result["SRSI_K"] = srsi_k
    result["SRSI_D"] = srsi_d
    k_closed, d_closed = _compute_stochrsi_local(df_calc["close"])
    result["SRSI_K_CLOSED"] = k_closed
    result["SRSI_D_CLOSED"] = d_closed
    
    # 当前K线(未收盘)指标
    result["EMA9"] = _compute_ema_local(df_calc["close"], 9)
    result["EMA20"] = _compute_ema_local(df_calc["close"], 20)
    result["EMA21"] = _compute_ema_local(df_calc["close"], 21)
    result["EMA50"] = _compute_ema_local(df_calc["close"], 50)
    result["EMA200"] = _compute_ema_local(df_calc["close"], 200) if len(df_calc) >= 200 else 0
    # OKX 图表对照（forming bar + 常见图表周期）
    result["EMA8"] = _compute_ema_local(df["close"], 8)
    result["EMA20_LIVE"] = _compute_ema_local(df["close"], 20)
    result["ADX_LIVE"] = adx_live
    result["ATR_LIVE"] = atr_live
    if len(df_calc) >= 2:
        sig = df_calc.iloc[-1]
        pri = df_calc.iloc[-2]
        result["SIG_OPEN"] = round(float(sig["open"]), 2)
        result["SIG_HIGH"] = round(float(sig["high"]), 2)
        result["SIG_LOW"] = round(float(sig["low"]), 2)
        result["SIG_CLOSE"] = round(float(sig["close"]), 2)
        result["PRIOR_HIGH"] = round(float(pri["high"]), 2)
        result["PRIOR_LOW"] = round(float(pri["low"]), 2)
    else:
        result["SIG_OPEN"] = result["open"]
        result["SIG_HIGH"] = result["high"]
        result["SIG_LOW"] = result["low"]
        result["SIG_CLOSE"] = result["close"]
        result["PRIOR_HIGH"] = result["high"]
        result["PRIOR_LOW"] = result["low"]

    # 上一根已收盘K线指标 (用于new_kline收线确认)
    if len(df) >= 2:
        result["PREV_CLOSE"] = round(float(c[-2]), 2)
        prev_df = df.iloc[:-1]
        result["PREV_EMA9"] = _compute_ema_local(prev_df["close"], 9)
        result["PREV_EMA21"] = _compute_ema_local(prev_df["close"], 21)
    else:
        result["PREV_CLOSE"] = result["close"]
        result["PREV_EMA9"] = result["EMA9"]
        result["PREV_EMA21"] = result["EMA21"]
    result["EMA60"] = _compute_ema_local(df["close"], 60) if len(c) >= 60 else result.get("EMA50", 0)
    result["recent_high_20"] = round(float(max(c[-20:])), 2) if len(c) >= 20 else c[-1]
    result["recent_low_20"] = round(float(min(c[-20:])), 2) if len(c) >= 20 else c[-1]
    # v5.9: 补齐OHLC + volume + prev_RSI + VR
    result["open"] = o[-1] if len(o) > 0 else c[-1]
    result["high"] = h[-1] if len(h) > 0 else c[-1]
    result["low"] = l[-1] if len(l) > 0 else c[-1]
    result["volume"] = v[-1] if len(v) > 0 else 0
    result["prev_RSI"] = result.get("RSI", 50)
    result["prev_high"] = result.get("recent_high_20", c[-1])
    # VR: 当前量 / 前5根均量
    if len(c) >= 6:
        avg_vol = sum(v[-6:-1]) / 5.0
        result["VR"] = round(v[-1] / avg_vol, 2) if avg_vol > 0 else 1.0
    else:
        result["VR"] = 1.0
    if vwap_override and vwap_override > 0:
        result["VWAP"] = round(float(vwap_override), 2)
        result["VWAP_SOURCE"] = "session_ccxt_demo"
    else:
        vwap_val = None
        if calculate_session_vwap:
            try:
                vwap_val = calculate_session_vwap(symbol="BTC/USDT:USDT", timeframe="15m", verbose=False)
            except Exception as e:
                logger.warning(f"session VWAP failed: {e}")
        if vwap_val and vwap_val > 0:
            result["VWAP"] = round(float(vwap_val), 2)
            result["VWAP_SOURCE"] = "session_ccxt_demo"
        else:
            result["VWAP"] = _compute_vwap_local(df_calc)
            result["VWAP_SOURCE"] = "local_fallback"
    result.update(_compute_macd_local(df_calc))
    # OKX 默认 MACD(12,26,9) 对照
    _c = df["close"]
    _ef = _c.ewm(span=12, adjust=False).mean()
    _es = _c.ewm(span=26, adjust=False).mean()
    _ml = _ef - _es
    _sig = _ml.ewm(span=9, adjust=False).mean()
    result["MACD12"] = round(float(_ml.iloc[-1]), 4)
    result["MACD12_SIGNAL"] = round(float(_sig.iloc[-1]), 4)
    result["MACD12_HIST"] = round(float((_ml - _sig).iloc[-1]), 4)
    result["VOLUME_LIVE"] = round(float(df.iloc[-1]["vol"]), 2) if len(df) else 0
    result["price_live"] = round(float(display_price), 2)
    bb = _compute_bb_local(df_calc)
    result.update(bb)
    result.update({
        "BB_Upper": bb.get("BB_UPPER", 0),
        "BB_Middle": bb.get("BB_MIDDLE", 0),
        "BB_Lower": bb.get("BB_LOWER", 0),
        "BB_Bandwidth": bb.get("BB_BANDWIDTH", 0),
        "BB_Position_Pct": bb.get("BB_POSITION_PCT", 0),
    })
    
    logger.info(f"[snapshot] inst={SYMBOL} bar_ts={result.get('bar_ts')} source={result['source']} price={display_price:.0f} ADX={result['ADX']:.2f} RSI={result['RSI']:.1f} ATR={result.get('ATR', 0):.2f} MACD={result.get('MACD', 0):.4f}/{result.get('MACD_SIGNAL', 0):.4f}/{result.get('MACD_HISTOGRAM', 0):.4f} EMA9={result.get('EMA9', 0):.0f} EMA21={result.get('EMA21', 0):.0f} VWAP={result.get('VWAP', 0):.0f} ({time.time()-t0:.2f}s)")
    return result