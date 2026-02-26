"""
Signal generation mimicking Fabio Valentini's order flow scalping rules.
Long/short on CVD + big trades + absorption + volume profile (LVN/HVN) + FVG/context.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .order_flow_analyzer import (
        BarSnapshot,
        OrderFlowAnalyzer,
        VolumeProfileResult,
        AbsorptionState,
    )

logger = logging.getLogger(__name__)


class MarketState(Enum):
    BALANCED = "balanced"   # Range / mean-reversion
    UNBALANCED = "unbalanced"  # Trend / continuation


class Signal(Enum):
    NONE = 0
    LONG = 1
    SHORT = -1


@dataclass
class SignalResult:
    signal: Signal
    reason: str
    strength: float  # 0-1
    stop_ticks: int
    target1_ticks: int
    target2_ticks: int


class SignalGenerator:
    """
    Fabio-style signals:
    - Long: bullish CVD + big buy cluster + absorption at LVN/support + (optional) above trend
    - Short: bearish CVD + big sells at HVN/resistance + absorption bearish / liquidity grab fail
    - Market state: balanced -> mean-revert at HVN/POC; unbalanced -> trend-follow LVN breakouts
    """

    def __init__(
        self,
        min_delta: float = 500.0,
        delta_sensitivity: float = 1.0,
        big_trade_confirm_min: int = 2,
        big_trade_edge: int = 2,
        require_absorption: bool = True,
        require_at_structure: bool = True,
        min_delta_multiplier: float = 1.3,
        min_signal_strength: float = 0.0,
        lvn_ticks: int = 10,
        hvn_ticks: int = 10,
        poc_ticks: int = 15,
        atr_stop_multiplier: float = 1.5,
        rr_first: float = 1.0,
        rr_second: float = 2.0,
    ):
        self.min_delta = min_delta
        self.delta_sensitivity = delta_sensitivity
        self.big_trade_confirm_min = big_trade_confirm_min
        self.big_trade_edge = big_trade_edge
        self.require_absorption = require_absorption
        self.require_at_structure = require_at_structure
        self.min_delta_multiplier = min_delta_multiplier
        self.min_signal_strength = min_signal_strength
        self.lvn_ticks = lvn_ticks
        self.hvn_ticks = hvn_ticks
        self.poc_ticks = poc_ticks
        self.atr_stop_multiplier = atr_stop_multiplier
        self.rr_first = rr_first
        self.rr_second = rr_second

    def classify_market_state(
        self,
        analyzer: "OrderFlowAnalyzer",
        profile: "VolumeProfileResult",
        last_price: float,
    ) -> MarketState:
        """Balanced if price oscillating around POC; unbalanced if breaking LVN with volume."""
        if not profile.by_price or profile.total_volume == 0:
            return MarketState.BALANCED
        bars = analyzer.get_recent_bars(20)
        if len(bars) < 10:
            return MarketState.BALANCED
        # Simple rule: if price mostly inside value area -> balanced
        inside = sum(1 for b in bars if profile.val <= b.close <= profile.vah)
        if inside >= len(bars) * 0.6:
            return MarketState.BALANCED
        return MarketState.UNBALANCED

    def generate(
        self,
        analyzer: "OrderFlowAnalyzer",
        profile: "VolumeProfileResult",
        last_price: float,
        atr: float,
        pips: float,
    ) -> SignalResult:
        """
        Scan for long/short. Returns SignalResult with NONE if no setup.
        """
        bars = analyzer.get_recent_bars(10)
        if not bars:
            return SignalResult(Signal.NONE, "no_bars", 0.0, 0, 0, 0)

        bar = bars[-1]
        cvd = analyzer.get_cvd()
        bar_delta = bar.delta
        big_buys, big_sells = analyzer.get_big_trade_cluster(30)
        absorption = analyzer.get_absorption()

        # Effective thresholds (stricter min_d for higher-quality signals)
        min_d = self.min_delta * self.delta_sensitivity
        min_d_strong = min_d * self.min_delta_multiplier
        stop_ticks = max(10, int((atr / pips) * self.atr_stop_multiplier))
        t1 = int(stop_ticks * self.rr_first)
        t2 = int(stop_ticks * self.rr_second)

        state = self.classify_market_state(analyzer, profile, last_price)
        near_lvn = analyzer.is_near_lvn(last_price, profile, self.lvn_ticks)
        near_hvn = analyzer.is_near_hvn(last_price, profile, self.hvn_ticks)
        near_poc = analyzer.is_near_poc(last_price, profile, self.poc_ticks)

        def _check_strength_and_return(sig: Signal, reason: str, strength: float) -> SignalResult:
            if strength < self.min_signal_strength:
                return SignalResult(Signal.NONE, "strength_filter", 0.0, stop_ticks, t1, t2)
            return SignalResult(signal=sig, reason=reason, strength=strength, stop_ticks=stop_ticks, target1_ticks=t1, target2_ticks=t2)

        # Absorption required for directional when require_absorption=True
        long_absorption_ok = (not self.require_absorption) or absorption.absorption_bullish
        short_absorption_ok = (not self.require_absorption) or absorption.absorption_bearish
        big_edge_long = big_buys >= big_sells + self.big_trade_edge
        big_edge_short = big_sells >= big_buys + self.big_trade_edge

        # --- LONG (stricter: stronger CVD, clear big-trade edge, at structure when required) ---
        if (
            cvd >= min_d_strong
            and bar_delta > 0
            and big_buys >= self.big_trade_confirm_min
            and big_edge_long
            and long_absorption_ok
        ):
            at_support = near_lvn or (state == MarketState.BALANCED and profile.val and last_price <= profile.val + self.poc_ticks * pips)
            if not self.require_at_structure or at_support:
                strength = min(1.0,
                    0.35 * min(1.0, cvd / (min_d_strong * 2))
                    + 0.35 * min(1.0, (big_buys - big_sells) / 5)
                    + (0.3 if absorption.absorption_bullish else 0.0)
                    + (0.15 if at_support else 0.0),
                )
                return _check_strength_and_return(Signal.LONG, "cvd_big_buys_absorption_lvn", strength)

        # --- SHORT ---
        if (
            cvd <= -min_d_strong
            and bar_delta < 0
            and big_sells >= self.big_trade_confirm_min
            and big_edge_short
            and short_absorption_ok
        ):
            at_resistance = near_hvn or (state == MarketState.BALANCED and profile.vah and last_price >= profile.vah - self.poc_ticks * pips)
            if not self.require_at_structure or at_resistance:
                strength = min(1.0,
                    0.35 * min(1.0, abs(cvd) / (min_d_strong * 2))
                    + 0.35 * min(1.0, (big_sells - big_buys) / 5)
                    + (0.3 if absorption.absorption_bearish else 0.0)
                    + (0.15 if at_resistance else 0.0),
                )
                return _check_strength_and_return(Signal.SHORT, "cvd_big_sells_absorption_hvn", strength)

        # Balanced mean-reversion: fade extremes at POC (high win rate when volume exhaustion clear)
        if state == MarketState.BALANCED and near_poc and profile.total_volume > 0:
            avg_vol = sum(b.total_volume for b in bars[:-1]) / max(1, len(bars) - 1)
            if bar.total_volume > avg_vol * 1.3:
                if bar_delta < -min_d * 0.6 and last_price >= profile.poc:
                    return _check_strength_and_return(Signal.SHORT, "mean_revert_poc_exhaustion", 0.72)
                if bar_delta > min_d * 0.6 and last_price <= profile.poc:
                    return _check_strength_and_return(Signal.LONG, "mean_revert_poc_exhaustion", 0.72)

        return SignalResult(Signal.NONE, "no_setup", 0.0, stop_ticks, t1, t2)
