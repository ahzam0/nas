"""
Tradovate client for dashboard – custom API layer.
Uses Tradovate REST (auth + account/list, position/list, etc.) under the hood.
Dashboard calls our FastAPI endpoints; this client talks to Tradovate.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)


@dataclass
class _AccountInfo:
    """Same shape as Demo for api_server."""
    login: int
    balance: float
    equity: float
    margin: float
    margin_free: float
    leverage: int
    server: str
    currency: str


@dataclass
class _Position:
    ticket: int
    symbol: str
    type: int  # 0 buy, 1 sell
    volume: float
    price_open: float
    price_current: float
    sl: float
    tp: float
    profit: float
    time: int


@dataclass
class _Deal:
    ticket: int
    symbol: str
    type: int
    volume: float
    price: float
    profit: float
    time: int
    comment: str


@dataclass
class _Bar:
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: int
    spread: int = 0


class TradovateClient:
    """
    Connects to Tradovate via REST. Exposes same interface as Demo
    so api_server and dashboard work unchanged. Credentials from config (tradovate).
    """
    def __init__(
        self,
        base_url: str,
        name: str,
        password: str,
        cid: str,
        sec: str,
        symbol: str = "NQ",
        contract_id: Optional[int] = None,
        app_id: str = "fabio_bot",
        app_version: str = "1.0",
    ):
        self.base_url = base_url.rstrip("/")
        self.name = name
        self.password = password
        self.cid = cid
        self.sec = sec
        self.symbol = symbol
        self._contract_id = contract_id  # optional; for place order. Get from config or contract/list
        self.app_id = app_id
        self.app_version = app_version
        self._token: Optional[str] = None
        self._token_expiry = 0.0
        self._session = requests.Session()
        self._connected = False
        self._account_id: Optional[int] = None

    def connect(self) -> bool:
        if not self._ensure_token():
            return False
        try:
            r = self._session.get(
                f"{self.base_url}/v1/account/list",
                headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json"},
                timeout=15,
            )
            r.raise_for_status()
            accounts = r.json() if r.content else []
            if isinstance(accounts, list) and len(accounts) > 0:
                self._account_id = accounts[0].get("id")
            self._connected = True
            logger.info("Tradovate connected. Symbol=%s", self.symbol)
            return True
        except Exception as e:
            logger.warning("Tradovate connect failed: %s", e)
            return False

    def _ensure_token(self) -> bool:
        if self._token and time.time() < self._token_expiry - 120:
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
            r = self._session.post(url, json=payload, timeout=15)
            r.raise_for_status()
            data = r.json()
            err = data.get("errorText") or data.get("error")
            if err:
                logger.warning("Tradovate auth error: %s", err)
                return False
            self._token = data.get("accessToken")
            if not self._token:
                return False
            self._token_expiry = time.time() + 90 * 60
            return True
        except Exception as e:
            logger.warning("Tradovate auth failed: %s", e)
            return False

    def disconnect(self) -> None:
        self._session.close()
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def ensure_connected(self) -> bool:
        if self._connected and self._ensure_token():
            return True
        return self.connect()

    def _get(self, path: str, params: Optional[dict] = None) -> Any:
        if not self.ensure_connected():
            return None
        url = f"{self.base_url}/v1/{path.lstrip('/')}"
        try:
            r = self._session.get(
                url,
                headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json"},
                params=params,
                timeout=15,
            )
            r.raise_for_status()
            return r.json() if r.content else None
        except Exception as e:
            logger.debug("Tradovate GET %s: %s", path, e)
            return None

    def _post(self, path: str, json_body: dict) -> Any:
        if not self.ensure_connected():
            return None
        url = f"{self.base_url}/v1/{path.lstrip('/')}"
        try:
            r = self._session.post(
                url,
                headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json", "Accept": "application/json"},
                json=json_body,
                timeout=15,
            )
            r.raise_for_status()
            return r.json() if r.content else None
        except Exception as e:
            logger.debug("Tradovate POST %s: %s", path, e)
            return None

    def _resolve_contract_id(self, symbol: Optional[str] = None) -> Optional[int]:
        sym = (symbol or self.symbol).upper()
        if self._contract_id and not symbol:
            return self._contract_id
        data = self._get("contract/list")
        if not isinstance(data, list):
            return None
        for c in data:
            name = (c.get("name") or c.get("symbol") or "").upper()
            if sym in name or name == sym:
                return c.get("id")
        return None

    def get_contracts(self) -> List[dict]:
        """Return all Tradovate contracts (pairs) for symbol selector. Items: { id, name, symbol }."""
        data = self._get("contract/list")
        if not isinstance(data, list):
            return []
        out = []
        seen = set()
        for c in data:
            name = (c.get("name") or c.get("symbol") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            out.append({
                "id": c.get("id"),
                "name": name,
                "symbol": (c.get("symbol") or name).strip(),
            })
        return sorted(out, key=lambda x: (x.get("name") or ""))

    def place_market_order(self, is_buy: bool, quantity: float, comment: str = "", symbol: Optional[str] = None) -> Tuple[bool, str]:
        """Place market order. symbol optional; uses self.symbol if not set. Returns (success, message)."""
        if not self._account_id:
            return (False, "No account")
        cid = self._resolve_contract_id(symbol)
        if not cid:
            return (False, "Set tradovate.contract_id in config or add API credentials to resolve contract")
        body = {
            "accountId": self._account_id,
            "contractId": cid,
            "orderType": "MKT",
            "isBuy": is_buy,
            "quantity": int(quantity),
        }
        out = self._post("order/placeorder", body)
        if out is None:
            return (False, "Order request failed")
        err = out.get("errorText") or out.get("message")
        if err:
            return (False, str(err))
        return (True, out.get("orderId") or "Sent")

    def close_position(self, ticket: int) -> bool:
        """Close position by id."""
        out = self._post("order/liquidatePosition", {"positionId": ticket})
        return out is not None and (out.get("errorText") or out.get("error")) is None

    def get_account_info(self) -> Optional[_AccountInfo]:
        if not self.ensure_connected():
            return None
        data = self._get("account/list")
        if not isinstance(data, list) or len(data) == 0:
            return None
        acc = data[0]
        # Tradovate account list may not include balance; use margin/balance endpoints if available
        balance = float(acc.get("evaluationSize") or acc.get("balance") or 0)
        return _AccountInfo(
            login=int(acc.get("id") or 0),
            balance=balance,
            equity=balance,
            margin=0.0,
            margin_free=balance,
            leverage=0,
            server="Tradovate",
            currency="USD",
        )

    def get_positions(self, symbol: Optional[str] = None) -> List[_Position]:
        if not self.ensure_connected():
            return []
        data = self._get("position/list")
        if not isinstance(data, list):
            return []
        out = []
        for p in data:
            sym = (p.get("contract") or p.get("symbol") or "").upper() or self.symbol
            if symbol and sym != symbol.upper():
                continue
            is_buy = (p.get("positionType") or p.get("side") or "").upper().startswith("B") or p.get("quantity", 0) > 0
            qty = abs(float(p.get("quantity") or p.get("size") or 0))
            price = float(p.get("avgPrice") or p.get("price") or 0)
            pl = float(p.get("realizedPnl") or p.get("profit") or 0)
            out.append(_Position(
                ticket=int(p.get("id") or 0),
                symbol=sym,
                type=0 if is_buy else 1,
                volume=qty,
                price_open=price,
                price_current=price,
                sl=0.0,
                tp=0.0,
                profit=pl,
                time=int(time.time()),
            ))
        return out

    def get_deals_history(self, days: int = 7, symbol: Optional[str] = None) -> List[_Deal]:
        if not self.ensure_connected():
            return []
        data = self._get("fill/list")
        if not isinstance(data, list):
            return []
        out = []
        for f in data[:200]:
            sym = (f.get("contractSymbol") or f.get("symbol") or self.symbol).upper()
            if symbol and sym != symbol.upper():
                continue
            is_buy = (f.get("side") or "").upper().startswith("B") or (f.get("quantity") or 0) > 0
            qty = abs(float(f.get("quantity") or f.get("size") or 0))
            price = float(f.get("price") or 0)
            pl = float(f.get("realizedPnl") or f.get("profit") or 0)
            ts = f.get("timestamp") or f.get("time")
            if isinstance(ts, str) and "T" in ts:
                try:
                    from datetime import datetime
                    t = int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp())
                except Exception:
                    t = int(time.time())
            else:
                t = int(ts or time.time())
            out.append(_Deal(
                ticket=int(f.get("id") or 0),
                symbol=sym,
                type=0 if is_buy else 1,
                volume=qty,
                price=price,
                profit=pl,
                time=t,
                comment=f.get("orderId") or "",
            ))
        return sorted(out, key=lambda d: d.time, reverse=True)[:200]

    def get_bars(self, timeframe: str = "1m", count: int = 500, start_pos: int = 0) -> List[_Bar]:
        # Tradovate REST may have chart endpoint; stub for now
        return []

    def get_tick(self) -> Optional[Tuple[float, float, float]]:
        # Real-time tick via Tradovate WebSocket in full integration; stub for dashboard
        return (0.0, 0.0, 0.0)
