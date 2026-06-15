# 全局开关：True=只开多（short信号被强制拦截），False=多空都开
ONLY_LONG = True

def _strong_bull_candle(o, h, l, c, prior_high):
    """强势阳线：实体大、下影短、突破前K高点（参照K线游民关键K线）"""
    body = c - o
    if body <= 0:
        return False
    rng = h - l
    if rng <= 0:
        return False
    lower_wick = o - l
    if lower_wick > body * 0.25:
        return False
    if body < rng * 0.55:
        return False
    return h > prior_high


def _strong_bear_candle(o, h, l, c, prior_low):
    """强势阴线：实体大、上影短、跌破前K低点"""
    body = o - c
    if body <= 0:
        return False
    rng = h - l
    if rng <= 0:
        return False
    upper_wick = h - o
    if upper_wick > body * 0.25:
        return False
    if body < rng * 0.55:
        return False
    return l < prior_low


def _stoch_golden_cross(k, d, prev_k, prev_d, oversold=30):
    return (k > d) and (prev_k <= prev_d) and (k < oversold)


def _stoch_death_cross(k, d, prev_k, prev_d, overbought=70):
    return (k < d) and (prev_k >= prev_d) and (k > overbought)


def _filter_result(result, sid):
    """全局方向过滤：ONLY_LONG 模式下拦截指定策略的空信号。"""
    if result == "short" and ONLY_LONG and sid in ("003", "006"):
        return None
    return result


def check_entry(sid, d):
    close = d['close']
    adx = d['ADX']
    k = d['SRSI_K']
    ema21 = d['EMA21']
    vwap = d['VWAP']
    prev_k = d.get('prev_K', k)
    prev_d = d.get('prev_D', k)
    rsi = d.get('RSI', 50)
    bb_lower = d.get('BB_Lower', 0)
    bb_upper = d.get('BB_Upper', 0)
    atr = d.get('ATR', 0)
    vr = d.get('VR', 1.0)
    ema200 = d.get('EMA200', 0)
    high = d.get('high', close)
    low = d.get('low', close)
    open_p = d.get('open', close)
    if sid == '003':
        ema9_c = d.get('EMA9', 0); ema21_c = d.get('EMA21', 0)
        prev_close = d.get('PREV_CLOSE', close)
        diff = ema9_c - ema21_c
        if abs(diff) < 10:
            return None
        if diff > 0 and (close > ema9_c) and (prev_close > ema9_c) and (close > vwap):
            return 'long'
        return None
    elif sid == '006':
        is_golden = (k > d['SRSI_D']) and (k < 20) and (prev_k <= prev_d)
        if is_golden and (adx >= 20) and (close > vwap):
            return 'long'
        return None
    elif sid == '009':
        if bb_lower <= 0: return None
        if close > bb_lower * 1.006: return None
        return _filter_result('long' if (k < 40 and k > prev_k and rsi < 50) else None, sid)
    elif sid == '010':
        if bb_lower <= 0: return None
        if close > bb_lower * 1.008: return None
        vr_val = d.get('VR', 1.0)
        return _filter_result('long' if (k < 35 and k > prev_k and vr_val > 0.9) else None, sid)
    elif sid == '011':
        if bb_lower <= 0 or atr <= 0: return None
        if close > bb_lower + 0.4 * atr: return None
        if k >= 45 or rsi >= 55: return None
        body_size = abs(close - open_p)
        lower_shadow = min(open_p, close) - low
        return _filter_result('long' if (adx < 40 and lower_shadow > body_size * 0.5) else None, sid)
    elif sid == '012':
        if ema200 <= 0: return None
        near_ema200 = (abs(close - ema200) / ema200 <= 0.018)
        return _filter_result('long' if (near_ema200 and k < 50 and k > prev_k and adx > 18) else None, sid)

    elif sid == '014':
        ema200 = d.get('EMA200') or 0
        if ema200 <= 0:
            return None
        sig_o = d.get('SIG_OPEN', open_p)
        sig_h = d.get('SIG_HIGH', high)
        sig_l = d.get('SIG_LOW', low)
        sig_c = d.get('SIG_CLOSE', close)
        prior_hi = d.get('PRIOR_HIGH', high)
        prior_lo = d.get('PRIOR_LOW', low)
        if _stoch_golden_cross(k, d['SRSI_D'], prev_k, prev_d, oversold=30):
            if sig_c > ema200 and _strong_bull_candle(sig_o, sig_h, sig_l, sig_c, prior_hi):
                if adx >= 15:
                    return 'long'
        if _stoch_death_cross(k, d['SRSI_D'], prev_k, prev_d, overbought=70):
            if sig_c < ema200 and _strong_bear_candle(sig_o, sig_h, sig_l, sig_c, prior_lo):
                if adx >= 15:
                    return _filter_result('short', sid)
        return None
    elif sid == '013':
        ema20 = d.get('EMA20', 0)
        if ema20 <= 0: return None
        if abs(close - ema20) / ema20 >= 0.01: return None
        lower_shadow = min(close, open_p) - low
        body_size = abs(close - open_p)
        return _filter_result('long' if (rsi < 40 and lower_shadow > body_size * 0.3 and adx >= 20) else None, sid)
    return _filter_result(None, sid)

BUFFER_POINTS = 5

def check_exit(sid, d, entry_price, direction='long', position_duration_seconds=99999):
    close = d['close']
    k = d['SRSI_K']
    pnl = (close - entry_price) / entry_price if direction == 'long' else (entry_price - close) / entry_price
    bb_middle = d.get('BB_Middle', 0)
    bb_upper = d.get('BB_Upper', 0)
    prev_k = d.get('prev_K', k)
    if sid == '003':
        if pnl <= -0.01: return True
        if position_duration_seconds < 60:
            return False
        diff = d.get('EMA9',0) - d.get('EMA21',0)
        vwap = d.get('VWAP', 0)
        prev_close = d.get('PREV_CLOSE', close)
        if direction == 'short' and diff >= BUFFER_POINTS:
            if close > vwap and prev_close > vwap:
                return True
        if direction == 'long' and -diff >= BUFFER_POINTS:
            if close < vwap and prev_close < vwap:
                return True
        return False
    elif sid == '006':
        if pnl <= -0.01: return True
        if pnl >= 0.02: return True
        if position_duration_seconds < 60:
            return False
        vwap = d.get('VWAP', 0)
        if direction == 'long' and (k < d['SRSI_D']) and (k > 80):
            return True
        if direction == 'long' and (close < vwap):
            return True
        if direction == 'short' and (k > d['SRSI_D']) and (k < 20):
            return True
        return False
    elif sid in ('009', '010'):
        if pnl <= -0.02: return True
        if position_duration_seconds < 60:
            return False
        if bb_middle > 0 and close >= bb_middle: return True
        breakeven = d.get('breakeven', False)
        if pnl >= 0.008 and not breakeven:
            return False
        if breakeven and pnl <= 0.0:
            return True
        return False
    elif sid == '011':
        if pnl <= -0.02: return True
        if pnl >= 0.02: return True
        if position_duration_seconds < 60:
            return False
        if bb_upper > 0 and close >= bb_upper: return True
        return False
    elif sid == '012':
        if pnl <= -0.02: return True
        if position_duration_seconds < 60:
            return False
        if (pnl >= 0.008) and (k < prev_k): return True
        if bb_upper > 0 and close >= bb_upper: return True
        return False

    elif sid == '014':
        sig_low = d.get('SIG_LOW', 0)
        sig_high = d.get('SIG_HIGH', 0)
        atr = d.get('ATR', 0) or 0
        if direction == 'long':
            if pnl <= -0.018:
                return True
            if sig_low > 0 and close < sig_low:
                return True
            if atr > 0 and close < entry_price - 1.0 * atr:
                return True
            if pnl >= 0.035:
                return True
            if position_duration_seconds < 120:
                return False
            if (k < d['SRSI_D']) and (k > 75):
                return True
        else:
            if pnl <= -0.018:
                return True
            if sig_high > 0 and close > sig_high:
                return True
            if atr > 0 and close > entry_price + 1.0 * atr:
                return True
            if pnl >= 0.035:
                return True
            if position_duration_seconds < 120:
                return False
            if (k > d['SRSI_D']) and (k < 25):
                return True
        return False
    elif sid == '013':
        if pnl <= -0.015: return True
        if pnl >= 0.03: return True
        if position_duration_seconds < 60:
            return False
        if bb_middle > 0 and close >= bb_middle - 0.3 * d.get('ATR', 0):
            pass
        if (pnl >= 0.015) and (k < prev_k): return True
        if bb_upper > 0 and close >= bb_upper: return True
        return False
    return False
