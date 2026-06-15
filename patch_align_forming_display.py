#!/usr/bin/env python3
"""VPS indicators.py: 对齐 JSON 增加 OKX 图表显示用字段（forming bar + 标准周期）。"""
from pathlib import Path

IND = Path("/home/admin/okx_bot/indicators.py")

ANCHOR_BEFORE_ADX = '    adx_val_x, atr_val_x = _compute_adx_local(df_calc)'
INSERT_ADX = '''    adx_val_x, atr_val_x = _compute_adx_local(df_calc)
    adx_live, atr_live = _compute_adx_local(df)'''

ANCHOR_EMA = '    result["EMA200"] = _compute_ema_local(df_calc["close"], 200) if len(df_calc) >= 200 else 0'
INSERT_EMA = '''    result["EMA200"] = _compute_ema_local(df_calc["close"], 200) if len(df_calc) >= 200 else 0
    # OKX 图表对照（forming bar + 常见图表周期）
    result["EMA8"] = _compute_ema_local(df["close"], 8)
    result["EMA20_LIVE"] = _compute_ema_local(df["close"], 20)
    result["EMA129"] = _compute_ema_local(df["close"], 129) if len(df) >= 129 else None
    result["ADX_LIVE"] = adx_live
    result["ATR_LIVE"] = atr_live'''

ANCHOR_MACD = '    result.update(_compute_macd_local(df_calc))'
INSERT_MACD = '''    result.update(_compute_macd_local(df_calc))
    # OKX 默认 MACD(12,26,9) 对照
    _c = df["close"]
    _ef = _c.ewm(span=12, adjust=False).mean()
    _es = _c.ewm(span=26, adjust=False).mean()
    _ml = _ef - _es
    _sig = _ml.ewm(span=9, adjust=False).mean()
    result["MACD12"] = round(float(_ml.iloc[-1]), 4)
    result["MACD12_SIGNAL"] = round(float(_sig.iloc[-1]), 4)
    result["MACD12_HIST"] = round(float((_ml - _sig).iloc[-1]), 4)'''

OLD_ALIGN = '''            "EMA9": result.get("EMA9"),
            "EMA21": result.get("EMA21"),
            "updated_ms": result.get("timestamp"),
        }'''

NEW_ALIGN = '''            "EMA9": result.get("EMA9"),
            "EMA21": result.get("EMA21"),
            "EMA8": result.get("EMA8"),
            "EMA20_LIVE": result.get("EMA20_LIVE"),
            "EMA129": result.get("EMA129"),
            "ADX_LIVE": result.get("ADX_LIVE"),
            "ATR_LIVE": result.get("ATR_LIVE"),
            "MACD12": result.get("MACD12"),
            "MACD12_SIGNAL": result.get("MACD12_SIGNAL"),
            "MACD12_HIST": result.get("MACD12_HIST"),
            "updated_ms": result.get("timestamp"),
        }'''


def main() -> None:
    text = IND.read_text()
    for old, new, label in [
        (ANCHOR_BEFORE_ADX, INSERT_ADX, "adx/atr live"),
        (ANCHOR_EMA, INSERT_EMA, "ema okx ref"),
        (ANCHOR_MACD, INSERT_MACD, "macd12"),
        (OLD_ALIGN, NEW_ALIGN, "align json"),
    ]:
        if new.strip() not in text:
            if old not in text:
                raise SystemExit(f"missing anchor: {label}")
            text = text.replace(old, new, 1)
            print(f"patched: {label}")
        else:
            print(f"skip: {label}")
    IND.write_text(text)
    print("indicators.py OK")


if __name__ == "__main__":
    main()
