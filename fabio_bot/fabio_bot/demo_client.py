"""
Demo/sandbox client – same interface as TradovateClient.
Used when Tradovate is not connected, so the dashboard still loads with mock data.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

# Mirror bar shape for get_bars
@dataclass
class DemoBar:
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: int
    spread: int = 0


class _DemoAccountInfo:
    def __init__(self):
        self.login = 0
        self.balance = 10000.0
        self.equity = 10000.0
        self.margin = 0.0
        self.margin_free = 10000.0
        self.leverage = 100
        self.server = "Demo"
        self.currency = "USD"


class _DemoPosition:
    def __init__(self, ticket: int, symbol: str, is_buy: bool, volume: float, price: float, profit: float = 0.0):
        self.ticket = ticket
        self.symbol = symbol
        self.type = 0 if is_buy else 1
        self.volume = volume
        self.price_open = price
        self.price_current = price
        self.sl = 0.0
        self.tp = 0.0
        self.profit = profit
        self.time = int(time.time())


class _DemoDeal:
    def __init__(self, ticket: int, symbol: str, is_buy: bool, volume: float, price: float, profit: float, comment: str = ""):
        self.ticket = ticket
        self.symbol = symbol
        self.type = 0 if is_buy else 1
        self.volume = volume
        self.price = price
        self.profit = profit
        self.time = int(time.time()) - 3600
        self.comment = comment


class DemoClient:
    """Mock client for dashboard when live connection is unavailable."""

    def __init__(self, symbol: str = "XAUUSD"):
        self.symbol = symbol

    def connect(self) -> bool:
        return True

    def disconnect(self) -> None:
        pass

    def is_connected(self) -> bool:
        return True

    def ensure_connected(self) -> bool:
        return True

    def get_account_info(self) -> Optional[_DemoAccountInfo]:
        return _DemoAccountInfo()

    def get_positions(self, symbol: Optional[str] = None) -> List[_DemoPosition]:
        return []

    def get_deals_history(self, days: int = 7, symbol: Optional[str] = None) -> List[_DemoDeal]:
        return []

    def get_bars(
        self,
        timeframe: str = "1m",
        count: int = 500,
        start_pos: int = 0,
    ) -> List[DemoBar]:
        # Simple mock bars (flat line)
        now = int(time.time())
        out = []
        for i in range(min(count, 100)):
            t = now - (count - i) * 60
            out.append(DemoBar(time=t, open=2650.0, high=2651.0, low=2649.0, close=2650.0, volume=0))
        return out[start_pos:] if start_pos < len(out) else []

    def get_tick(self) -> Optional[Tuple[float, float, float]]:
        return (2650.0, 2650.1, 2650.05)

    def get_contracts(self):
        """Demo list of common futures symbols (Tradovate-style)."""
        return [
            {"id": None, "name": "NQ", "symbol": "NQ"},
            {"id": None, "name": "MNQ", "symbol": "MNQ"},
            {"id": None, "name": "ES", "symbol": "ES"},
            {"id": None, "name": "MES", "symbol": "MES"},
            {"id": None, "name": "CL", "symbol": "CL"},
            {"id": None, "name": "GC", "symbol": "GC"},
            {"id": None, "name": "ZB", "symbol": "ZB"},
        ]

    def place_market_order(self, is_buy: bool, volume: float, sl_price: Optional[float] = None, tp_price: Optional[float] = None, comment: str = "") -> Tuple[bool, str]:
        return (False, "Demo mode – connect Tradovate to trade")

    def close_position(self, ticket: int) -> bool:
        return False
