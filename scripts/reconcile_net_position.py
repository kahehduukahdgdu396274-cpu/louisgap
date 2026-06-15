#!/usr/bin/env python3
"""Align position_*.json + state.json with OKX net position after net_mode collision."""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from datetime import datetime

BASE = os.environ.get("OKX_BOT_DIR", "/home/admin/okx_bot")
sys.path.insert(0, BASE)

from api import OKXClient  # noqa: E402
from position_state import reconcile_state_from_tracker, save_state, load_state  # noqa: E402

SYMBOL = "BTC-USDT-SWAP"
STRATEGY_IDS = ["003", "006", "009", "010", "011", "012", "013", "014"]

# 21:30 同 bar 连开后，OKX 最终净多 3 张的归因（按末笔贡献 fills）
ATTRIBUTION = [
    {
        "sid": "011",
        "direction": "long",
        "qty": 1.0,
        "open_ord_id": "3640972322096234496",
    },
    {
        "sid": "013",
        "direction": "long",
        "qty": 2.0,
        "open_ord_id": "3640972502585524224",
    },
]
CLEAR_SIDS = ["003"]


def empty_position():
    return {"position": False, "entry_price": 0}


def backup():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    for name in ("state.json", "trades.csv"):
        src = os.path.join(BASE, name)
        if os.path.exists(src):
            shutil.copy2(src, f"{src}.bak_net_{ts}")
    for sid in STRATEGY_IDS:
        pf = os.path.join(BASE, f"position_{sid}.json")
        if os.path.exists(pf):
            shutil.copy2(pf, f"{pf}.bak_net_{ts}")


def load_tracker():
    tracker = {}
    for sid in STRATEGY_IDS:
        path = os.path.join(BASE, f"position_{sid}.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fp:
                tracker[sid] = json.load(fp)
        else:
            tracker[sid] = empty_position()
    return tracker


def save_tracker(tracker):
    for sid, data in tracker.items():
        tmp = os.path.join(BASE, f"position_{sid}.json.tmp")
        with open(tmp, "w", encoding="utf-8") as fp:
            json.dump(data, fp)
        os.replace(tmp, os.path.join(BASE, f"position_{sid}.json"))


def fetch_okx_net(client: OKXClient) -> tuple[int, float, float]:
    pr = client.request("GET", f"/api/v5/account/positions?instId={SYMBOL}")
    if pr.get("code") != "0" or not pr.get("data"):
        raise RuntimeError(f"OKX position query failed: {pr}")
    row = pr["data"][0]
    pos = int(row.get("pos") or 0)
    avg_px = float(row.get("avgPx") or 0)
    ctime_ms = row.get("cTime")
    entry_time = float(ctime_ms) / 1000.0 if ctime_ms else time.time()
    return pos, avg_px, entry_time


def fill_snapshot(client: OKXClient, ord_id: str) -> dict:
    data = client.fetch_fills_by_ordId(ord_id)
    if not data:
        return {"avgPx": 0.0, "totalSz": 0.0, "fee": 0.0}
    return data


def main() -> None:
    client = OKXClient()
    net_pos, okx_avg, okx_entry_time = fetch_okx_net(client)
    expected_net = sum(
        (a["qty"] if a["direction"] == "long" else -a["qty"]) for a in ATTRIBUTION
    )
    if net_pos != expected_net:
        print(
            f"WARN: OKX net={net_pos} != expected attribution net={expected_net}; "
            "proceeding with OKX as truth"
        )

    backup()
    tracker = load_tracker()

    for sid in STRATEGY_IDS:
        tracker[sid] = empty_position()

    for attr in ATTRIBUTION:
        sid = attr["sid"]
        fills = fill_snapshot(client, attr["open_ord_id"])
        entry_px = float(fills.get("avgPx") or okx_avg or 0)
        qty = float(attr["qty"])
        et = okx_entry_time
        tracker[sid] = {
            "position": True,
            "direction": attr["direction"],
            "entry_price": entry_px,
            "entry_time": et,
            "qty": qty,
            "open_ord_id": attr["open_ord_id"],
            "tranche_id": f"{sid}-{int(et * 1000)}-1",
            "margin_locked": (qty * entry_px * 0.01) / 5 if entry_px else 0,
        }
        print(f"SET {sid} {attr['direction']} qty={qty} @ {entry_px:.2f} ord={attr['open_ord_id']}")

    for sid in CLEAR_SIDS:
        print(f"CLEAR ghost {sid}")

    save_tracker(tracker)
    reconcile_state_from_tracker(tracker, BASE, logger=None)

    import build_war_report as b  # noqa: E402

    b.reconcile_state_from_position_files(BASE)
    b.rebuild_trades_from_state()
    b.dedup_trades_csv()
    print("OK: trades.csv rebuilt from reconciled state")

    state = load_state(BASE)
    print(
        "OK: state net",
        state.get("net_position"),
        "tranches",
        [(t["strategy_id"], t["direction"], t["qty"]) for t in state.get("tranches", [])],
    )
    print(f"DONE | OKX net={net_pos} avgPx={okx_avg:.2f}")


if __name__ == "__main__":
    main()
