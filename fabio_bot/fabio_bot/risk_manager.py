"""
Risk management: position sizing, drawdown limits, consecutive loss halt, session checks.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class RiskState:
    """Mutable risk state for the session."""
    daily_pnl: float = 0.0
    daily_trades: int = 0
    consecutive_losses: int = 0
    session_start_equity: float = 0.0
    peak_equity: float = 0.0
    is_paused: bool = False
    is_halted: bool = False


class RiskManager:
    """
    Enforce:
    - Max risk % per trade (position size from ATR stop)
    - Max daily drawdown % (pause bot)
    - Max consecutive losses (halt)
    - Max daily trades
    - Session hours (no trading outside)
    """

    def __init__(
        self,
        risk_pct: float = 0.01,
        max_daily_drawdown_pct: float = 0.03,
        max_consecutive_losses: int = 3,
        max_daily_trades: int = 20,
        session_start: str = "09:30",
        session_end: str = "16:00",
        tick_value: float = 5.0,
        use_globex: bool = False,
    ):
        self.risk_pct = risk_pct
        self.max_daily_drawdown_pct = max_daily_drawdown_pct
        self.max_consecutive_losses = max_consecutive_losses
        self.max_daily_trades = max_daily_trades
        self.tick_value = tick_value
        self.use_globex = use_globex
        # Parse session (ET assumed; no TZ handling here - caller can pass ET now)
        self._session_start = self._parse_time(session_start)
        self._session_end = self._parse_time(session_end)
        self._state = RiskState()

    @staticmethod
    def _parse_time(s: str) -> time:
        parts = s.strip().split(":")
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
        return time(h, m)

    def in_session(self, now: Optional[datetime] = None) -> bool:
        """True if current time (ET) is within session. Pass datetime in ET."""
        t = (now or datetime.now()).time()
        if self.use_globex:
            return True
        if self._session_start <= self._session_end:
            return self._session_start <= t <= self._session_end
        return t >= self._session_start or t <= self._session_end

    def position_size(
        self,
        account_balance: float,
        stop_ticks: int,
        pips: float,
        max_contracts: int = 10,
    ) -> int:
        """
        Size = (Account * risk_pct) / (stop_ticks * pips * tick_value).
        Returns contract count (int >= 1, or 0 if risk too high).
        """
        if account_balance <= 0 or stop_ticks <= 0 or pips <= 0:
            return 0
        risk_dollars = account_balance * self.risk_pct
        risk_per_contract = stop_ticks * pips * self.tick_value
        if risk_per_contract <= 0:
            return 0
        size = int(risk_dollars / risk_per_contract)
        size = max(0, min(size, max_contracts))
        return max(1, size) if size > 0 else 0

    def set_session_equity(self, equity: float) -> None:
        self._state.session_start_equity = equity
        self._state.peak_equity = equity

    def update_equity(self, equity: float) -> None:
        self._state.peak_equity = max(self._state.peak_equity, equity)

    def record_trade(self, pnl: float) -> None:
        self._state.daily_pnl += pnl
        self._state.daily_trades += 1
        if pnl < 0:
            self._state.consecutive_losses += 1
        else:
            self._state.consecutive_losses = 0

    def can_trade(self, current_equity: float) -> tuple[bool, str]:
        """
        Returns (allowed, reason). If not allowed, reason explains why.
        """
        if self._state.is_halted:
            return False, "halted_consecutive_losses"
        if self._state.is_paused:
            return False, "paused_daily_drawdown"
        if self._state.daily_trades >= self.max_daily_trades:
            return False, "max_daily_trades"
        if not self.in_session():
            return False, "outside_session"
        # Drawdown check: pause when down max_daily_drawdown_pct from peak (caps reported max DD)
        self.update_equity(current_equity)
        if self._state.peak_equity > 0:
            dd_from_peak = (self._state.peak_equity - current_equity) / self._state.peak_equity
            if dd_from_peak >= self.max_daily_drawdown_pct:
                self._state.is_paused = True
                return False, "daily_drawdown_limit"
        if self._state.consecutive_losses >= self.max_consecutive_losses:
            self._state.is_halted = True
            return False, "consecutive_losses"
        return True, "ok"

    def reset_daily(self) -> None:
        """Call at session start (e.g. 9:30 ET)."""
        self._state.daily_pnl = 0.0
        self._state.daily_trades = 0
        self._state.consecutive_losses = 0
        self._state.is_paused = False
        self._state.is_halted = False

    def get_state(self) -> RiskState:
        return self._state
