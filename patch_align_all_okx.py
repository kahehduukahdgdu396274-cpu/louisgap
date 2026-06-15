#!/usr/bin/env python3
"""VPS 全面对齐 OKX 桌面所有指标：live 价、VWAP、Volume、align JSON 重写。"""
from pathlib import Path

IND = Path("/home/admin/okx_bot/indicators.py")
MAIN = Path("/home/admin/okx_bot/main.py")

# --- indicators.py: build_snapshot 签名 + live 价 + volume ---
IND_OLD_SIG = "def build_snapshot(o, h, l, c, v, t=None):"
IND_NEW_SIG = "def build_snapshot(o, h, l, c, v, t=None, live_price=None, vwap_override=None):"

IND_OLD_DF = "    t0 = time.time(); df = pd.DataFrame({\"open\": o, \"high\": h, \"low\": l, \"close\": c, \"vol\": v})\n    price = c[-1]"
IND_NEW_DF = """    t0 = time.time(); df = pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "vol": v})
    price = float(live_price) if live_price is not None else c[-1]
    if live_price is not None and len(df) > 0:
        df = df.copy()
        df.iloc[-1, df.columns.get_loc("close")] = price
        df.iloc[-1, df.columns.get_loc("high")] = max(float(df.iloc[-1]["high"]), price)
        df.iloc[-1, df.columns.get_loc("low")] = min(float(df.iloc[-1]["low"]), price)"""

IND_OLD_VWAP = """    vwap_val = None
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
        result["VWAP_SOURCE"] = "local_fallback\""""

IND_NEW_VWAP = """    if vwap_override and vwap_override > 0:
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
            result["VWAP_SOURCE"] = "local_fallback\""""

IND_OLD_ALIGN_END = """            "MACD12_HIST": result.get("MACD12_HIST"),
            "updated_ms": result.get("timestamp"),
        }"""

IND_NEW_ALIGN_END = """            "MACD12_HIST": result.get("MACD12_HIST"),
            "VOLUME_LIVE": result.get("VOLUME_LIVE"),
            "price_live": result.get("price_live"),
            "updated_ms": result.get("timestamp"),
        }"""

IND_OLD_MACD_BLOCK = """    result["MACD12_HIST"] = round(float((_ml - _sig).iloc[-1]), 4)
    bb = _compute_bb_local(df_calc)"""

IND_NEW_MACD_BLOCK = """    result["MACD12_HIST"] = round(float((_ml - _sig).iloc[-1]), 4)
    result["VOLUME_LIVE"] = round(float(df.iloc[-1]["vol"]), 2) if len(df) else 0
    result["price_live"] = round(float(price), 2)
    bb = _compute_bb_local(df_calc)"""

IND_OLD_WRITE = "    _write_align_json(result)\n    logger.info"
IND_NEW_WRITE = "    logger.info"

# --- main.py: 价格先行 + VWAP 初始化 + align 重写 ---
MAIN_OLD_LOOP = """        o, h, l, c, v, ts = r
        snap = build_snapshot(o, h, l, c, v, t=ts)
        ct = time.time()

        # VWAP
        if ct - last_vwap_update > 60:
            try:
                new_vwap = calculate_session_vwap(symbol="BTC/USDT:USDT", timeframe="15m")
                if new_vwap > 0:
                    cached_vwap = new_vwap
                    last_vwap_update = ct
                else:
                    logger.warning(f"VWAP返回零值({new_vwap}), 保留旧值: {cached_vwap:.0f}")
            except Exception as e:
                logger.warning(f"VWAP计算失败: {e}")
        snap["VWAP"] = cached_vwap
        kt = int(ct) // 900 * 900; snap["new_kline"] = kt != last_kline_ts; last_kline_ts = kt

        # WS实时价格
        with ws_price_lock:
            lw = ws_latest_price
            wt = ws_last_time
        if wt > 0 and ct - wt < WS_STALE_SECS:
            price = lw
            price_src = "WS"
        else:
            stale_secs = int(ct - wt) if wt > 0 else -1
            logger.warning(f"WS僵死{stale_secs}秒, 触发实时REST兜底")
            try:
                res = client.fetch_ticker("BTC-USDT-SWAP")
                rest_price = float(res["data"][0]["last"])
                with ws_price_lock:
                    ws_last_time = ct - (WS_STALE_SECS - 5)
                price = rest_price
                price_src = "REST"
            except Exception as e:
                logger.warning(f"实时REST也挂了({e}), 读取本地快照")
                price = snap["close"]
                price_src = "SNAP\""""

MAIN_NEW_LOOP = """        o, h, l, c, v, ts = r
        ct = time.time()

        # WS实时价格（先于指标快照，供 forming 棒对齐 OKX）
        with ws_price_lock:
            lw = ws_latest_price
            wt = ws_last_time
        if wt > 0 and ct - wt < WS_STALE_SECS:
            price = lw
            price_src = "WS"
        else:
            stale_secs = int(ct - wt) if wt > 0 else -1
            logger.warning(f"WS僵死{stale_secs}秒, 触发实时REST兜底")
            try:
                res = client.fetch_ticker("BTC-USDT-SWAP")
                rest_price = float(res["data"][0]["last"])
                with ws_price_lock:
                    ws_last_time = ct - (WS_STALE_SECS - 5)
                price = rest_price
                price_src = "REST"
            except Exception as e:
                logger.warning(f"实时REST也挂了({e}), 使用K线收盘价")
                price = c[-1]
                price_src = "SNAP"

        # VWAP（60s 缓存，UTC+8 零点会话）
        if ct - last_vwap_update > 60 or cached_vwap <= 0:
            try:
                new_vwap = calculate_session_vwap(symbol="BTC/USDT:USDT", timeframe="15m", verbose=False)
                if new_vwap > 0:
                    cached_vwap = new_vwap
                    last_vwap_update = ct
            except Exception as e:
                logger.warning(f"VWAP计算失败: {e}")

        snap = build_snapshot(o, h, l, c, v, t=ts, live_price=price, vwap_override=cached_vwap)
        from indicators import _write_align_json
        _write_align_json(snap)
        kt = int(ct) // 900 * 900; snap["new_kline"] = kt != last_kline_ts; last_kline_ts = kt"""

MAIN_OLD_INIT = "last_vwap_update = 0; cached_vwap = 0; last_kline_ts = 0"
MAIN_NEW_INIT = """last_vwap_update = 0; cached_vwap = 0; last_kline_ts = 0
try:
    _boot_vwap = calculate_session_vwap(symbol="BTC/USDT:USDT", timeframe="15m", verbose=False)
    if _boot_vwap > 0:
        cached_vwap = _boot_vwap
        last_vwap_update = time.time()
except Exception:
    pass"""


def patch_file(path: Path, pairs: list) -> None:
    text = path.read_text()
    for old, new, label in pairs:
        if new.strip() not in text:
            if old not in text:
                raise SystemExit(f"{path.name}: missing anchor {label}")
            text = text.replace(old, new, 1)
            print(f"  patched {path.name}: {label}")
        else:
            print(f"  skip {path.name}: {label}")
    path.write_text(text)


def main() -> None:
    print("=== patch indicators.py ===")
    patch_file(IND, [
        (IND_OLD_SIG, IND_NEW_SIG, "signature"),
        (IND_OLD_DF, IND_NEW_DF, "live_price df"),
        (IND_OLD_VWAP, IND_NEW_VWAP, "vwap_override"),
        (IND_OLD_MACD_BLOCK, IND_NEW_MACD_BLOCK, "volume_live"),
        (IND_OLD_ALIGN_END, IND_NEW_ALIGN_END, "align volume"),
        (IND_OLD_WRITE, IND_NEW_WRITE, "defer align write"),
    ])
    print("=== patch main.py ===")
    patch_file(MAIN, [
        (MAIN_OLD_INIT, MAIN_NEW_INIT, "vwap boot"),
        (MAIN_OLD_LOOP, MAIN_NEW_LOOP, "loop reorder"),
    ])
    print("ALL OK")


if __name__ == "__main__":
    main()
