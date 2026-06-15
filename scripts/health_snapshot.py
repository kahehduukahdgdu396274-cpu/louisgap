#!/usr/bin/env python3
"""Write logs/health_snapshot.json on VPS — single read source for health_check / AI."""
import json
import os
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

BASE_DIR = Path(os.environ.get("OKX_BOT_DIR", "/home/admin/okx_bot"))
OUT = BASE_DIR / "logs" / "health_snapshot.json"
STRATEGY_IDS = ["003", "006", "009", "010", "011", "012", "013", "014"]


def _read_bot_log() -> Optional[Path]:
    day = datetime.now().strftime("%Y%m%d")
    for name in ("logs/bot_systemd.log", f"bot_output_{day}.log"):
        path = BASE_DIR / name
        if path.exists():
            return path
    return None


def _grep_last(pattern: str, log_path: Path) -> str:
    try:
        out = subprocess.run(
            ["grep", "-F", pattern, str(log_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        lines = [ln for ln in out.stdout.splitlines() if ln.strip()]
        return lines[-1] if lines else ""
    except Exception:
        return ""


def _parse_heartbeat(line: str) -> dict:
    info = {"raw": line, "strategies": {}}
    if not line:
        return info
    m = re.search(r"BTC \$([0-9.]+)", line)
    if m:
        info["btc_price"] = float(m.group(1))
    for sid in STRATEGY_IDS:
        sm = re.search(rf"{sid}:((?:多|空)|O)[CL]*", line)
        if sm:
            info["strategies"][sid] = sm.group(1)
    return info


def _expected_hb_label(pos: dict) -> str:
    if not pos.get("position"):
        return "O"
    return "多" if pos.get("direction", "long") == "long" else "空"


def _heartbeat_desync(hb: dict, positions: dict) -> list[str]:
    """心跳标签与 position_*.json 不一致的策略（内存未重载时的残留）。"""
    out = []
    for sid in STRATEGY_IDS:
        hb_lbl = hb.get("strategies", {}).get(sid, "O")
        exp = _expected_hb_label(positions.get(sid, {}))
        if hb_lbl != exp:
            out.append(sid)
    return out


def _load_positions() -> dict:
    positions = {}
    for sid in STRATEGY_IDS:
        path = BASE_DIR / f"position_{sid}.json"
        if not path.exists():
            positions[sid] = {"position": False, "entry_price": 0}
            continue
        try:
            positions[sid] = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            positions[sid] = {"error": "parse_failed"}
    return positions


def _load_state_summary() -> dict:
    path = BASE_DIR / "state.json"
    if not path.exists():
        return {"present": False}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        net = state.get("net_position", {})
        tranches = [
            tr
            for tr in state.get("tranches", [])
            if float(tr.get("remaining_qty", tr.get("qty", 0)) or 0) > 0
        ]
        return {
            "present": True,
            "net_direction": net.get("direction", ""),
            "net_size": float(net.get("size", 0) or 0),
            "avg_px": float(net.get("avg_px", 0) or 0),
            "open_tranches": len(tranches),
            "tranche_sids": [tr.get("strategy_id") for tr in tranches],
        }
    except Exception as exc:
        return {"present": True, "error": str(exc)}


def _ws_rest_warn_count_today() -> int:
    alert_log = BASE_DIR / "logs" / "alerts.log"
    if not alert_log.exists():
        return 0
    today = datetime.now().strftime("%Y-%m-%d")
    return sum(
        1
        for line in alert_log.read_text(encoding="utf-8", errors="ignore").splitlines()
        if today in line and "偏差过大" in line
    )


def _price_notes(positions: dict, state_sum: dict) -> list:
    notes = []
    avg_px = float(state_sum.get("avg_px", 0) or 0)
    for sid, pos in positions.items():
        if not pos.get("position"):
            continue
        entry = float(pos.get("entry_price", 0) or 0)
        if entry > 0 and avg_px > 0 and abs(entry - avg_px) > 1:
            notes.append(
                f"{sid}: entry_price={entry:.2f} vs state.avg_px={avg_px:.2f} (策略记账 vs 交易所均价，非 desync)"
            )
    return notes


def _heartbeat_age_sec(hb_line: str) -> int | None:
    """解析日志行 HH:MM:SS | ... 与当前时间的秒差。"""
    if not hb_line:
        return None
    m = re.search(r"^(\d{2}:\d{2}:\d{2})", hb_line.strip())
    if not m:
        return None
    try:
        now = datetime.now()
        hb = datetime.strptime(
            f"{now.strftime('%Y-%m-%d')} {m.group(1)}", "%Y-%m-%d %H:%M:%S"
        )
        age = int((now - hb).total_seconds())
        if age < 0 or age > 43200:
            hb = hb - timedelta(days=1)
            age = int((now - hb).total_seconds())
        return max(0, age)
    except Exception:
        return None


def _okx_alignment() -> dict:
    try:
        import sys

        scripts = BASE_DIR / "scripts"
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        if str(BASE_DIR) not in sys.path:
            sys.path.insert(0, str(BASE_DIR))
        from api import OKXClient  # noqa: E402
        from okx_net_alignment import check_alignment  # noqa: E402

        return check_alignment(OKXClient(), str(BASE_DIR))
    except Exception as exc:
        return {"aligned": None, "error": str(exc)}


def _critical_count_24h() -> int:
    alert_log = BASE_DIR / "logs" / "alerts.log"
    if not alert_log.exists():
        return 0
    count = 0
    today = datetime.now().strftime("%Y-%m-%d")
    for line in alert_log.read_text(encoding="utf-8", errors="ignore").splitlines()[-200:]:
        if today in line and "CRITICAL" in line:
            count += 1
    return count


def build_snapshot() -> dict:
    log_path = _read_bot_log()
    hb_line = _grep_last("BTC $", log_path) if log_path else ""
    hb = _parse_heartbeat(hb_line)
    positions = _load_positions()
    open_sids = [sid for sid, p in positions.items() if p.get("position")]

    active = (
        subprocess.run(
            ["systemctl", "is-active", "okx-bot"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        == "active"
    )

    safe_lock_line = _grep_last("SAFE_LOCK", log_path) if log_path else ""
    safe_lock_blocked = []
    m = re.search(r"拦截策略:\s*(\[[^\]]*\])", safe_lock_line)
    if m:
        try:
            safe_lock_blocked = json.loads(m.group(1).replace("'", '"'))
        except Exception:
            safe_lock_blocked = []

    state_sum = _load_state_summary()
    okx_align = _okx_alignment()
    state_synced = set(open_sids) == set(state_sum.get("tranche_sids", []))
    okx_aligned = okx_align.get("aligned")
    hb_desync = _heartbeat_desync(hb, positions)

    hb_age = _heartbeat_age_sec(hb_line)
    heartbeat_stale = hb_age is not None and hb_age > 300

    status = "idle_ok"
    if not active or not hb_line or heartbeat_stale:
        status = "degraded"
    elif open_sids:
        status = "holding_ok" if state_synced and okx_aligned is not False else "holding_desync"
    elif okx_aligned is False:
        status = "holding_desync"
    crit = _critical_count_24h()
    # 历史critical告警不覆盖当前健康状态（三源一致+运行中就不算critical）
    if crit > 0 and status not in ("holding_ok", "idle_ok"):
        status = "critical"

    return {
        "schema_version": 1,
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "bot_active": active,
        "status": status,
        "heartbeat": hb,
        "heartbeat_age_sec": hb_age,
        "heartbeat_stale": heartbeat_stale,
        "open_strategy_ids": open_sids,
        "open_count": len(open_sids),
        "positions": positions,
        "state": state_sum,
        "okx_alignment": okx_align,
        "okx_aligned": okx_aligned,
        "state_synced": state_synced,
        "heartbeat_desync": hb_desync,
        "safe_lock_blocked": safe_lock_blocked,
        "critical_alerts_today": crit,
        "ws_rest_warn_count_today": _ws_rest_warn_count_today(),
        "price_notes": _price_notes(positions, state_sum) + (
            [f"心跳残留: {','.join(hb_desync)} 与 position 不一致（以 position 为准）"]
            if hb_desync
            else []
        ),
        "report_phrase": (
            "系统正常，无需操作"
            if status == "idle_ok"
            else "系统运行中，{} 策略持仓，无需操作".format(len(open_sids))
            if status == "holding_ok"
            else "需要人工核查"
        ),
    }


def main() -> None:
    snap = build_snapshot()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(OUT)
    print(f"OK: {OUT} status={snap['status']}")


if __name__ == "__main__":
    main()
