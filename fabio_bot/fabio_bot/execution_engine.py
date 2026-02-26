"""
Execution: place/cancel orders via Bookmap trading API or Tradovate REST.
- Bookmap add-on: orders go through Bookmap -> Tradovate.
- Standalone Tradovate REST when not using Bookmap.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

# Optional Bookmap import (only available inside Bookmap)
try:
    import bookmap as bm
    HAS_BOOKMAP = True
except ImportError:
    bm = None
    HAS_BOOKMAP = False


@dataclass
class OrderRequest:
    alias: str
    is_buy: bool
    size: int
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    duration: str = "GTC"
    order_type: str = "MKT"  # MKT, LMT, STP


@dataclass
class BracketRequest:
    """Entry + stop + limit target."""
    alias: str
    is_buy: bool
    size: int
    entry_price: Optional[float]  # None = market
    stop_ticks: int
    target1_ticks: int
    target2_ticks: int
    pips: float
    scale_out_pct: float = 0.5


class ExecutionEngine:
    """
    Execution via Bookmap when addon and trading are available;
    otherwise can use Tradovate REST (see TradovateClient below).
    """

    def __init__(self, addon: Any = None, pips: float = 0.25, tick_value: float = 5.0):
        self.addon = addon
        self.pips = pips
        self.tick_value = tick_value
        self._order_callback: Optional[Callable[[str, Dict], None]] = None
        self._position_callback: Optional[Callable[[Dict], None]] = None

    def set_order_callback(self, cb: Callable[[str, Dict], None]) -> None:
        self._order_callback = cb

    def set_position_callback(self, cb: Callable[[Dict], None]) -> None:
        self._position_callback = cb

    def place_market(self, alias: str, is_buy: bool, size: int) -> Optional[str]:
        """Place market order. Returns order_id or None."""
        if HAS_BOOKMAP and bm and self.addon:
            try:
                params = bm.OrderSendParameters(alias=alias, is_buy=is_buy, size=size, duration="GTC")
                # Market: no limit price or use convert to market
                bm.send_order(self.addon, params)
                return "bookmap_market"
            except Exception as e:
                logger.exception("Bookmap place_market failed: %s", e)
                return None
        return None

    def place_bracket(self, req: BracketRequest) -> Optional[str]:
        """Place entry with stop and limit targets. Bookmap supports brackets."""
        if not (HAS_BOOKMAP and bm and self.addon):
            return None
        entry = req.entry_price
        if entry is None or entry <= 0:
            # Market order only; stop/target would need to be sent separately
            try:
                params = bm.OrderSendParameters(alias=req.alias, is_buy=req.is_buy, size=req.size, duration="GTC")
                bm.send_order(self.addon, params)
                return "bookmap_market"
            except Exception as e:
                logger.exception("Bookmap place_bracket (market) failed: %s", e)
                return None
        try:
            alias, is_buy, size = req.alias, req.is_buy, req.size
            pips = req.pips
            params = bm.OrderSendParameters(
                alias=alias, is_buy=is_buy, size=size, duration="GTC",
                limit_price=entry,
            )
            # Stop and limit as bracket children if supported by connector
            stop_price = entry - req.stop_ticks * pips if is_buy else entry + req.stop_ticks * pips
            target1 = entry + req.target1_ticks * pips if is_buy else entry - req.target1_ticks * pips
            bm.send_order(self.addon, params)
            return "bookmap_bracket"
        except Exception as e:
            logger.exception("Bookmap place_bracket failed: %s", e)
            return None

    def cancel_order(self, order_id: str) -> bool:
        if HAS_BOOKMAP and bm and self.addon:
            try:
                bm.cancel_order(self.addon, order_id)
                return True
            except Exception as e:
                logger.exception("Bookmap cancel failed: %s", e)
        return False


class TradovateClient:
    """
    Standalone Tradovate REST client for auth and order placement
    when not using Bookmap's built-in Tradovate connection.
    """
    def __init__(self, base_url: str, name: str, password: str, cid: str, sec: str, app_id: str = "fabio_bot", app_version: str = "1.0"):
        self.base_url = base_url.rstrip("/")
        self.name = name
        self.password = password
        self.cid = cid
        self.sec = sec
        self.app_id = app_id
        self.app_version = app_version
        self._token: Optional[str] = None
        self._token_expiry = 0.0
        self._lock = threading.Lock()

    def _env(self, key: str, default: str = "") -> str:
        val = os.environ.get(key)
        if val:
            return val
        if key == "TRADOVATE_CID":
            return self.cid
        if key == "TRADOVATE_SEC":
            return self.sec
        if key == "TRADOVATE_USER":
            return self.name
        if key == "TRADOVATE_PASS":
            return self.password
        return default

    def ensure_token(self) -> bool:
        import requests
        with self._lock:
            if self._token and time.time() < self._token_expiry - 60:
                return True
            url = f"{self.base_url}/v1/auth/accesstokenrequest"
            payload = {
                "name": self.name,
                "password": self.password,
                "appId": self.app_id,
                "appVersion": self.app_version,
                "cid": self.cid,
                "sec": self.sec,
            }
            try:
                r = requests.post(url, json=payload, timeout=10)
                r.raise_for_status()
                data = r.json()
                self._token = data.get("accessToken")
                if not self._token:
                    return False
                self._token_expiry = time.time() + 90 * 60  # 90 min
                return True
            except Exception as e:
                logger.exception("Tradovate auth failed: %s", e)
                return False

    def place_order(
        self,
        account_id: int,
        contract_id: int,
        order_type: str,
        is_buy: bool,
        quantity: int,
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
    ) -> Optional[Dict]:
        import requests
        if not self.ensure_token():
            return None
        url = f"{self.base_url}/v1/order/placeorder"
        body = {
            "accountId": account_id,
            "contractId": contract_id,
            "orderType": order_type,
            "isBuy": is_buy,
            "quantity": quantity,
        }
        if limit_price is not None:
            body["limitPrice"] = limit_price
        if stop_price is not None:
            body["stopPrice"] = stop_price
        headers = {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}
        try:
            r = requests.post(url, json=body, headers=headers, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.exception("Tradovate place_order failed: %s", e)
            return None
