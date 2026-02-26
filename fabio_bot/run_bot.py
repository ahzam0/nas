"""
Tradovate-only trading bot. Connects via config tradovate and sends heartbeat for dashboard.

  python run_bot.py
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from fabio_bot.config_loader import load_config
from fabio_bot.activity_store import heartbeat, push

CONFIG_PATH = ROOT / "config.yaml"
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "bot.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("run_bot")


def main() -> int:
    config = load_config(CONFIG_PATH) if CONFIG_PATH.exists() else {}
    tv = config.get("tradovate", {})
    name = (tv.get("username") or tv.get("name") or os.environ.get("TRADOVATE_USER") or "").strip()
    password = (tv.get("password") or os.environ.get("TRADOVATE_PASS") or "").strip()
    cid = (tv.get("client_id") or tv.get("cid") or os.environ.get("TRADOVATE_CID") or "").strip()
    sec = (tv.get("client_secret") or tv.get("sec") or os.environ.get("TRADOVATE_SEC") or "").strip()

    if not (name and password and cid and sec):
        logger.error("Tradovate credentials missing. Set tradovate in config.yaml.")
        push("error", "Tradovate credentials missing in config.")
        return 1

    try:
        from fabio_bot.tradovate_client import TradovateClient
    except ImportError as e:
        logger.error("Tradovate client not available: %s", e)
        push("error", str(e))
        return 1

    base_url = (tv.get("base_url") or os.environ.get("TRADOVATE_BASE_URL") or "https://demo.tradovateapi.com").strip()
    symbol = (tv.get("symbol") or os.environ.get("TRADOVATE_SYMBOL") or "NQ").strip()
    contract_id = tv.get("contract_id") or (int(os.environ["TRADOVATE_CONTRACT_ID"]) if os.environ.get("TRADOVATE_CONTRACT_ID") else None)

    client = TradovateClient(
        base_url=base_url,
        name=name,
        password=password,
        cid=cid,
        sec=sec,
        symbol=symbol,
        contract_id=contract_id,
        app_id=tv.get("app_id") or "fabio_bot",
        app_version=tv.get("app_version") or "1.0",
    )

    if not client.connect():
        logger.error("Tradovate connection failed. Check credentials.")
        push("error", "Tradovate connection failed.")
        return 1

    logger.info("Bot started. Symbol=%s. Sending heartbeat for dashboard.", symbol)
    push("info", "Tradovate bot started.")

    try:
        while True:
            heartbeat()
            time.sleep(30)
    except KeyboardInterrupt:
        logger.info("Bot stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
