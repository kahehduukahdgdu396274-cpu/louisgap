"""OKX bot config — secrets loaded from .env only (chmod 600)."""
import os
from pathlib import Path


def _load_env():
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        raise RuntimeError(
            f"Missing {env_path}. Copy from config.env.example and set OKX_* keys."
        )
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key, val = key.strip(), val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


_load_env()

API_KEY = os.environ["OKX_API_KEY"]
SECRET_KEY = os.environ["OKX_SECRET_KEY"]
PASSPHRASE = os.environ["OKX_PASSPHRASE"]

SYMBOL = "BTC-USDT-SWAP"
TIMEFRAME = "15m"
MARGIN_USDT = "200"
POLLING_INTERVAL = 30
STRATEGY_IDS = ["003", "006", "009", "010", "011", "012", "013", "014"]
MIN_EQUITY_THRESHOLD = 1000
EQUITY_CHECK_INTERVAL = 60
SIGNAL_VALID_BARS = 2
