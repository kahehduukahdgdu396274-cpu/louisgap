"""
trade_logger — v6: 平仓后从OKX fillPnl字段获取真实盈亏，写入trades_history.csv
"""
import csv, os, time, json
import requests, hmac, hashlib, base64
from datetime import datetime

CSV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trades_history.csv")
CSV_HEADERS = ["strategy","action","entry_price","exit_price","sz","fillPnl","fee","exit_time","ordId","fillPx"]


_client_cache = None

def _get_client():
    global _client_cache
    if _client_cache is None:
        from api import OKXClient
        _client_cache = OKXClient()
    return _client_cache


def _ensure_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="") as f:
            csv.writer(f).writerow(CSV_HEADERS)


def record_exit(strategy_id, ord_id, inst_id="BTC-USDT-SWAP"):
    """
    平仓后立即调用：从OKX trade fills拉取成交明细，用ordId匹配fillPnl，写入CSV。
    重试3次，每次间隔2秒，确保订单已结算。
    """
    _ensure_csv()
    client = _get_client()
    exit_fill = None

    for attempt in range(3):
        path = f"/api/v5/trade/fills?instId={inst_id}&limit=10"
        data = client.request("GET", path)
        if data.get("code") != "0" or not data.get("data"):
            time.sleep(2)
            continue
        for fill in data["data"]:
            if fill.get("ordId") == ord_id and fill.get("subType") == "2":
                exit_fill = fill
                break
        if exit_fill:
            break
        time.sleep(2)


def fetch_entry_avg_price(ord_id, inst_id="BTC-USDT-SWAP"):
    """
    开仓后调用：从OKX trade fills按ordId匹配subType=1（开仓）的成交，
    返回实际成交均价 avgPx = Σ(fillPx * fillSz) / Σ(fillSz)
    重试3次，每次2秒。
    """
    client = _get_client()
    for attempt in range(3):
        path = f"/api/v5/trade/fills?instId={inst_id}&limit=10"
        data = client.request("GET", path)
        if data.get("code") != "0" or not data.get("data"):
            time.sleep(2)
            continue
        fills = [f for f in data["data"] if f.get("ordId") == ord_id and f.get("subType") == "1"]
        if fills:
            total_sz = sum(float(f["fillSz"]) for f in fills)
            total_px = sum(float(f["fillPx"]) * float(f["fillSz"]) for f in fills)
            return round(total_px / total_sz, 2) if total_sz > 0 else 0.0
        time.sleep(2)
    return 0.0

    if not exit_fill:
        print(f"[trade_logger] ⚠️ {strategy_id} ordId={ord_id} 未匹配到平仓记录")
        return None

    fill_pnl = float(exit_fill.get("fillPnl", 0))
    exit_price = float(exit_fill["fillPx"])
    sz = float(exit_fill["fillSz"])
    fee = float(exit_fill.get("fee", 0))

    # 从 DB 读 entry_price
    entry_price = 0.0
    try:
        import sqlite3
        db = sqlite3.connect(os.path.join(os.path.dirname(os.path.abspath(__file__)), "hermes_trades.db"))
        cur = db.execute(
            "SELECT price FROM trades WHERE strategy=? AND action IN ('BUY','BUY_SIM') ORDER BY id DESC LIMIT 1",
            (strategy_id,)
        )
        row = cur.fetchone()
        if row:
            entry_price = row[0]
        db.close()
    except Exception as e:
        print(f"[trade_logger] DB读entry_price失败: {e}")

    exit_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(CSV_FILE, "a", newline="") as f:
        csv.writer(f).writerow([
            strategy_id, "SELL",
            f"{entry_price:.1f}", f"{exit_price:.1f}",
            sz, f"{fill_pnl:.2f}", f"{fee:.2f}",
            exit_time, ord_id, exit_price,
        ])

    print(f"[trade_logger] ✅ {strategy_id} fillPnl={fill_pnl:.2f} USDT → trades_history.csv")
    return {"strategy": strategy_id, "fillPnl": fill_pnl, "exitPrice": exit_price, "sz": sz}


def generate_report():
    """从trades_history.csv读取记录生成战报摘要"""
    _ensure_csv()
    trades = []
    try:
        with open(CSV_FILE, "r") as f:
            for row in csv.DictReader(f):
                trades.append(row)
    except Exception as e:
        print(f"[trade_logger] CSV读取失败: {e}")
        return None

    if not trades:
        print("[trade_logger] trades_history.csv 为空")
        return None

    from collections import defaultdict
    by_strategy = defaultdict(list)
    for t in trades:
        by_strategy[t["strategy"]].append(t)

    report = []
    total_pnl = 0.0
    for sid in sorted(by_strategy.keys()):
        ts = by_strategy[sid]
        name = {"006": "A类-超卖反弹", "003": "B类-趋势延续"}.get(sid, sid)
        pnl = sum(float(t.get("fillPnl", 0)) for t in ts)
        wins = sum(1 for t in ts if float(t.get("fillPnl", 0)) > 0)
        total_pnl += pnl
        report.append({"strategy": sid, "name": name, "trades": len(ts),
                        "wins": wins, "win_rate": f"{wins/len(ts)*100:.1f}%" if ts else "0%",
                        "total_pnl": round(pnl, 2)})

    return {"strategies": report, "total_trades": len(trades), "total_pnl": round(total_pnl, 2),
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


if __name__ == "__main__":
    rpt = generate_report()
    if rpt:
        print(f"=== 战报 ({rpt['generated_at']}) ===")
        for s in rpt["strategies"]:
            print(f"  {s['name']}: {s['trades']}笔 胜率{s['win_rate']} PnL={s['total_pnl']:+.2f}")
        print(f"  合计: {rpt['total_trades']}笔 PnL={rpt['total_pnl']:+.2f} USDT")
    else:
        print("无交易记录")
