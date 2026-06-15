from config_sim import WS_PUBLIC, WS_PRIVATE, WS_BUSINESS
"""
ws_client.py — OKX WebSocket 客户端 (v4, 自动重连)
"""
import json, time, hmac, base64, hashlib, threading, logging
from typing import Optional, Callable
import websocket

logger = logging.getLogger(__name__)

WS_PUBLIC = "wss://wspap.okx.com:8443/ws/v5/public"
WS_PRIVATE = "wss://wspap.okx.com:8443/ws/v5/private"
WS_BUSINESS = "wss://wspap.okx.com:8443/ws/v5/business"


class OKXWebSocket:
    def __init__(self, url: str, api_key: str = "", secret_key: str = "", passphrase: str = ""):
        self.url = url
        self.last_price = None
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase
        self.ws: Optional[websocket.WebSocketApp] = None
        self.running = False
        self._should_reconnect = True
        self.handlers: dict[str, list[Callable]] = {}
        self.last_pong = 0
        self._subscribe_args: list[dict] = []
        self._reconnect_delay = 1

    def on(self, channel: str, handler: Callable):
        if channel not in self.handlers:
            self.handlers[channel] = []
        self.handlers[channel].append(handler)

    def _sign_login(self) -> str:
        ts = str(int(time.time()))
        msg = ts + "GET" + "/users/self/verify"
        sig = base64.b64encode(
            hmac.new(self.secret_key.encode(), msg.encode(), hashlib.sha256).digest()
        ).decode()
        return json.dumps({
            "op": "login",
            "args": [{"apiKey": self.api_key, "passphrase": self.passphrase, "timestamp": ts, "sign": sig}]
        })

    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
            if data.get("event") == "pong":
                self.last_pong = time.time()
                return
            if data.get("event") in ("subscribe", "login"):
                logger.info(f"WS {data.get("event")} OK: {data.get("arg", {})}")
                return
            if data.get("event") == "error":
                logger.error(f"WS error: {data.get("msg", "")}")
                return
            if "arg" in data and "data" in data:
                channel = data["arg"].get("channel", "")
                if channel in self.handlers:
                    for h in self.handlers[channel]:
                        try:
                            h(data["data"])
                        except Exception as e:
                            logger.error(f"WS handler {channel} error: {e}")
        except Exception as e:
            logger.error(f"WS parse error: {e}")

    def _on_error(self, ws, error):
        logger.error(f"WS error: {error}")

    def _on_close(self, ws, close_status_code, close_msg):
        logger.warning(f"WS closed: {close_status_code} {close_msg}")
        self.running = False

    def _on_open(self, ws):
        logger.info("WS connected")
        self.running = True
        self._reconnect_delay = 1
        if "private" in self.url and self.api_key:
            login_msg = self._sign_login()
            ws.send(login_msg)
        # 重连后重新订阅
        if self._subscribe_args:
            msg = json.dumps({"op": "subscribe", "args": self._subscribe_args})
            ws.send(msg)

    def subscribe(self, channels: list[dict]):
        self._subscribe_args = channels
        if not self.ws or not self.running:
            return
        msg = json.dumps({"op": "subscribe", "args": channels})
        self.ws.send(msg)

    def start(self):
        self._should_reconnect = True
        while self._should_reconnect:
            self.ws = websocket.WebSocketApp(
                self.url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close
            )
            logger.info(f"WS connecting to {self.url} ...")
            self.ws.run_forever(ping_interval=20, ping_timeout=10)
            self.running = False
            if self._should_reconnect:
                logger.warning(f"WS disconnected, reconnecting in {self._reconnect_delay}s ...")
                time.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 60)

    def start_bg(self):
        t = threading.Thread(target=self.start, daemon=True)
        t.start()
        return t

    def stop(self):
        self._should_reconnect = False
        self.running = False
        if self.ws:
            self.ws.close()

