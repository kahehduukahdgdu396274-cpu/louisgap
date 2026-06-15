import requests, time, hmac, hashlib, base64, json, logging
from datetime import datetime
from config import API_KEY, SECRET_KEY, PASSPHRASE

logger = logging.getLogger("QuantBot")


class OKXClient:
    def __init__(self):
        self.base_url = "https://openapi.okx.com"
        self.api_key = API_KEY
        self.secret_key = SECRET_KEY
        self.passphrase = PASSPHRASE
        self._ct_val = None  # 缓存合约面值
        self._pos_mode = None  # 缓存账户持仓模式
        # 独立 Session，禁用连接池重用防止 half-open 挂死
        self._session = requests.Session()
        self._session.keep_alive = False
        adapter = requests.adapters.HTTPAdapter(
            max_retries=0,
            pool_connections=1,
            pool_maxsize=1,
        )
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    def _sign(self, method, path, body=""):
        ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
        msg = f"{ts}{method}{path}{body}"
        sig = base64.b64encode(hmac.new(self.secret_key.encode(), msg.encode(), hashlib.sha256).digest()).decode()
        return sig, ts

    def request(self, method, path, params=None):
        body = json.dumps(params) if params is not None else ""
        sig, ts = self._sign(method, path, body)
        headers = {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": sig,
            "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
            "x-simulated-trading": "1",
            "Connection": "close",  # 每次请求关闭连接，避免 stale pool
        }
        url = self.base_url + path
        if method == "GET":
            try:
                return self._session.get(url, headers=headers, params=params, timeout=(3.05, 10)).json()
            except requests.exceptions.Timeout:
                logger.warning(f"[API] GET超时 path={path}")
                return None
            except requests.exceptions.ConnectionError as e:
                logger.error(f"[API] GET连接失败 path={path}: {e}")
                return None
            except requests.exceptions.RequestException as e:
                logger.warning(f"[API] GET异常 path={path}: {e}")
                return None
        # POST带3次重试, 应对网关502/503/504抖动
        max_post_retry = 3 if "stop-order-algo" in path else 1
        for attempt in range(1, max_post_retry + 1):
            try:
                resp = self._session.post(url, headers=headers, data=body, timeout=(3.05, 10))
                if resp.status_code in (502, 503, 504):
                    raise requests.exceptions.RequestException(f"网关抖动 HTTP {resp.status_code}")
                return resp.json()
            except requests.exceptions.RequestException as e:
                if attempt == max_post_retry:
                    logger.critical(f"[API] 接口失联! path={path} 重试{max_post_retry}次失败: {e}")
                    raise
                logger.warning(f"[API] 网络抖动 path={path} 第{attempt}次重试...")
                time.sleep(2)

    def _get_pos_mode(self):
        """获取当前账户持仓模式并缓存 (net_mode / long_short_mode)"""
        if self._pos_mode is not None:
            return self._pos_mode
        try:
            res = self.request("GET", "/api/v5/account/config")
            if res.get("code") == "0" and res.get("data"):
                mode = res["data"][0].get("posMode", "net_mode")
                self._pos_mode = mode
                logger.info(f"[POS_MODE] 账户持仓模式 = {mode}")
                return mode
            logger.warning(f"[POS_MODE] 获取失败 code={res.get('code')}, 默认net_mode")
            return "net_mode"
        except Exception as e:
            logger.error(f"[POS_MODE] 异常: {e}")
            return "net_mode"

    def get_ct_val(self, inst_id="BTC-USDT-SWAP"):
        """从OKX获取合约面值并缓存。拉取失败则拒绝下单"""
        if self._ct_val is not None:
            return self._ct_val
        try:
            res = self.request("GET", f"/api/v5/public/instruments?instType=SWAP&instId={inst_id}")
            if res.get("code") == "0" and res.get("data"):
                ct_val = float(res["data"][0]["ctVal"])
                self._ct_val = ct_val
                logger.info(f"[CT_VAL] 合约面值 = {ct_val} (来自OKX/{inst_id})")
                return ct_val
            else:
                raise RuntimeError(f"获取ctVal失败: {res.get('msg','')}")
        except Exception as e:
            logger.critical(f"[CT_VAL] 合约面值获取异常: {e}")
            raise

    def get_total_equity(self):
        """v5.4 资金雷达：获取账户动态总权益(USDT)"""
        try:
            res = self.request("GET", "/api/v5/account/balance")
            if res.get("code") == "0" and "data" in res and res["data"]:
                total_eq = float(res["data"][0].get("totalEq", 0))
                return total_eq
            logger.error(f"资金雷达失败 code={res.get('code')}")
            return None
        except Exception as e:
            logger.error(f"资金雷达异常: {e}")
            return None

    def place_order(self, strategy_id, action, side, sz, ord_type="market", direction=None, max_retries=3):
        """
        下单（自动适配持仓模式）
        - strategy_id: 策略ID
        - action: "open" 或 "close"
        - side: "buy" 或 "sell"
        - sz: 张数（已计算好的动态值）
        - direction: "long"/"short"，用于posSide（仅在long_short_mode下生效）
        - ord_type: "market" 或 "limit"

        返回: OKX原始响应 或 None(全部重试耗尽)
        """
        is_close = (action == "close")
        if is_close:
            max_retries = 10  # 平仓重试上限10次
        ts = int(time.time() * 1000)
        cl_ord_id = f"str{strategy_id}{action}{ts}"[:32]

        p = {
            "instId": "BTC-USDT-SWAP",
            "tdMode": "cross",
            "side": side,
            "ordType": ord_type,
            "sz": str(sz),
            "clOrdId": cl_ord_id,
        }

        # 获取当前持仓模式，决定是否传posSide
        pos_mode = self._get_pos_mode()
        actual_pos_side = None
        if pos_mode == "long_short_mode":
            if direction in ("long", "short"):
                p["posSide"] = direction
                actual_pos_side = direction
        elif pos_mode == "net_mode":
            # net模式下传posSide=short会触发sCode=51000拒单
            # 主动不传posSide（OKX net模式无视posSide字段）
            p.pop("posSide", None)
            actual_pos_side = None

        # 市价单防御性脱敏
        if ord_type == "market":
            p.pop("tgtCcy", None)

        delay = 0.2
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"下单 [尝试{attempt}/{max_retries}] | {cl_ord_id} | sz={sz} side={side} posSide={actual_pos_side} posMode={pos_mode}")
                res = self.request("POST", "/api/v5/trade/order", p)
                code = res.get("code", "-1")
                msg = res.get("msg", "")
                if code == "0":
                    ord_id = res["data"][0]["ordId"]
                    logger.info(f"下单成功 ordId={ord_id} | {cl_ord_id}")
                    return res
                elif code == "1":
                    # 增强日志：记录原始拒绝原因
                    s_code = res.get("data", [{}])[0].get("sCode", "")
                    s_msg = res.get("data", [{}])[0].get("sMsg", "")
                    ord_id = res.get("data", [{}])[0].get("ordId", "")
                    logger.warning(
                        f"code=1 | {cl_ord_id} | "
                        f"side={side} sz={sz} posSide={actual_pos_side} posMode={pos_mode} | "
                        f"sCode={s_code} sMsg={s_msg} ordId={ord_id} | "
                        f"第{attempt}次重试 ({delay}s后)"
                    )
                    if is_close:
                        # 51169=方向无持仓，重试无意义，提前退出
                        if s_code == "51169":
                            logger.warning(
                                f"51169提前退出 | {cl_ord_id} | OKX无此方向持仓，终止重试"
                            )
                            return res
                        logger.critical(f"平仓code=1 第{attempt}/{max_retries}次不死不休重试! | {cl_ord_id}")
                        time.sleep(1)
                    else:
                        time.sleep(delay)
                        delay *= 2.5
                else:
                    s_code = res.get("data", [{}])[0].get("sCode", "") if res.get("data") else ""
                    s_msg = res.get("data", [{}])[0].get("sMsg", "") if res.get("data") else ""
                    ord_id = res.get("data", [{}])[0].get("ordId", "") if res.get("data") else ""
                    logger.error(
                        f"OKX拒绝 code={code} msg={msg} | {cl_ord_id} | "
                        f"side={side} sz={sz} posSide={actual_pos_side} posMode={pos_mode} | "
                        f"sCode={s_code} sMsg={s_msg} ordId={ord_id}"
                    )
                    return res
            except Exception as e:
                logger.error(f"网络异常 [尝试{attempt}]: {e}")
                time.sleep(1 if is_close else delay)
                if not is_close:
                    delay *= 2.5
        if is_close:
            logger.critical(f"平仓失败! {max_retries}次不死不休重试耗尽, 人工介入! | {cl_ord_id}")
        else:
            logger.warning(f"开仓放弃 {max_retries}次重试耗尽 | {cl_ord_id}")
        return None

    def fetch_ticker(self, symbol):
        return self.request("GET", f"/api/v5/market/ticker?instId={symbol}")

    def fetch_fills_by_ordId(self, ord_id, inst_id="BTC-USDT-SWAP", max_retries=8):
        """
        按ordId拉取成交明细，返回聚合结果
        - fills: 原始fill列表
        - avgPx: 加权均价
        - totalSz: 总成交量（张）
        - fillPnl: 总平仓盈亏（仅平仓成交有值）
        - fee: 总手续费
        """
        wait_s = 3
        paths = [
            f"/api/v5/trade/fills?instId={inst_id}&ordId={ord_id}",
            f"/api/v5/trade/fills?instId={inst_id}&limit=100",
        ]
        for attempt in range(max_retries):
            for path in paths:
                data = self.request("GET", path)
                if data.get("code") != "0":
                    continue
                matched = [f for f in (data.get("data") or []) if f.get("ordId") == ord_id]
                if not matched:
                    continue
                total_sz = sum(float(f["fillSz"]) for f in matched)
                total_px = sum(float(f["fillPx"]) * float(f["fillSz"]) for f in matched)
                total_pnl = sum(float(f.get("fillPnl", 0)) for f in matched)
                total_fee = sum(float(f.get("fee", 0)) for f in matched)
                avg_px = round(total_px / total_sz, 2) if total_sz > 0 else 0.0
                return {
                    "fills": matched,
                    "avgPx": avg_px,
                    "totalSz": total_sz,
                    "fillPnl": round(total_pnl, 2),
                    "fee": round(total_fee, 2),
                }
            time.sleep(wait_s)
        logger.error(f"[FILLS] ordId={ord_id} 未找到成交, 重试{max_retries}次后放弃")
        return None
