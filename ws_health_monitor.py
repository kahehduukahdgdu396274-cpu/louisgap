import logging
import time
import requests
import threading
from config_sim import REST_BASE_URL, SIMULATED_HEADER

logger = logging.getLogger("HealthMonitor")


class WSHealthMonitor:
    def __init__(self, ws_client, check_interval=30, max_deviation=50, price_getter=None):
        self.ws_client = ws_client
        self.check_interval = check_interval
        self.max_deviation = max_deviation
        self.price_getter = price_getter
        self.last_heartbeat_price = None
        self.last_heartbeat_time = None
        self.running = False
        self.monitor_thread = None

    def get_rest_mark_price(self):
        try:
            url = f"{REST_BASE_URL}/api/v5/public/mark-price?instId=BTC-USDT-SWAP"
            resp = requests.get(url, headers=SIMULATED_HEADER, timeout=8)
            data = resp.json()
            if data.get("code") == "0":
                return float(data["data"][0]["markPx"]), int(data["data"][0]["ts"])
        except Exception:
            pass
        return None, None

    def _get_ws_price(self):
        if self.price_getter is not None:
            try:
                return self.price_getter()
            except Exception:
                return None
        try:
            import __main__
            return getattr(__main__, "ws_latest_price", None)
        except Exception:
            return None

    def start(self):
        if self.running:
            return
        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        logger.info("WS健康监控已启动（每30秒检查一次）")

    def _monitor_loop(self):
        while self.running:
            try:
                self.last_heartbeat_price = self._get_ws_price()
                self.last_heartbeat_time = time.time()
                if self.last_heartbeat_price is None or self.last_heartbeat_price == 0.0:
                    logger.info("[HealthCheck] WS stream not ready yet. Skipping this check cycle.")
                    time.sleep(self.check_interval)
                    continue
                rest_price, _rest_ts = self.get_rest_mark_price()
                if rest_price is None:
                    logger.warning("[HealthCheck] REST返回None")
                    time.sleep(self.check_interval)
                    continue
                deviation = abs(self.last_heartbeat_price - rest_price)
                logger.info(
                    f"[HealthCheck] WS: {self.last_heartbeat_price:.1f} | REST: {rest_price:.1f} | 偏差: {deviation:.0f}点"
                )
                if deviation > self.max_deviation:
                    logger.warning(f"[HealthCheck] WS与REST偏差过大 ({deviation:.0f}点)，需手动排查")
            except Exception as e:
                logger.warning(f"[HealthCheck] ws_price获取失败: {e}")
            time.sleep(self.check_interval)
