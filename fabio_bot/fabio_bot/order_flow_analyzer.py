"""
Order flow analysis: CVD, big trades, absorption, volume profile (POC, VAH, VAL, LVN, HVN).
Designed for use with Bookmap trade/depth/MBO handlers and for backtest tick streams.
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class TradeEvent:
    """Single trade from T&S."""
    price: float
    size: float
    is_bid: bool  # True = buy (aggressor hit bid)
    ts: float = 0.0


@dataclass
class BarSnapshot:
    """Rolling bar (e.g. 15s) for delta and volume."""
    open: float
    high: float
    low: float
    close: float
    buy_volume: float
    sell_volume: float
    delta: float  # buy_volume - sell_volume
    total_volume: float
    trade_count: int
    big_buys: int
    big_sells: int


@dataclass
class VolumeProfileResult:
    """Session volume profile output."""
    poc: float              # Point of control (price with max volume)
    vah: float              # Value area high
    val: float              # Value area low
    total_volume: float
    value_pct: float        # e.g. 0.70
    by_price: Dict[float, float]  # price -> volume
    hvn_prices: List[float]  # High-volume nodes (top N)
    lvn_prices: List[float]  # Low-volume nodes (bottom N)


@dataclass
class AbsorptionState:
    """Absorption detection: large size without price movement."""
    last_price: float = 0.0
    last_size_bid: float = 0.0
    last_size_ask: float = 0.0
    unchanged_ticks: int = 0
    accumulated_bid_vol: float = 0.0
    accumulated_ask_vol: float = 0.0
    absorption_bullish: bool = False  # Sells absorbed
    absorption_bearish: bool = False  # Buys absorbed


class OrderFlowAnalyzer:
    """
    Real-time order flow state: CVD, big trades, absorption, volume profile.
    Thread-safe for single-threaded Bookmap handlers; use from one thread.
    """

    def __init__(
        self,
        pips: float,
        size_multiplier: float,
        big_trade_threshold: float = 30.0,
        absorption_ticks: int = 3,
        value_area_pct: float = 0.70,
        profile_rolling_bars: int = 120,  # e.g. 30 min at 15s bars
    ):
        self.pips = pips
        self.size_multiplier = size_multiplier
        self.big_trade_threshold = big_trade_threshold
        self.absorption_ticks = absorption_ticks
        self.value_area_pct = value_area_pct
        self.profile_rolling_bars = profile_rolling_bars

        # Session CVD (reset at session start)
        self._buy_volume = 0.0
        self._sell_volume = 0.0
        self._cvd = 0.0

        # Bar buffer for current bar
        self._current_bar: Optional[BarSnapshot] = None
        self._bar_open = 0.0
        self._bar_high = 0.0
        self._bar_low = float("inf")
        self._bar_close = 0.0
        self._bar_buy_vol = 0.0
        self._bar_sell_vol = 0.0
        self._bar_big_buys = 0
        self._bar_big_sells = 0
        self._bar_trades = 0

        # Rolling bars for volume profile
        self._bars: Deque[BarSnapshot] = deque(maxlen=profile_rolling_bars)

        # Trades at price for profile (price -> volume)
        self._volume_at_price: Dict[float, float] = {}
        self._price_level_multiplier = 1.0  # round price to levels if needed

        # Absorption
        self._absorption = AbsorptionState()

        # Recent big trades (for clustering)
        self._recent_big_trades: Deque[Tuple[float, float, bool]] = deque(maxlen=200)

        # FVG detection: gaps in price with low volume
        self._recent_highs: Deque[float] = deque(maxlen=20)
        self._recent_lows: Deque[float] = deque(maxlen=20)

    def _to_price(self, price_level: int) -> float:
        return price_level * self.pips

    def _to_size(self, size_level: int) -> float:
        return size_level / self.size_multiplier

    def on_trade(
        self,
        price_level: int,
        size_level: int,
        is_bid: bool,
    ) -> None:
        """Call from Bookmap trade handler. Updates CVD, bar, big trades, profile."""
        price = self._to_price(price_level)
        size = self._to_size(size_level)

        # CVD
        if is_bid:
            self._buy_volume += size
        else:
            self._sell_volume += size
        self._cvd = self._buy_volume - self._sell_volume

        # Bar
        if self._bar_open == 0.0:
            self._bar_open = price
        self._bar_high = max(self._bar_high, price) if self._bar_high else price
        self._bar_low = min(self._bar_low, price) if self._bar_low != float("inf") else price
        self._bar_close = price
        if is_bid:
            self._bar_buy_vol += size
            if size >= self.big_trade_threshold:
                self._bar_big_buys += 1
                self._recent_big_trades.append((price, size, True))
        else:
            self._bar_sell_vol += size
            if size >= self.big_trade_threshold:
                self._bar_big_sells += 1
                self._recent_big_trades.append((price, size, False))
        self._bar_trades += 1

        # Volume at price (for profile)
        p = round(price / self.pips) * self.pips
        self._volume_at_price[p] = self._volume_at_price.get(p, 0) + size

        # Absorption: same price level with lots of size
        if self._absorption.last_price == 0:
            self._absorption.last_price = price
        if abs(price - self._absorption.last_price) <= self.absorption_ticks * self.pips:
            self._absorption.unchanged_ticks += 1
            if is_bid:
                self._absorption.accumulated_bid_vol += size
            else:
                self._absorption.accumulated_ask_vol += size
        else:
            self._absorption.unchanged_ticks = 0
            self._absorption.accumulated_bid_vol = size if is_bid else 0
            self._absorption.accumulated_ask_vol = size if not is_bid else 0
            self._absorption.last_price = price
        self._absorption.absorption_bullish = (
            self._absorption.unchanged_ticks >= self.absorption_ticks
            and self._absorption.accumulated_ask_vol > self._absorption.accumulated_bid_vol * 1.5
        )
        self._absorption.absorption_bearish = (
            self._absorption.unchanged_ticks >= self.absorption_ticks
            and self._absorption.accumulated_bid_vol > self._absorption.accumulated_ask_vol * 1.5
        )

    def start_new_bar(self) -> Optional[BarSnapshot]:
        """Call on interval (e.g. every 15s). Commits current bar and returns it."""
        if self._bar_open == 0.0:
            return None
        snap = BarSnapshot(
            open=self._bar_open,
            high=self._bar_high,
            low=self._bar_low,
            close=self._bar_close,
            buy_volume=self._bar_buy_vol,
            sell_volume=self._bar_sell_vol,
            delta=self._bar_buy_vol - self._bar_sell_vol,
            total_volume=self._bar_buy_vol + self._bar_sell_vol,
            trade_count=self._bar_trades,
            big_buys=self._bar_big_buys,
            big_sells=self._bar_big_sells,
        )
        self._bars.append(snap)
        self._current_bar = snap
        # Reset bar
        self._bar_open = self._bar_close
        self._bar_high = self._bar_close
        self._bar_low = self._bar_close
        self._bar_buy_vol = 0.0
        self._bar_sell_vol = 0.0
        self._bar_big_buys = 0
        self._bar_big_sells = 0
        self._bar_trades = 0
        return snap

    def get_cvd(self) -> float:
        return self._cvd

    def get_bar_delta(self) -> float:
        return self._bar_buy_vol - self._bar_sell_vol

    def get_current_bar(self) -> Optional[BarSnapshot]:
        return self._current_bar

    def get_recent_bars(self, n: int = 20) -> List[BarSnapshot]:
        return list(self._bars)[-n:]

    def get_big_trade_cluster(self, lookback: int = 30) -> Tuple[int, int]:
        """Count big buys and big sells in recent trades."""
        recent = list(self._recent_big_trades)[-lookback:]
        buys = sum(1 for _, _, is_buy in recent if is_buy)
        sells = sum(1 for _, _, is_buy in recent if not is_buy)
        return buys, sells

    def get_absorption(self) -> AbsorptionState:
        return self._absorption

    def build_volume_profile(self) -> VolumeProfileResult:
        """Build profile from current volume_at_price (session or rolling)."""
        if not self._volume_at_price:
            return VolumeProfileResult(
                poc=0.0, vah=0.0, val=0.0, total_volume=0.0, value_pct=self.value_area_pct,
                by_price={}, hvn_prices=[], lvn_prices=[],
            )
        by_price = dict(self._volume_at_price)
        total = sum(by_price.values())
        if total == 0:
            return VolumeProfileResult(
                poc=0.0, vah=0.0, val=0.0, total_volume=0.0, value_pct=self.value_area_pct,
                by_price=by_price, hvn_prices=[], lvn_prices=[],
            )
        poc_price = max(by_price, key=by_price.get)
        # Value area: 70% of volume around POC (expand from POC until we have value_pct of volume)
        sorted_prices = sorted(by_price.keys())
        target_vol = total * self.value_area_pct
        idx_poc = sorted_prices.index(poc_price)
        vol_so_far = by_price[poc_price]
        lo, hi = idx_poc, idx_poc
        while vol_so_far < target_vol and (lo > 0 or hi < len(sorted_prices) - 1):
            add_lo = by_price[sorted_prices[lo - 1]] if lo > 0 else 0
            add_hi = by_price[sorted_prices[hi + 1]] if hi < len(sorted_prices) - 1 else 0
            if add_lo >= add_hi and lo > 0:
                lo -= 1
                vol_so_far += add_lo
            elif hi < len(sorted_prices) - 1:
                hi += 1
                vol_so_far += add_hi
            elif lo > 0:
                lo -= 1
                vol_so_far += add_lo
            else:
                break
        val = sorted_prices[lo]
        vah = sorted_prices[hi]
        # HVN: top 5 price levels by volume; LVN: bottom 5
        by_vol = sorted(by_price.items(), key=lambda x: -x[1])
        hvn_prices = [p for p, _ in by_vol[:5]]
        lvn_prices = [p for p, _ in by_vol[-5:] if by_price[p] > 0]
        return VolumeProfileResult(
            poc=poc_price,
            vah=vah,
            val=val,
            total_volume=total,
            value_pct=self.value_area_pct,
            by_price=by_price,
            hvn_prices=hvn_prices,
            lvn_prices=lvn_prices,
        )

    def reset_session(self) -> None:
        """Reset CVD and profile at session start."""
        self._buy_volume = 0.0
        self._sell_volume = 0.0
        self._cvd = 0.0
        self._volume_at_price.clear()
        self._recent_big_trades.clear()
        self._bars.clear()
        self._current_bar = None
        self._bar_open = 0.0
        self._bar_high = 0.0
        self._bar_low = float("inf")
        self._bar_close = 0.0
        self._bar_buy_vol = 0.0
        self._bar_sell_vol = 0.0
        self._bar_big_buys = 0
        self._bar_big_sells = 0
        self._bar_trades = 0

    def is_near_lvn(self, price: float, profile: VolumeProfileResult, ticks: int = 10) -> bool:
        """True if price is within ticks of a low-volume node."""
        if not profile.lvn_prices:
            return False
        pip = self.pips
        return any(abs(price - p) <= ticks * pip for p in profile.lvn_prices)

    def is_near_hvn(self, price: float, profile: VolumeProfileResult, ticks: int = 10) -> bool:
        """True if price is within ticks of POC or HVN."""
        if not profile.hvn_prices:
            return False
        pip = self.pips
        return any(abs(price - p) <= ticks * pip for p in profile.hvn_prices) or abs(price - profile.poc) <= ticks * pip

    def is_near_poc(self, price: float, profile: VolumeProfileResult, ticks: int = 15) -> bool:
        return abs(price - profile.poc) <= ticks * self.pips
