import math, time, json, os, sys, logging, threading, sqlite3, fcntl
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from strategies import check_entry, check_exit
from config import SYMBOL, POLLING_INTERVAL, STRATEGY_IDS, MIN_EQUITY_THRESHOLD, EQUITY_CHECK_INTERVAL, SIGNAL_VALID_BARS
from api import OKXClient
from trade_logger import record_exit, fetch_entry_avg_price
from indicators import build_snapshot
from session_vwap import calculate_session_vwap
from ws_client import OKXWebSocket, WS_PUBLIC
from ws_health_monitor import WSHealthMonitor
# ==================== 环境零容忍断言 ====================
for _f in ['api.py', 'indicators.py', 'session_vwap.py', 'ws_client.py']:
    try:
        with open(_f) as _fp:
            _c = _fp.read()
        if 'ws.okx.com' in _c or 'www.okx.com' in _c:
            raise EnvironmentError(f'[ENV-GUARD] {_f} 中发现实盘地址！')
    except FileNotFoundError:
        pass
print('[ENV-GUARD] 环境自检通过')
# =======================================================


_LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s", datefmt=_LOG_DATEFMT)
logger = logging.getLogger("QuantBot")
client = OKXClient()

# ==================== SAFE LOCK ====================
# 安全锁: 按策略白名单拦截平仓
# BLOCK_LIST: 被拦截的策略列表（默认空=全策略可自动平仓）
SAFE_LOCK_BLOCK_LIST = [x.strip() for x in os.environ.get("SAFE_LOCK_BLOCK_LIST", "").split(",") if x.strip()]
logger.warning(f"[SAFE_LOCK] 平仓锁策略白名单, 拦截策略: {SAFE_LOCK_BLOCK_LIST}")
# ====================================================

HISTORY_DB = "history_candles.db"
# ==================== 风控核心函数 ====================
import pandas as pd
from datetime import datetime, timedelta

# FileHandler日志持久化
_log_dir = os.path.dirname(os.path.abspath(__file__))
_fh = logging.FileHandler(os.path.join(_log_dir, f"bot_output_{datetime.now().strftime('%Y%m%d')}.log"), mode='a', encoding='utf-8')
_fh.setFormatter(logging.Formatter("%(asctime)s | %(message)s", _LOG_DATEFMT))
logger.addHandler(_fh)

# 全局风控参数
MAX_RISK_PERCENT = 0.015        # 单笔最大风险 1.5%
MAX_DAILY_LOSS_PERCENT = 0.06   # 单日最大亏损 6%

daily_loss = 0.0
daily_reset_time = datetime.now()

# 策略独立预算（初始本金，平仓后按盈亏动态调整）
# 注意: 006已移除
BUDGET_CONFIG = {
    "003": {"type": "fixed", "limit": 200},
    "006": {"type": "fixed", "limit": 200},
    "013": {"type": "fixed", "limit": 200},
    "014": {"type": "fixed", "limit": 200},
    "POOL_009_012": {"type": "shared", "limit": 250, "members": ["009", "010", "011", "012"]}
}
# 动态权益账本 + 持久化
EQ_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "strategy_eq.json")

def _init_eq_dict():
    eq = {}
    for sid in STRATEGY_IDS:
        if sid in BUDGET_CONFIG:
            eq[sid] = BUDGET_CONFIG[sid]["limit"]
        elif sid in BUDGET_CONFIG.get("POOL_009_012", {}).get("members", []):
            eq[sid] = BUDGET_CONFIG["POOL_009_012"]["limit"]
    eq["POOL_009_012"] = BUDGET_CONFIG.get("POOL_009_012", {}).get("limit", 250)
    return eq

strategy_eq = _init_eq_dict()

def _load_strategy_eq():
    defaults = _init_eq_dict()
    if os.path.exists(EQ_FILE):
        try:
            with open(EQ_FILE) as f:
                saved = json.load(f)
            # Legacy迁移：006 -> 003（仅在006被移除策略列表时触发）
            LEGACY_006_ACTIVE = "006" in STRATEGY_IDS
            if "006" in saved and not LEGACY_006_ACTIVE:
                eq_006 = saved.pop("006")
                old_003 = saved.get("003", defaults.get("003", 200))
                saved["003"] = round(old_003 + eq_006, 2)
                logger.info(f"[EQ迁移] 006 -> 003: +${eq_006:.2f} (003: ${old_003:.2f} -> ${saved['003']:.2f})")
            for k in list(saved.keys()):
                if k not in defaults and k != "POOL_009_012":
                    del saved[k]
            for k, v in defaults.items():
                if k not in saved:
                    saved[k] = v
            strategy_eq.clear()
            strategy_eq.update(saved)
            logger.info(f"[EQ持久化] 从文件加载: {dict((k,round(v,2)) for k,v in saved.items())}")
        except Exception as e:
            logger.warning(f"[EQ持久化] 加载失败 ({e}), 使用初始值")
            strategy_eq.clear(); strategy_eq.update(defaults)
    else:
        logger.info("[EQ持久化] 文件不存在, 使用初始值")

def _save_strategy_eq():
    try:
        data = {k: round(v, 2) for k, v in strategy_eq.items()}
        tmp = EQ_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, EQ_FILE)
    except Exception as e:
        logger.error(f"[EQ持久化] 写入失败: {e}")

# 启动时加载持久化
_load_strategy_eq()

# ==================== 单实例锁（防双进程） ====================
BOT_LOCK_FILE = os.path.join(_log_dir, "bot.lock")
_lock_fd = open(BOT_LOCK_FILE, "w")
try:
    fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    logger.critical("[SINGLETON] 另一个 bot 实例正在运行，本进程退出")
    sys.exit(1)
logger.info("[SINGLETON] 单实例锁已获取")

COOLDOWN_FILE = os.path.join(_log_dir, "cooldown.json")

def _load_cooldown():
    if not os.path.exists(COOLDOWN_FILE):
        return {}
    try:
        with open(COOLDOWN_FILE, encoding="utf-8") as fp:
            raw = json.load(fp)
        now = time.time()
        return {k: float(v) for k, v in raw.items() if float(v) > now}
    except Exception as ex:
        logger.warning(f"[cooldown] 加载失败: {ex}")
        return {}

def _save_cooldown(cd):
    try:
        tmp = COOLDOWN_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fp:
            json.dump({k: v for k, v in cd.items()}, fp)
        os.replace(tmp, COOLDOWN_FILE)
    except Exception as ex:
        logger.warning(f"[cooldown] 保存失败: {ex}")


def _schedule_war_refresh(sid):
    """平仓且 OKX leg 校验通过后，后台以 state 真源重建战报。"""
    def _run():
        try:
            from build_war_report import refresh_war_report_accurate
            refresh_war_report_accurate(trigger_sid=sid)
        except Exception as ex:
            logger.warning(f"[war] 平仓后战报重建失败 sid={sid}: {ex}")

    threading.Thread(target=_run, daemon=True, name=f"war-refresh-{sid}").start()


def _schedule_okx_reconcile(reason):
    """OKX net 与本地不一致时，后台按 fills LIFO 自动对账。"""
    def _run():
        global t
        try:
            import subprocess
            script = os.path.join(_log_dir, "scripts/reconcile_all_from_okx.py")
            if not os.path.isfile(script):
                return
            with _position_io_lock:
                subprocess.run(
                    [sys.executable, script],
                    cwd=_log_dir,
                    timeout=180,
                    check=False,
                )
                t = load_all()
            logger.info(f"[pos_sync] 自动对账完成 reason={reason}")
        except Exception as ex:
            logger.warning(f"[pos_sync] 自动对账失败 reason={reason}: {ex}")

    threading.Thread(target=_run, daemon=True, name="okx-reconcile").start()

loop_count = 0
prev_ks, prev_ds, prev_ema9, prev_ema21, cooldown = {}, {}, {}, {}, _load_cooldown()
last_signal_bar = {}  # 同K线去重: sid->kt（日志/兼容）
last_global_entry_bar = 0  # net_mode 全 bot 每根 15m K 线只允许一笔新开
INDEPENDENT_SIDS = ["003", "006", "013", "014"]
POOL_SIDS = BUDGET_CONFIG.get("POOL_009_012", {}).get("members", ["009", "010", "011", "012"])
ALLOW_NEW_POSITIONS = True

# WS Ticker 实时价格
ws_latest_price = None
ws_last_time = 0.0
WS_STALE_SECS = 30
ws_price_lock = threading.Lock()
_position_io_lock = threading.Lock()

def pf(sid): return f"position_{sid}.json"
def load_all():
    t = {}
    for sid in STRATEGY_IDS:
        f = pf(sid)
        if os.path.exists(f):
            with open(f) as fp: t[sid] = json.load(fp)
        else: t[sid] = empty_position()
    return t

def empty_position():
    """空仓标准结构，避免残留 direction/entry_time 误导对账"""
    return {"position": False, "entry_price": 0}

def reset_position(tr):
    tr.clear()
    tr.update(empty_position())

def _atomic_write_json(path, data):
    """原子写 JSON，避免崩溃导致 position/state 半文件。"""
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fp:
        json.dump(data, fp)
    os.replace(tmp, path)


def save_all(t):
    with _position_io_lock:
        for sid, data in t.items():
            _atomic_write_json(pf(sid), data)
        try:
            from position_state import reconcile_state_from_tracker
            reconcile_state_from_tracker(t, _log_dir, logger)
        except Exception as ex:
            logger.warning(f"[state] sync failed: {ex}")


def _tracker_pos_key(tr):
    if not tr.get("position"):
        return ("flat", 0.0, "")
    return (
        tr.get("direction", "long"),
        float(tr.get("qty", 1) or 1),
        round(float(tr.get("entry_price", 0) or 0), 2),
    )


def reload_tracker_from_disk_if_changed(tracker):
    """cron/手工对账改写了 position_*.json 时，内存 tracker 须与磁盘一致（防心跳标签残留）。"""
    with _position_io_lock:
        fresh = load_all()
    changed = [
        sid for sid in STRATEGY_IDS
        if _tracker_pos_key(tracker.get(sid, {})) != _tracker_pos_key(fresh.get(sid, {}))
    ]
    if not changed:
        return False
    logger.warning(f"[pos_sync] 磁盘 position 与内存不一致 sid={changed}，从磁盘重载")
    tracker.update(fresh)
    return True


def _fetch_close_fills(close_ord_id, max_attempts=5, base_wait=2):
    """平仓后拉 fills；失败返回 None（禁止用估算盈亏改预算）。"""
    for attempt in range(1, max_attempts + 1):
        fills_data = client.fetch_fills_by_ordId(close_ord_id)
        if fills_data:
            return fills_data
        wait = base_wait * attempt
        logger.warning(f"[FILLS] ordId={close_ord_id} 第{attempt}/{max_attempts}次未找到, {wait}s后重试")
        time.sleep(wait)
    return None

# 行情改用WS ticker推送，K线仅用于指标计算
cached_o, cached_h, cached_l, cached_c, cached_v, cached_t = [], [], [], [], [], []
last_fc_time = 0

def fc():
    global cached_o, cached_h, cached_l, cached_c, cached_v, cached_t, last_fc_time
    now = time.time()
    if now - last_fc_time < 120:
        return cached_o, cached_h, cached_l, cached_c, cached_v, cached_t
    last_fc_time = now
    data = client.request("GET", f"/api/v5/market/candles?instId={SYMBOL}&bar=15m&limit=1000")
    if data.get("code") != "0": return None
    candles = data["data"]
    if len(candles) < 50: return None
    ts = [int(c[0]) for c in candles]
    o = [float(c[1]) for c in candles]; h = [float(c[2]) for c in candles]
    l = [float(c[3]) for c in candles]; c = [float(c[4]) for c in candles]; v = [float(c[5]) for c in candles]
    ts.reverse(); o.reverse(); h.reverse(); l.reverse(); c.reverse(); v.reverse()
    cached_o, cached_h, cached_l, cached_c, cached_v, cached_t = o, h, l, c, v, ts
    MAX_KLINE = 2000
    if len(o) > MAX_KLINE:
        trim = len(o) - MAX_KLINE
        o = o[trim:]; h = h[trim:]; l = l[trim:]; c = c[trim:]; v = v[trim:]
    try:
        db = sqlite3.connect(HISTORY_DB)
        db.execute("CREATE TABLE IF NOT EXISTS candles (ts INTEGER PRIMARY KEY, o REAL, h REAL, l REAL, c REAL, v REAL)")
        for j in range(len(o)):
            db.execute("INSERT OR IGNORE INTO candles (ts, o, h, l, c, v) VALUES (?,?,?,?,?,?)",
                       (int(candles[j][0]), o[j], h[j], l[j], c[j], v[j]))
        db.commit()
    except Exception as ex:
        logger.warning(f"持久化K线失败: {ex}")
    finally:
        try: db.close()
        except: pass
    return o, h, l, c, v, ts


def calc_order_sz(strategy_id, current_price, direction="long", usage=0.95):
    """
    动态开仓张数计算（唯一sz来源，禁用任何常数）

    sz = floor( (strategy_equity * usage * leverage) / (current_price * ct_val) )

    - strategy_equity: 该策略当前独立权益（初始+已实现盈亏，从strategy_eq读取）
    - usage: 资金使用率（默认0.95，预留余地）
    - leverage: 5x（当前全局固定）
    - current_price: 当前币价
    - ct_val: OKX合约面值（从OKX instruments API动态获取）

    返回: int 开仓张数，0表示不可开仓
    """
    # 动态获取合约面值（失败则抛异常，拒绝假数据下单）
    try:
        ct_val = client.get_ct_val()
    except Exception as e:
        logger.critical(f"[calc_order_sz] ct_val获取失败: {e}，无法下单")
        return 0

    leverage = 5  # 全局杠杆

    # 读取策略独立权益
    pool = BUDGET_CONFIG.get("POOL_009_012", {})
    if strategy_id in pool.get("members", []):
        equity = strategy_eq.get("POOL_009_012", pool["limit"])
        # 共享池：检查是否已被其他成员占用
        for m in pool["members"]:
            if m != strategy_id and t.get(m, {}).get("position", False):
                return 0
    else:
        equity = strategy_eq.get(strategy_id, BUDGET_CONFIG.get(strategy_id, {}).get("limit", 0))

    if equity <= 1:
        logger.warning(f"[calc_order_sz] {strategy_id} 权益金不足: ${equity:.2f}")
        return 0

    raw = (equity * usage * leverage) / (current_price * ct_val)
    if direction == "short":
        raw *= 0.8  # 空头安全系数

    sz = max(1, int(math.floor(raw)))
    logger.info(f"[calc_order_sz] {strategy_id} eq=${equity:.2f} price=${current_price:.0f} ctVal={ct_val} raw={raw:.2f} → sz={sz}")
    return sz


def risk_control_check(strategy_id, direction, current_price, atr, balance=None):
    """开仓前风控检查"""
    global daily_loss, daily_reset_time

    if datetime.now().date() != daily_reset_time.date():
        daily_loss = 0.0
        daily_reset_time = datetime.now()

    if balance is None or balance <= 0:
        try:
            balance = get_account_balance()
        except:
            # 资金获取失败则拒绝开仓，不给假兜底
            logger.critical(f"[风控] {strategy_id} 余额查询失败，拒绝开仓")
            return False
        if balance is None or balance <= 0:
            logger.critical(f"[风控] {strategy_id} 余额={balance} 无效，拒绝开仓")
            return False

    stop_loss_distance = atr * 1.8
    risk_amount = balance * MAX_RISK_PERCENT
    position_size = risk_amount / stop_loss_distance if stop_loss_distance > 0 else 0

    if daily_loss / balance > MAX_DAILY_LOSS_PERCENT:
        logger.warning(f"风控拦截: 今日亏损已达上限 ({daily_loss/balance*100:.2f}%)")
        return False

    logger.info(f"风控通过 | 策略:{strategy_id} | 方向:{direction} | 建议仓位:{position_size:.4f}")
    return True


# ================ 交易所成交后落库函数 ================

def log_trade_after_fill(strategy_id, direction, ord_id, action_type="open"):
    """
    【唯一交易记录入口】订单成交后调用，从OKX fills拉真实数据写入trades.csv
    - action_type: "open" 或 "close"
    - ord_id: 订单ID（来自place_order返回）
    - direction: "long"/"short"

    写入的数值全部来自OKX成交明细，禁止推算/估算
    """
    fills_data = client.fetch_fills_by_ordId(ord_id)
    if fills_data is None:
        logger.error(f"[log_trade_after_fill] {strategy_id} ordId={ord_id} fills不可用，跳过写入trades.csv")
        return

    avg_px = fills_data["avgPx"]
    total_sz = fills_data["totalSz"]
    fill_pnl = fills_data["fillPnl"]
    fee = fills_data["fee"]

    ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    wins_fn = "/home/admin/okx_bot/trades.csv"
    import csv
    file_exists = os.path.exists(wins_fn)
    with open(wins_fn, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists or os.path.getsize(wins_fn) == 0:
            writer.writerow(["开仓时间","出场时间","策略","方向","入场价","出场价","收益率%","净盈亏","状态","持仓时间(分)","原因","K值","D值","ADX","杠杆","开仓张数","策略权益金","fee","ordId"])
        writer.writerow([
            ts_str,  # 开仓/出场时间（用同一个字段）
            "",      # 出场时间（平仓时再补）
            strategy_id,
            direction,
            avg_px,  # 入场价（fills加权均价）
            "",      # 出场价
            "",      # 收益率%（平仓时补）
            "",      # 净盈亏（平仓时补）
            "持仓中",
            "",      # 持仓时间
            "",
            "",      # K值
            "",      # D值
            "",      # ADX
            5,       # 杠杆
            total_sz,  # 真实成交量
            strategy_eq.get(strategy_id, 0),
            fee,
            ord_id,
        ])

    if action_type == "close":
        # 平仓逻辑：更新对应开仓记录
        pass  # 简化：平仓时补填出场价和净盈亏

    if action_type == "open" and strategy_id in t and t[strategy_id].get("position"):
        t[strategy_id]["entry_price"] = float(avg_px)
        t[strategy_id]["qty"] = float(total_sz)
        save_all(t)

    logger.info(f"[log_trade_after_fill] ✅ {strategy_id} {action_type} ordId={ord_id} fillPx={avg_px} sz={total_sz} pnl={fill_pnl} fee={fee}")


def _equity_after_close(sid):
    """平仓结算后权益：共享池策略记池余额，其余记独立策略余额。"""
    pool = BUDGET_CONFIG.get("POOL_009_012", {})
    if sid in pool.get("members", []):
        return strategy_eq.get("POOL_009_012", pool["limit"])
    return strategy_eq.get(sid, BUDGET_CONFIG.get(sid, {}).get("limit", 0))


def update_strategy_pnl(sid, fill_pnl, entry_price, sz, ct_val):
    """
    平仓后：用 OKX fillPnl 真实值更新策略权益金

    pnl_net = fillPnl - fee  (fillPnl已经是扣除手续费后的净盈亏)
    注意：OKX fillPnl 返回的是 USDT 净盈亏（已扣手续费）
    """
    pnl_net = fill_pnl
    pool = BUDGET_CONFIG.get("POOL_009_012", {})
    if sid in pool.get("members", []):
        old_eq = strategy_eq.get("POOL_009_012", pool["limit"])
        strategy_eq["POOL_009_012"] = max(1, round(old_eq + pnl_net, 2))
        logger.info(f"[预算更新] {sid}(共享池) 盈亏${pnl_net:.2f} 池余额=${strategy_eq['POOL_009_012']:.2f}")
    else:
        old_eq = strategy_eq.get(sid, BUDGET_CONFIG.get(sid, {}).get("limit", 0))
        strategy_eq[sid] = max(1, round(old_eq + pnl_net, 2))
        logger.info(f"[预算更新] {sid} 盈亏${pnl_net:.2f} 余额=${strategy_eq[sid]:.2f}")

    # 释放保证金锁定
    if sid in t and "margin_locked" in t[sid]:
        del t[sid]["margin_locked"]
        save_all(t)

    logger.info(f"[预算更新] {sid} 净值 ${strategy_eq.get(sid, strategy_eq.get('POOL_009_012', 0)):.2f}")
    # 持久化权益金
    _save_strategy_eq()


def count_open_positions(tracker):
    return sum(1 for s in STRATEGY_IDS if tracker.get(s, {}).get("position"))


def local_net_qty(tracker):
    """本地各策略持仓折算为 OKX net 张数（多为正、空为负）。"""
    total = 0.0
    for tr in tracker.values():
        if not tr.get("position"):
            continue
        q = float(tr.get("qty", 1) or 1)
        total += q if tr.get("direction", "long") == "long" else -q
    return int(round(total))


def can_open_new_position(sid, tracker, bar_ts):
    """long_short_mode：各策略独立开仓，仅拦方向冲突 + 同bar重复。"""
    if not ALLOW_NEW_POSITIONS:
        return False, "fuse_off"
    if tracker.get(sid, {}).get("position"):
        return False, "sid_already_open"
    if bar_ts == last_global_entry_bar:
        return False, "global_bar_dedupe"
    # 检查 OKX 是否有反方向持仓（新开方向不能与已有持仓相反）
    # 从检查的信号方向入手，在调用处用 check_entry 返回值判断
    return True, "ok"


def ca(sid, tracker):
    """调用前检查: 是否允许开仓（动态预算 + 共享池排他性）"""
    if not ALLOW_NEW_POSITIONS: return False
    if tracker.get(sid, {}).get("position", False): return False
    pool = BUDGET_CONFIG.get("POOL_009_012", {})
    if sid in pool.get("members", []):
        for m in pool["members"]:
            if tracker.get(m, {}).get("position", False):
                return False
        used = sum(tracker.get(m, {}).get("margin_locked", 0) or 0 for m in pool["members"])
        if used >= strategy_eq.get("POOL_009_012", pool["limit"]):
            logger.warning(f"[风险拦截] 共享池已达预算上限 (已用{used:.2f})")
            return False
        return True
    budget = strategy_eq.get(sid, BUDGET_CONFIG.get(sid, {}).get("limit", 0))
    used = tracker.get(sid, {}).get("margin_locked", 0) or 0
    if used >= budget:
        logger.warning(f"[风险拦截] 策略 {sid} 已达预算上限 {budget} (已用{used:.2f})")
        return False
    return True


def get_account_balance():
    try:
        br = client.request("GET", "/api/v5/account/balance")
        if br.get("code") == "0" and br.get("data"):
            total_eq = float(br["data"][0].get("totalEq", 0))
            if total_eq > 0:
                return total_eq
        logger.warning(f"余额查询异常: {br.get('msg', '')}")
        return 0
    except Exception as e:
        logger.error(f"余额查询失败: {e}")
        return 0

def grp():
    """返回带符号的净持仓（正=long, 负=short）。
    long_short_mode 下 OKX 的 pos 始终正数，方向在 posSide 字段。"""
    try:
        pr = client.request("GET", f"/api/v5/account/positions?instId={SYMBOL}")
        if pr.get("code") != "0" or not pr.get("data"):
            return 0
        signed = 0
        for row in pr["data"]:
            p = float(row.get("pos") or 0)
            if abs(p) < 0.01:
                continue
            side = (row.get("posSide") or "net").lower()
            if side == "short":
                signed -= int(abs(p))
            elif side == "long":
                signed += int(abs(p))
            else:
                # net_mode: pos 本身带符号
                signed += int(round(p))
        return signed
    except Exception as e:
        logger.error(f"实盘查询失败: {e}")
        return None


t = load_all()
try:
    from position_state import reconcile_state_from_tracker
    reconcile_state_from_tracker(t, _log_dir, logger)
except Exception as ex:
    logger.warning(f"[state] startup reconcile failed: {ex}")
try:
    sys.path.insert(0, os.path.join(_log_dir, "scripts"))
    sys.path.insert(0, _log_dir)
    from govern_state_legs import govern_state_legs, catch_up_missing_closes
    gv = govern_state_legs(dry_run=False, refresh_war=False)
    if gv.get("before", 0) != gv.get("after", 0):
        logger.warning(f"[govern] startup pruned legs {gv.get('before')}→{gv.get('after')}")
    cu = catch_up_missing_closes(dry_run=False, max_add=3)
    if cu.get("added", 0):
        logger.info(f"[catchup] startup added {cu.get('added')} close leg(s)")
        t = load_all()
        reconcile_state_from_tracker(t, _log_dir, logger)
except Exception as ex:
    logger.warning(f"[govern/catchup] startup failed: {ex}")
last_vwap_update = 0; cached_vwap = 0; last_kline_ts = 0; last_pos_check = 0; last_equity_check = 0
last_auto_reconcile = 0
equity_fail_count = 0

# 启动WS ticker
def on_ticker(data):
    global ws_latest_price
    global ws_last_time
    for item in data:
        p = item.get("last")
        if p is None:
            continue
        p = float(p)
        if p <= 0:
            continue
        ws.last_price = p
        with ws_price_lock:
            ws_latest_price = p
            ws_last_time = time.time()

ws = OKXWebSocket(WS_PUBLIC)
ws.on("tickers", on_ticker)
ws.start_bg()
time.sleep(2)
ws.subscribe([{"channel": "tickers", "instId": SYMBOL}])
logger.info(f"WS ticker订阅: {SYMBOL}")

# 启动WS健康监控（price_getter 避免 import __main__ 在 systemd 下失败）
def _ws_price_snapshot():
    with ws_price_lock:
        return ws_latest_price

ws_monitor = WSHealthMonitor(ws, check_interval=30, max_deviation=50, price_getter=_ws_price_snapshot)
ws_monitor.start()

# 启动同步：本地 position_*.json 优先；仅当本地全无持仓时才把 OKX net 仓归到首个空闲策略
try:
    pr = client.request("GET", f"/api/v5/account/positions?instId={SYMBOL}")
    if pr.get("code") == "0" and pr.get("data"):
        # 用带符号的净仓位（grp() 逻辑，处理 long_short_mode 的 posSide）
        signed = 0
        for row in pr["data"]:
            p = float(row.get("pos") or 0)
            if abs(p) < 0.01:
                continue
            side = (row.get("posSide") or "net").lower()
            if side == "short":
                signed -= int(abs(p))
            elif side == "long":
                signed += int(abs(p))
            else:
                signed += int(round(p))
        ap = signed
        locals_open = [sid for sid in STRATEGY_IDS if t[sid].get("position")]
        if ap != 0:
            # 有持仓时封锁当前 bar，防止重启后同一 bar 内重复开仓
            last_global_entry_bar = int(time.time()) // 900 * 900
        if ap != 0 and locals_open:
            logger.info(
                f"启动同步: OKX net={ap}张, 本地已标记 {locals_open}，保留策略归因不重分配"
            )
        elif ap != 0:
            d = "short" if ap < 0 else "long"
            # 从 OKX 找到对应方向的第一个持仓获取均价和时间
            entry_px = 0.0
            entry_time = None
            for row in pr["data"]:
                p = float(row.get("pos") or 0)
                if abs(p) < 0.01:
                    continue
                side = (row.get("posSide") or "net").lower()
                if (d == "short" and side == "short") or (d == "long" and side == "long") or (d == "long" and ap > 0 and side == "net"):
                    entry_px = float(row.get("avgPx", 0))
                    ctime_ms = row.get("cTime")
                    entry_time = float(ctime_ms) / 1000.0 if ctime_ms else None
                    break
            for sid in STRATEGY_IDS:
                if not t[sid]["position"]:
                    t[sid]["position"] = True
                    t[sid]["direction"] = d
                    t[sid]["entry_price"] = entry_px
                    if entry_time:
                        t[sid]["entry_time"] = entry_time
                    logger.info(f"[同步] {sid} 已标记 {d} 仓位 @ {entry_px} (本地无持仓)")
                    save_all(t)
                    break
            logger.info(f"启动同步: OKX有{ap}张 → 已归首个空闲策略")
        elif ap == 0 and locals_open:
            logger.warning(
                f"启动同步: OKX net=0 但本地仍标记持仓 {locals_open}，清理本地幽灵仓"
            )
            for sid in locals_open:
                reset_position(t[sid])
            save_all(t)
except Exception as e:
    logger.warning(f"启动同步异常: {e}")


def _direction_sync_check(tracker):
    """对比 grp() 与本地 state 方向一致性，漂移时自动纠正。"""
    try:
        o_net = grp()
        if o_net is None:
            return
        l_net = local_net_qty(tracker)
        if o_net == 0 and l_net != 0:
            logger.warning(f"[方向同步] OKX net=0 但本地净仓={l_net}，清理幽灵仓")
            for sid, tr in tracker.items():
                if tr.get("position"):
                    reset_position(tr)
            save_all(tracker)
            return
        if o_net != 0 and l_net == 0:
            logger.warning(f"[方向同步] OKX net={o_net} 但本地净仓=0，跳过（等待启动同步归因）")
            return
        if o_net != 0 and l_net != 0 and (o_net > 0) != (l_net > 0):
            logger.critical(
                f"[方向同步] 方向漂移! OKX net={o_net} 本地净仓={l_net} "
                f"— 以 OKX 为准修正本地方向"
            )
            correct_dir = "short" if o_net < 0 else "long"
            for sid, tr in tracker.items():
                if tr.get("position") and tr.get("direction") != correct_dir:
                    old = tr["direction"]
                    tr["direction"] = correct_dir
                    logger.info(f"  [修正] {sid} {old} → {correct_dir}")
            save_all(tracker)
    except Exception as e:
        logger.error(f"[方向同步] 异常: {e}")


error_strike = 0
MAX_ERROR_STRIKE = 5

while True:
    try:
        r = fc()
        if not r: time.sleep(POLLING_INTERVAL); continue
        o, h, l, c, v, ts = r
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
                price_src = "SNAP"
        now = time.strftime("%H:%M:%S"); nt = ct

        # 权益金巡检
        if nt - last_equity_check > EQUITY_CHECK_INTERVAL:
            last_equity_check = nt
            eq = client.get_total_equity()
            if eq is not None:
                equity_fail_count = 0
                logger.info(f"资金巡检: ${eq:.2f} | 阈值: ${MIN_EQUITY_THRESHOLD}")
                if eq <= MIN_EQUITY_THRESHOLD:
                    if ALLOW_NEW_POSITIONS:
                        logger.critical(f"权益金${eq:.2f}跌破阈值${MIN_EQUITY_THRESHOLD}! 熔断!")
                    ALLOW_NEW_POSITIONS = False
                else:
                    if not ALLOW_NEW_POSITIONS: logger.info("权益金恢复, 恢复开仓")
                    ALLOW_NEW_POSITIONS = True
            else:
                equity_fail_count += 1
                if equity_fail_count >= 3:
                    if ALLOW_NEW_POSITIONS:
                        logger.critical(f"连续{equity_fail_count}次获取权益金失败, 熔断!")
                    ALLOW_NEW_POSITIONS = False

        # 仓位同步
        if nt - last_pos_check > 60:
            last_pos_check = nt
            reload_tracker_from_disk_if_changed(t)
            _direction_sync_check(t)  # 方向一致性校验（含自动修正）
            rp = grp()
            if rp is not None:
                pp = count_open_positions(t)
                lq = local_net_qty(t)
                if rp == 0 and pp > 0 and loop_count > 3:
                    logger.warning(f"[pos_sync] OKX net=0 但本地{pp}策略持仓，清理幽灵仓")
                    for sid in STRATEGY_IDS:
                        if t[sid]["position"]:
                            reset_position(t[sid])
                            cooldown[sid] = nt + 300  # 防立即被对账重新标记
                    save_all(t)
                    _save_cooldown(cooldown)
                elif rp != 0 and lq != rp and loop_count > 3:
                    logger.critical(
                        f"[pos_sync] OKX net={rp}张 != 本地折算={lq}张 "
                        f"(持仓策略={[s for s in STRATEGY_IDS if t[s].get('position')]})"
                    )
                    if nt - last_auto_reconcile > 90:
                        last_auto_reconcile = nt
                        _schedule_okx_reconcile(f"net={rp}_local={lq}")

        for sid in STRATEGY_IDS:
            snap["prev_K"] = prev_ks.get(sid, snap["SRSI_K"]); snap["prev_D"] = prev_ds.get(sid, snap["SRSI_D"])
            snap["prev_EMA9"] = prev_ema9.get(sid, snap.get("EMA9", price)); snap["prev_EMA21"] = snap["EMA21"]
            tr = t[sid]
            if cooldown.get(sid, 0) > nt and not tr["position"]: continue
            if not tr["position"]:
                if not ALLOW_NEW_POSITIONS: continue
                ok_open, skip_reason = can_open_new_position(sid, t, kt)
                if not ok_open:
                    if skip_reason == "global_bar_dedupe":
                        logger.info(f"GLOBAL_DEDUPE_SKIP sid={sid} bar={kt}")
                    elif skip_reason not in ("fuse_off",):
                        logger.info(f"ENTRY_SKIP sid={sid} reason={skip_reason} bar={kt}")
                    continue
                ed = None
                if sid == "003":
                    if len(c) < 14: continue
                    ed = check_entry("003", snap)
                else:
                    ed = check_entry(sid, snap)
                if ed:
                    ok_open, skip_reason = can_open_new_position(sid, t, kt)
                    if not ok_open:
                        logger.info(f"ENTRY_SKIP sid={sid} reason={skip_reason}_post_signal bar={kt}")
                        continue
                    # long_short_mode下方向冲突检查：OKX已有反方向持仓则拦截
                    okx_net = grp()
                    if okx_net is not None and okx_net != 0:
                        if (ed == "long" and okx_net < -1) or (ed == "short" and okx_net > 1):
                            logger.warning(f"⚠️ 方向冲突拦截: {sid} {ed} 但OKX net={okx_net}")
                            continue
                    # 风控
                    if snap["ADX"] < 20:
                        logger.warning(f"⚠️ 风控拦截: {sid} {ed} ADX={snap['ADX']:.0f}<20")
                        continue
                    close_price = snap.get("close", 0)
                    vwap_val = snap.get("VWAP", 0)
                    if vwap_val > 0 and close_price > 0:
                        vwap_deviation = abs(close_price - vwap_val) / close_price
                        if vwap_deviation > 0.012 and snap["ADX"] < 18:
                            logger.warning(f"⚠️ VWAP偏离拦截: {sid} {ed} 偏离={vwap_deviation*100:.2f}% ADX={snap['ADX']:.1f}")
                            continue
                    atr_val = snap.get("ATR", 0)
                    if not risk_control_check(sid, ed, close_price, atr_val):
                        logger.warning(f"风控拦截，未执行开仓: {sid} {ed}")
                        continue
                    if tr["position"]: continue
                    pool = BUDGET_CONFIG.get("POOL_009_012", {})
                    if sid in pool.get("members", []):
                        rp = grp()
                        if rp is None:
                            logger.warning(f"[{now}] 实盘异常, 跳过{sid}")
                            continue
                        if rp != 0:
                            logger.warning(f"[{now}] {sid}(共享池)信号但OKX已有{abs(rp)}张, 跳过")
                            continue
                    if not ca(sid, t):
                        logger.warning(f"[{now}] {sid} {ed}信号触发, 额度不足, 拦截")
                        continue

                    # === 唯一sz来源：calc_order_sz ===
                    current_price = close_price
                    dyn_sz = calc_order_sz(sid, current_price, ed)
                    if dyn_sz <= 0:
                        logger.warning(f"[{now}] {sid} {ed} sz=0，跳过开仓")
                        continue

                    side = "buy" if ed == "long" else "sell"
                    planned_sz = dyn_sz
                    logger.info(f"[开盘模拟] {sid} {ed} planned_sz={planned_sz} price=${current_price:.0f} eq=${strategy_eq.get(sid,0):.2f}")
                    res = client.place_order(sid, "open", side, dyn_sz, direction=ed)
                    if res and res.get("code") == "0":
                        ord_id = res["data"][0]["ordId"]
                        if tr["position"]: continue
                        last_global_entry_bar = kt
                        last_signal_bar[sid] = kt
                        tr["position"] = True
                        tr["direction"] = ed
                        tr["entry_price"] = current_price
                        tr["margin_locked"] = (dyn_sz * current_price * 0.01) / 5
                        tr["entry_time"] = time.time()
                        tr["qty"] = float(dyn_sz)
                        tr["open_ord_id"] = ord_id
                        tr["tranche_id"] = f"{sid}-{int(tr['entry_time'] * 1000)}-1"
                        logger.info(f"[保证金锁定] {sid} margin_locked={tr['margin_locked']:.2f}")
                        save_all(t)
                        logger.info(f"执行开仓: {sid} {ed} @ {current_price} (ordId={ord_id})")

                        time.sleep(2)
                        log_trade_after_fill(sid, ed, ord_id, "open")

                        logger.info(f"[{now}] {sid} 开{ed} ${price:.0f} (planned={planned_sz}张)")
                    else:
                        logger.error(f"[{now}] {sid} 开{ed}失败")
                        # 开仓失败后短冷却防连续重试
                        cooldown[sid] = nt + 60
                        _save_cooldown(cooldown)
                        logger.info(f"ENTRY_FAIL_COOLDOWN sid={sid} until={cooldown[sid]} reason=failed_response")
            else:
                ep = tr["entry_price"]
                snap["breakeven"] = tr.get("breakeven", False)
                exit_now = check_exit(sid, snap, ep, tr.get("direction", "long"), time.time() - tr.get("entry_time", time.time()))
                exit_reason = "平仓信号" if exit_now else ""
                if not exit_now and sid in ("009", "010") and not tr.get("breakeven", False) and (ep > 0 and (float(price) - ep) / ep >= 0.008):
                    tr["breakeven"] = True
                    save_all(t)
                    logger.info(f"[{now}] {sid} 保本锁触发, 止损上移至成本价")
                if exit_now:
                    # ====== SAFE_LOCK 按策略白名单拦截 ======
                    if sid in SAFE_LOCK_BLOCK_LIST:
                        logger.info(f"[SAFE_LOCK] BLOCKED {sid} 触发平仓信号 (ep={ep} price={price}) 白名单={SAFE_LOCK_BLOCK_LIST}")
                        continue
                    else:
                        logger.info(f"[SAFE_LOCK] PASS {sid} 允许平仓 (ep={ep} price={price}) 白名单={SAFE_LOCK_BLOCK_LIST}")
                    # ===========================================
                    xs = "sell" if tr.get("direction", "long") == "long" else "buy"
                    pos_dir = tr.get("direction", "long")
                    pos_qty = float(tr.get("remaining_qty", tr.get("qty", 1)) or 1)
                    close_sz = max(1, int(round(pos_qty)))
                    # long_short_mode下直接用策略本地qty平仓，不依赖OKX net
                    logger.info(
                        f"[{now}] {sid} 策略独立一次平仓 sz={close_sz} "
                        f"(remaining={pos_qty})"
                    )
                    res = client.place_order(sid, "close", xs, close_sz, direction=pos_dir)
                    if res and res.get("code") == "0":
                        close_ord_id = res["data"][0]["ordId"]
                        close_snapshot = dict(tr)
                        pos_qty = float(tr.get("qty", 1) or 1)
                        if close_sz >= pos_qty - 1e-6:
                            reset_position(tr)
                            cooldown[sid] = nt + 900
                            _save_cooldown(cooldown)
                        else:
                            tr["qty"] = round(pos_qty - close_sz, 4)
                            tr["margin_locked"] = (tr["qty"] * float(tr.get("entry_price", 0) or 0) * 0.01) / 5
                            logger.info(f"[{now}] {sid} 部分平仓 剩余qty={tr['qty']}")
                        save_all(t)
                        logger.info(f"执行平仓: {sid} @ {price} | 原因: 平仓信号 (ordId={close_ord_id})")

                        # 后置获取平仓真实 fill（禁止估算改预算 — 由 state/战报回补）
                        time.sleep(2)
                        fills_data = _fetch_close_fills(close_ord_id)
                        if fills_data:
                            open_oid = (close_snapshot.get("open_ord_id") or "").strip()
                            open_fills = _fetch_close_fills(open_oid) if open_oid else None
                            exit_px = float(fills_data.get("avgPx") or price)
                            open_px = float(open_fills["avgPx"]) if open_fills else float(ep or 0)
                            open_sz = float(open_fills["totalSz"]) if open_fills else float(close_snapshot.get("qty", 1) or 1)
                            total_sz = min(float(fills_data["totalSz"]), open_sz)
                            fee = float(fills_data.get("fee") or 0)
                            pos_dir = close_snapshot.get("direction", "long")
                            close_snapshot["entry_price"] = open_px
                            close_snapshot["qty"] = total_sz
                            try:
                                from build_war_report import attributed_pnl_from_prices
                                attr_pnl = attributed_pnl_from_prices(
                                    pos_dir, open_px, exit_px, total_sz, fee
                                )
                            except Exception:
                                attr_pnl = None
                            if attr_pnl is None:
                                logger.critical(
                                    f"[{now}] {sid} 平仓归因失败 open={open_px} exit={exit_px} "
                                    f"— 跳过战报写入，待全量 repair"
                                )
                                continue
                            fill_pnl = attr_pnl
                            ct_val = client.get_ct_val()
                            update_strategy_pnl(sid, fill_pnl, open_px, total_sz, ct_val)
                            eq_after = _equity_after_close(sid)
                            try:
                                from position_state import record_close_leg
                                from build_war_report import (
                                    append_realized_leg,
                                    finalize_close_leg_from_fills,
                                    sync_leg_to_state,
                                )
                                fill_ms = int(fills_data.get("fillTime") or 0)
                                close_ts = fill_ms / 1000.0 if fill_ms else None
                                leg = record_close_leg(
                                    sid, close_snapshot, close_ord_id,
                                    fill_pnl, fee,
                                    exit_px,
                                    "bot平仓",
                                    _log_dir,
                                    equity_after=eq_after,
                                    close_qty=total_sz,
                                    close_time=close_ts,
                                )
                                if leg:
                                    leg, ok, vreason = finalize_close_leg_from_fills(leg)
                                    if not ok:
                                        logger.warning(
                                            f"[war] leg OKX校验未通过 sid={sid} "
                                            f"close={close_ord_id} reason={vreason}"
                                        )
                                    else:
                                        sync_leg_to_state(leg, _log_dir)
                                        if append_realized_leg(leg):
                                            logger.info(
                                                f"[trades] OKX校验写入 {sid} "
                                                f"ep={leg.get('entry_price')} xp={leg.get('exit_price')} "
                                                f"pnl={leg.get('net_pnl')} eq=${eq_after:.2f}"
                                            )
                                            _schedule_war_refresh(sid)
                            except Exception as ex:
                                logger.warning(f"[state/trades] close leg failed: {ex}")
                            okx_pnl = fills_data["fillPnl"]
                            if attr_pnl is not None and abs(attr_pnl - okx_pnl) >= 0.01:
                                logger.info(
                                    f"[{now}] {sid} 平仓 策略归因={fill_pnl:.2f}USDT "
                                    f"(OKX fillPnl={okx_pnl:.2f}) "
                                    f"[策略归因=价差×张数|OKX=本次fill实现盈亏] 冷却15m"
                                )
                            else:
                                logger.info(f"[{now}] {sid} 平仓 真实fillPnl={fill_pnl:.2f}USDT 冷却15m")
                        else:
                            logger.critical(
                                f"[{now}] {sid} 平仓后fills不可用 ordId={close_ord_id} — "
                                f"跳过预算更新(安全)；待 state/战报回补或人工核对"
                            )
                    else:
                        # 平仓失败：检查是否是 51169（方向无市）
                        scode = ""
                        if res and res.get("data"):
                            scode = res["data"][0].get("sCode", "")
                        if scode == "51169":
                            logger.warning(
                                f"[{now}] {sid} 平仓sCode=51169(方向无市) — "
                                f"OKX无{tr.get('direction','?')}方向持仓，清理本地仓"
                            )
                            reset_position(tr)
                            cooldown[sid] = nt + 900
                            _save_cooldown(cooldown)
                            save_all(t)
                        else:
                            logger.error(f"[{now}] {sid} 平仓失败 (sCode={scode})")
            prev_ks[sid] = snap["SRSI_K"]; prev_ds[sid] = snap["SRSI_D"]

        # OKX 持仓方向日志
        try:
            pr = client.request("GET", f"/api/v5/account/positions?instId={SYMBOL}")
            if pr.get("code") == "0" and pr.get("data"):
                for row in pr["data"]:
                    p = float(row.get("pos") or 0)
                    if abs(p) > 0.01:
                        logger.info(
                            f"[OKX持仓] posSide={row.get('posSide','?')} "
                            f"pos={int(p)} avgPx={row.get('avgPx','?')}"
                        )
        except Exception as e:
            logger.warning(f"[OKX持仓] 查询异常: {e}")

        parts = []
        for s, tr in t.items():
            lbl = "多" if tr["position"] and tr.get("direction", "long") == "long" else ("空" if tr["position"] else "O")
            cl = "C" if cooldown.get(s, 0) > nt else ""
            lock = "L" if not ALLOW_NEW_POSITIONS else ""
            eq_info = f"${strategy_eq.get(s,0):.0f}"
            parts.append(f"{s}:{lbl}{cl}{lock}({eq_info})")
        src = price_src
        logger.info(f"[{now}] BTC ${price:.0f}({src}) K:{snap['SRSI_K']:.1f} D:{snap['SRSI_D']:.1f} ADX:{snap['ADX']:.0f} | {' | '.join(parts)}")
    except Exception as e:
        error_strike += 1
        logger.error(f"异常 ({error_strike}/{MAX_ERROR_STRIKE}): {e}")
        import traceback; traceback.print_exc()
        if error_strike >= MAX_ERROR_STRIKE:
            logger.critical(
                f"连续{MAX_ERROR_STRIKE}次异常, 主动退出让systemd重启"
            )
            sys.exit(1)
        sleep_t = POLLING_INTERVAL * (2 ** (error_strike - 1))
        logger.warning(f"异常指数退避 {sleep_t}s")
        time.sleep(sleep_t)
        continue
    loop_count += 1
    error_strike = 0
    time.sleep(POLLING_INTERVAL)
