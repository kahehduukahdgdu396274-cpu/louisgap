"""Unified position state — state.json tranches synced from bot position_*.json."""
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

_root = os.path.dirname(os.path.abspath(__file__))
_scripts = os.path.join(_root, "scripts")
if os.path.isdir(_scripts) and _scripts not in sys.path:
    sys.path.insert(0, _scripts)
if _root not in sys.path:
    sys.path.insert(0, _root)

STATE_FILENAME = "state.json"
PENDING_CLOSES_FILENAME = "pending_close_legs.json"
SCHEMA_VERSION = 1
MAX_CLOSE_RETRIES = 3


def _atomic_write_json(path: str, data: Any) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fp:
        json.dump(data, fp)
    os.replace(tmp, path)


def empty_state() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "net_position": {"direction": "", "size": 0, "avg_px": 0, "entry_time": 0},
        "tranches": [],
        "realized_legs": [],
    }


def load_state(base_dir: str) -> dict:
    path = os.path.join(base_dir, STATE_FILENAME)
    if not os.path.exists(path):
        return empty_state()
    with open(path, encoding="utf-8") as fp:
        state = json.load(fp)
    state.setdefault("realized_legs", [])
    state.setdefault("tranches", [])
    state.setdefault("schema_version", SCHEMA_VERSION)
    return state


def compute_net_position(tranches: List[dict]) -> dict:
    open_tr = [
        tr
        for tr in tranches
        if float(tr.get("remaining_qty", tr.get("qty", 0)) or 0) > 0
    ]
    if not open_tr:
        return {"direction": "", "size": 0, "avg_px": 0, "entry_time": 0}

    def _qty(tr: dict) -> float:
        return float(tr.get("remaining_qty", tr.get("qty", 0)) or 0)

    long_tr = [tr for tr in open_tr if tr.get("direction") == "long"]
    short_tr = [tr for tr in open_tr if tr.get("direction") == "short"]
    long_sz = sum(_qty(tr) for tr in long_tr)
    short_sz = sum(_qty(tr) for tr in short_tr)

    if long_sz >= short_sz and long_sz > 0:
        direction, active, size = "long", long_tr, long_sz
    elif short_sz > 0:
        direction, active, size = "short", short_tr, short_sz
    else:
        return {"direction": "", "size": 0, "avg_px": 0, "entry_time": 0}

    weighted = sum(float(tr.get("entry_price", 0) or 0) * _qty(tr) for tr in active)
    avg_px = weighted / size if size else 0
    entry_time = min(float(tr.get("entry_time", 0) or 0) for tr in active)
    return {
        "direction": direction,
        "size": round(size, 4),
        "avg_px": round(avg_px, 4),
        "entry_time": entry_time,
    }


def save_state(state: dict, base_dir: str) -> None:
    state["schema_version"] = SCHEMA_VERSION
    state["net_position"] = compute_net_position(state.get("tranches", []))
    _atomic_write_json(os.path.join(base_dir, STATE_FILENAME), state)


def tracker_to_tranche(sid: str, tr: dict) -> Optional[dict]:
    if not tr.get("position"):
        return None
    et = float(tr.get("entry_time", time.time()) or time.time())
    qty = float(tr.get("qty", 1) or 1)
    remaining = float(tr.get("remaining_qty", qty) or qty)
    if remaining <= 1e-9:
        return None
    return {
        "tranche_id": tr.get("tranche_id") or f"{sid}-{int(et * 1000)}-1",
        "strategy_id": sid,
        "direction": tr.get("direction", "long"),
        "entry_price": float(tr.get("entry_price", 0) or 0),
        "entry_time": et,
        "qty": qty,
        "remaining_qty": remaining,
        "margin_locked": float(tr.get("margin_locked", 0) or 0),
        "open_ord_id": tr.get("open_ord_id", ""),
        "open_fee": float(tr.get("open_fee", 0) or 0),
    }


def sync_tracker_to_state(tracker: Dict[str, dict], base_dir: str, logger: Any = None) -> dict:
    """position_*.json 变更后立即同步 state tranches（单一真源链路）。"""
    return reconcile_state_from_tracker(tracker, base_dir, logger=logger)


def _tranche_qty(tr: dict) -> float:
    return float(tr.get("remaining_qty", tr.get("qty", 0)) or 0)


def reconcile_state_from_tracker(
    tracker: Dict[str, dict],
    base_dir: str,
    logger: Any = None,
) -> dict:
    """Rebuild open tranches from position tracker; preserve realized_legs."""
    state = load_state(base_dir)
    existing_open = [t for t in state.get("tranches", []) if _tranche_qty(t) > 0]
    open_tranches = []
    for sid, tr in tracker.items():
        tc = tracker_to_tranche(sid, tr)
        if tc:
            open_tranches.append(tc)

    if len(existing_open) > 1 and open_tranches:
        exist_by_sid: Dict[str, float] = {}
        for tr in existing_open:
            sid = str(tr.get("strategy_id", ""))
            exist_by_sid[sid] = exist_by_sid.get(sid, 0.0) + _tranche_qty(tr)
        new_by_sid: Dict[str, float] = {}
        for tr in open_tranches:
            sid = str(tr.get("strategy_id", ""))
            new_by_sid[sid] = new_by_sid.get(sid, 0.0) + _tranche_qty(tr)
        sids = set(exist_by_sid) | set(new_by_sid)
        if all(abs(exist_by_sid.get(s, 0) - new_by_sid.get(s, 0)) < 1e-6 for s in sids):
            if logger:
                logger.info(
                    f"[state] 保留 {len(existing_open)} tranche 明细"
                    f"（与 position 总量一致，不压扁）"
                )
            return state

    state["tranches"] = open_tranches
    save_state(state, base_dir)
    if logger:
        logger.info(f"[state] reconciled {len(open_tranches)} open tranche(s) from position files")
    return state


def _pending_path(base_dir: str) -> str:
    return os.path.join(base_dir, PENDING_CLOSES_FILENAME)


def load_pending_closes(base_dir: str) -> list:
    path = _pending_path(base_dir)
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as fp:
            return json.load(fp) or []
    except (OSError, json.JSONDecodeError):
        return []


def save_pending_closes(base_dir: str, items: list) -> None:
    _atomic_write_json(_pending_path(base_dir), items)


def enqueue_pending_close(base_dir: str, payload: dict) -> None:
    items = load_pending_closes(base_dir)
    cid = (payload.get("close_ord_id") or "").strip()
    items = [x for x in items if (x.get("close_ord_id") or "").strip() != cid]
    payload["retries"] = int(payload.get("retries", 0) or 0)
    payload["enqueued_at"] = time.time()
    items.append(payload)
    save_pending_closes(base_dir, items)


def _apply_partial_close_to_tranches(state: dict, sid: str, close_qty: float) -> None:
    """减仓：扣减 tranche remaining_qty；全平时移除该策略 tranche。"""
    remaining = float(close_qty or 0)
    if remaining <= 1e-9:
        return
    updated = []
    for tr in state.get("tranches", []):
        if tr.get("strategy_id") != sid:
            updated.append(tr)
            continue
        rq = float(tr.get("remaining_qty", tr.get("qty", 0)) or 0)
        if rq <= 1e-9:
            continue
        deduct = min(rq, remaining)
        rq -= deduct
        remaining -= deduct
        if rq > 1e-9:
            tr = dict(tr)
            tr["remaining_qty"] = round(rq, 6)
            updated.append(tr)
    state["tranches"] = updated


def apply_close_to_tracker(tracker_entry: dict, close_qty: float) -> dict:
    """同步扣减 position tracker（支持部分平仓）。"""
    tr = dict(tracker_entry)
    if not tr.get("position"):
        return tr
    rq = float(tr.get("remaining_qty", tr.get("qty", 0)) or 0)
    deduct = min(rq, float(close_qty or 0))
    rq = max(0.0, rq - deduct)
    if rq <= 1e-9:
        tr["position"] = False
        tr["entry_price"] = 0
        tr["qty"] = 0
        tr["remaining_qty"] = 0
    else:
        tr["remaining_qty"] = round(rq, 6)
        tr["qty"] = round(rq, 6)
    return tr


def record_close_leg(
    sid: str,
    tracker_entry: dict,
    close_ord_id: str,
    fill_pnl: float,
    fee: float,
    exit_price: float,
    reason: str,
    base_dir: str,
    equity_after: float | None = None,
    close_qty: float | None = None,
    close_time: float | None = None,
) -> dict | None:
    """记录平仓腿；支持部分平仓；失败时写入 pending_close_legs 待 reconcile 重试。"""
    close_oid = (close_ord_id or "").strip()
    if not close_oid:
        enqueue_pending_close(
            base_dir,
            {
                "strategy_id": sid,
                "close_ord_id": close_ord_id,
                "fill_pnl": fill_pnl,
                "fee": fee,
                "exit_price": exit_price,
                "reason": reason,
                "close_qty": close_qty,
                "tracker": tracker_entry,
            },
        )
        return None

    try:
        state = load_state(base_dir)
        tranche = tracker_to_tranche(sid, tracker_entry)
        if not tranche:
            for tr in state.get("tranches", []):
                if tr.get("strategy_id") == sid and float(
                    tr.get("remaining_qty", tr.get("qty", 0)) or 0
                ) > 0:
                    tranche = tr
                    break
        if not tranche:
            raise RuntimeError("no_open_tranche")

        open_oid = (tranche.get("open_ord_id") or tracker_entry.get("open_ord_id") or "").strip()
        if not open_oid:
            raise RuntimeError("no_open_ord_id")

        leg_qty = float(close_qty if close_qty is not None else tranche.get("remaining_qty", tranche.get("qty", 1)) or 1)

        leg = {
            "strategy_id": sid,
            "direction": tranche.get("direction", "long"),
            "entry_price": tranche.get("entry_price", 0),
            "exit_price": exit_price,
            "qty": leg_qty,
            "entry_time": tranche.get("entry_time", 0),
            "close_time": close_time if close_time is not None else time.time(),
            "open_ord_id": open_oid,
            "close_ord_id": close_ord_id,
            "fee": fee,
            "net_pnl": fill_pnl,
            "reason": reason,
        }
        if equity_after is not None:
            leg["equity_after"] = round(float(equity_after), 2)

        for i, existing in enumerate(state.get("realized_legs", [])):
            if (existing.get("close_ord_id") or "").strip() == close_oid:
                from okx_close_aggregate import merge_okx_close_legs  # noqa: E402

                merged = merge_okx_close_legs(existing, leg)
                if equity_after is not None:
                    merged["equity_after"] = round(float(equity_after), 2)
                state["realized_legs"][i] = merged
                save_state(state, base_dir)
                return merged

        state.setdefault("realized_legs", []).append(leg)
        _apply_partial_close_to_tranches(state, sid, leg_qty)
        save_state(state, base_dir)
        return leg
    except Exception:
        items = load_pending_closes(base_dir)
        found = None
        for it in items:
            if (it.get("close_ord_id") or "").strip() == close_oid:
                found = it
                break
        payload = found or {
            "strategy_id": sid,
            "close_ord_id": close_ord_id,
            "fill_pnl": fill_pnl,
            "fee": fee,
            "exit_price": exit_price,
            "reason": reason,
            "close_qty": close_qty,
            "tracker": tracker_entry,
            "retries": 0,
        }
        payload["retries"] = int(payload.get("retries", 0) or 0) + 1
        if payload["retries"] <= MAX_CLOSE_RETRIES:
            enqueue_pending_close(base_dir, payload)
        return None
