#!/usr/bin/env python3
"""OKX net 与 state/position 张数对齐 — 对账、体检、告警共用。"""
from __future__ import annotations

import json
import os
import sys

BASE = os.environ.get("OKX_BOT_DIR", "/home/admin/okx_bot")
SYMBOL = "BTC-USDT-SWAP"
STRATEGY_IDS = ["003", "006", "009", "010", "011", "012", "013", "014"]


def _signed_qty(direction: str, size: float) -> float:
    if size <= 0:
        return 0.0
    return size if direction == "long" else -size


def local_net_from_state(base_dir: str | None = None) -> dict:
    """从 state.json 读取净持仓张数（多为正、空为负）。"""
    base = base_dir or BASE
    path = os.path.join(base, "state.json")
    if not os.path.exists(path):
        return {"net_signed": 0.0, "direction": "", "size": 0.0, "avg_px": 0.0, "tranches": 0}
    with open(path, encoding="utf-8") as fp:
        state = json.load(fp)
    net = state.get("net_position") or {}
    direction = net.get("direction") or ""
    size = float(net.get("size", 0) or 0)
    signed = _signed_qty(direction, size)
    tranches = [
        t
        for t in state.get("tranches", [])
        if float(t.get("remaining_qty", t.get("qty", 0)) or 0) > 0
    ]
    return {
        "net_signed": signed,
        "direction": direction,
        "size": size,
        "avg_px": float(net.get("avg_px", 0) or 0),
        "tranches": len(tranches),
        "tranche_sids": [t.get("strategy_id") for t in tranches],
    }


def local_net_from_positions(base_dir: str | None = None) -> float:
    """position_*.json 折算净张数。"""
    base = base_dir or BASE
    total = 0.0
    for sid in STRATEGY_IDS:
        path = os.path.join(base, f"position_{sid}.json")
        if not os.path.exists(path):
            continue
        try:
            tr = json.loads(open(path, encoding="utf-8").read())
        except (OSError, json.JSONDecodeError):
            continue
        if not tr.get("position"):
            continue
        qty = float(tr.get("remaining_qty", tr.get("qty", 0)) or 0)
        d = tr.get("direction", "long")
        total += qty if d == "long" else -qty
    return total


def fetch_okx_net_signed(client) -> dict:
    pr = client.request("GET", f"/api/v5/account/positions?instId={SYMBOL}")
    if pr.get("code") != "0" or not pr.get("data"):
        raise RuntimeError(f"OKX position query failed: {pr}")
    row = pr["data"][0]
    pos = float(row.get("pos") or 0)
    side = (row.get("posSide") or "net").lower()
    if side == "short":
        signed = -abs(pos)
    elif side == "long":
        signed = abs(pos)
    else:
        signed = pos
    return {
        "net_signed": signed,
        "size": abs(pos),
        "direction": "long" if signed > 0 else ("short" if signed < 0 else ""),
        "avg_px": float(row.get("avgPx") or 0),
    }


def check_alignment(client=None, base_dir: str | None = None) -> dict:
    base = base_dir or BASE
    local = local_net_from_state(base)
    local_pos = local_net_from_positions(base)
    okx = None
    err = ""
    if client is not None:
        try:
            okx = fetch_okx_net_signed(client)
        except Exception as ex:
            err = str(ex)
    okx_signed = float(okx["net_signed"]) if okx else None
    state_signed = float(local["net_signed"])
    aligned_state = okx_signed is not None and abs(okx_signed - state_signed) < 0.01
    aligned_pos = okx_signed is not None and abs(okx_signed - local_pos) < 0.01
    return {
        "okx_net": okx_signed,
        "okx_avg_px": okx.get("avg_px") if okx else None,
        "state_net": state_signed,
        "state_size": local["size"],
        "state_avg_px": local["avg_px"],
        "position_net": local_pos,
        "aligned": aligned_state and aligned_pos,
        "aligned_state": aligned_state,
        "aligned_position": aligned_pos,
        "tranches": local["tranches"],
        "tranche_sids": local.get("tranche_sids", []),
        "error": err,
    }


def pad_attribution_to_net(
    net_pos: int,
    attr: list[dict],
    okx_avg: float,
    okx_entry_time: float,
    orders: list[dict] | None = None,
) -> list[dict]:
    """LIFO 未覆盖的缺口用 OKX 均价补齐，保证归因张数 == |net_pos|。"""
    if net_pos == 0:
        return attr
    need = float(abs(net_pos))
    got = sum(float(a.get("qty", 0) or 0) for a in attr)
    gap = round(need - got, 4)
    if gap <= 0.01:
        return attr
    sid = "003"
    if attr:
        sid = attr[-1].get("sid") or sid
    elif orders:
        sid = orders[-1].get("sid") or sid
    direction = "long" if net_pos > 0 else "short"
    attr = list(attr)
    attr.append(
        {
            "sid": sid,
            "direction": direction,
            "qty": gap,
            "entry_price": okx_avg,
            "entry_time": okx_entry_time,
            "open_ord_id": "okx_net_pad",
            "px_sum": okx_avg * gap,
        }
    )
    print(f"PAD okx_net +{gap}张 -> {sid} @{okx_avg:.2f} (LIFO缺口补齐)")
    return attr


if __name__ == "__main__":
    sys.path.insert(0, BASE)
    from api import OKXClient  # noqa: E402

    print(check_alignment(OKXClient()))
