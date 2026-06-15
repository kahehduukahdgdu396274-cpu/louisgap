#!/usr/bin/env python3
"""OKX 平仓聚合：一 close_ord 多 fill 合并；同策略同开仓同分钟多单一行战报。"""
from __future__ import annotations

from datetime import datetime


def _close_minute(leg: dict) -> str:
    ct = float(leg.get("close_time", 0) or 0)
    if ct <= 0:
        return ""
    return datetime.fromtimestamp(ct).strftime("%Y-%m-%d %H:%M")


def _leg_group_key(leg: dict) -> tuple:
    """同策略、同开仓 ord、同平仓分钟 → 视为一次平仓动作（OKX 多笔委托合并）。"""
    sid = (leg.get("strategy_id") or "").strip()
    open_oid = (leg.get("open_ord_id") or "").strip()
    if open_oid:
        return (sid, open_oid, _close_minute(leg))
    ep = round(float(leg.get("entry_price", 0) or 0), 2)
    return (sid, f"ep:{ep}", _close_minute(leg))


def merge_okx_close_legs(primary: dict, other: dict) -> dict:
    """按 OKX 规则合并两笔平仓腿：加权均价、张数/盈亏/手续费求和。"""
    a, b = dict(primary), dict(other)
    qty_a = float(a.get("qty", 0) or 0)
    qty_b = float(b.get("qty", 0) or 0)
    total_qty = qty_a + qty_b
    if total_qty <= 0:
        return a

    def wavg(field: str) -> float:
        va = float(a.get(field, 0) or 0)
        vb = float(b.get(field, 0) or 0)
        return (va * qty_a + vb * qty_b) / total_qty

    pnl = round(float(a.get("net_pnl", 0) or 0) + float(b.get("net_pnl", 0) or 0), 4)
    fee = round(float(a.get("fee", 0) or 0) + float(b.get("fee", 0) or 0), 4)
    ct = max(float(a.get("close_time", 0) or 0), float(b.get("close_time", 0) or 0))
    et = min(
        float(a.get("entry_time", 0) or 0) or ct,
        float(b.get("entry_time", 0) or 0) or ct,
    )

    out = dict(a)
    out.update(
        {
            "qty": round(total_qty, 4),
            "entry_price": round(wavg("entry_price"), 2),
            "exit_price": round(wavg("exit_price"), 2),
            "net_pnl": pnl,
            "fee": fee,
            "entry_time": et,
            "close_time": ct,
            "reason": "OKX同策略平仓合并",
        }
    )
    return out


def collapse_okx_close_legs(legs: list[dict]) -> tuple[list[dict], int]:
    """同策略同开仓同平仓分钟的多笔 leg 合并为一笔（学习 OKX 按委托聚合 fill）。"""
    if not legs:
        return [], 0
    groups: dict[tuple, list[dict]] = {}
    order: list[tuple] = []
    for leg in legs:
        cid = (leg.get("close_ord_id") or "").strip()
        if not cid:
            continue
        key = _leg_group_key(leg)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(leg)

    merged, collapsed = [], 0
    for key in order:
        batch = groups[key]
        if len(batch) == 1:
            merged.append(batch[0])
            continue
        batch.sort(key=lambda x: float(x.get("close_time", 0) or 0))
        acc = batch[0]
        for leg in batch[1:]:
            acc = merge_okx_close_legs(acc, leg)
            collapsed += 1
        merged.append(acc)

    no_id = [leg for leg in legs if not (leg.get("close_ord_id") or "").strip()]
    merged.extend(no_id)
    merged.sort(key=lambda x: float(x.get("close_time", 0) or 0))
    return merged, collapsed


def collapse_okx_close_rows(rows: list[dict]) -> tuple[list[dict], int]:
    """战报行：同策略+同开仓 ord+同平仓分钟合并（保留首笔 close ordId）。"""
    closed = [r for r in rows if r.get("状态") == "已平仓"]
    other = [r for r in rows if r.get("状态") != "已平仓"]
    if not closed:
        return rows, 0

    def row_key(row: dict) -> tuple:
        sid = (row.get("策略") or "").strip()
        open_oid = (row.get("_open_ordId") or row.get("open_ordId") or "").strip()
        ct = (row.get("出场时间") or "")[:16]
        if open_oid:
            return (sid, open_oid, ct)
        ep = round(float(row.get("入场价", 0) or 0), 2)
        return (sid, f"ep:{ep}", ct)

    groups: dict[tuple, list[dict]] = {}
    order: list[tuple] = []
    for row in closed:
        key = row_key(row)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)

    merged_closed, collapsed = [], 0
    for key in order:
        batch = groups[key]
        if len(batch) == 1:
            merged_closed.append(batch[0])
            continue
        total_qty = sum(float(r.get("开仓张数", 0) or 0) for r in batch)
        ep_sum = xp_sum = pnl_sum = fee_sum = 0.0
        et_min = ct_max = None
        for row in batch:
            qty = float(row.get("开仓张数", 0) or 0)
            ep = float(row.get("入场价", 0) or 0)
            xp = float(row.get("出场价", 0) or 0)
            pnl = float(row.get("净盈亏", 0) or 0)
            fee = float(row.get("fee", 0) or 0)
            ep_sum += ep * qty
            xp_sum += xp * qty
            pnl_sum += pnl
            fee_sum += fee
            ot = row.get("开仓时间", "")
            ct = row.get("出场时间", "")
            if ot and (et_min is None or ot < et_min):
                et_min = ot
            if ct and (ct_max is None or ct > ct_max):
                ct_max = ct
        primary = sorted(batch, key=lambda r: r.get("出场时间", ""))[0]
        row = dict(primary)
        row.update(
            {
                "开仓时间": et_min or primary.get("开仓时间", ""),
                "出场时间": ct_max or primary.get("出场时间", ""),
                "入场价": round(ep_sum / total_qty, 2) if total_qty else primary.get("入场价"),
                "出场价": round(xp_sum / total_qty, 2) if total_qty else primary.get("出场价"),
                "开仓张数": round(total_qty, 4),
                "净盈亏": round(pnl_sum, 4),
                "fee": round(fee_sum, 4),
                "原因": "OKX同策略平仓合并",
                "数据源": "okx_close_merge",
            }
        )
        merged_closed.append(row)
        collapsed += len(batch) - 1

    merged_closed.sort(key=lambda r: r.get("出场时间", ""))
    return merged_closed + other, collapsed
