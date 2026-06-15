import datetime
import sqlite3
import os

LOCAL_DB = "/home/admin/okx_bot/hermes_trades.db"


def _get_conn():
    conn = sqlite3.connect(LOCAL_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            strategy TEXT NOT NULL,
            action TEXT NOT NULL,
            price REAL NOT NULL,
            pnl REAL DEFAULT 0,
            status TEXT DEFAULT '持仓中'
        )
    """)
    return conn


def log_trade(sid, action, price, pnl=0, grid_id=None):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    grid_tag = f" | 网格ID:{grid_id}" if grid_id else ""
    status = "已平仓" if action in ("SELL", "SELL_SIM") else "持仓中"

    log_entry = f"[{timestamp}] 策略 {sid}{grid_tag} | {action} | 价格: {price} | 盈亏: {pnl:.2f}%\n"
    with open("trade_log.txt", "a") as f:
        f.write(log_entry)

    try:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO trades (ts, strategy, action, price, pnl, status) VALUES (?, ?, ?, ?, ?, ?)",
            (timestamp, sid, action, price, pnl, status),
        )
        if status == "已平仓":
            conn.execute(
                "UPDATE trades SET status=? WHERE strategy=? AND status='持仓中'",
                (status, sid),
            )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DB] 写入失败: {e}")


def update_report():
    pass
