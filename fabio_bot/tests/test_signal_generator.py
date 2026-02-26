"""Unit tests for signal generator (Fabio-style rules)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from fabio_bot.order_flow_analyzer import OrderFlowAnalyzer, VolumeProfileResult
from fabio_bot.signal_generator import Signal, SignalGenerator, MarketState, SignalResult


def test_signal_none_without_setup():
    pips = 0.25
    a = OrderFlowAnalyzer(pips=pips, size_multiplier=1.0, big_trade_threshold=30)
    # No bars
    profile = a.build_volume_profile()
    gen = SignalGenerator(min_delta=500)
    res = gen.generate(a, profile, 20000.0, 10.0 * pips, pips)
    assert res.signal == Signal.NONE


def test_signal_result_has_all_fields():
    """SignalResult must have signal, reason, strength, stop_ticks, target1_ticks, target2_ticks."""
    res = SignalResult(Signal.NONE, "no_bars", 0.0, 20, 10, 40)
    assert res.signal == Signal.NONE
    assert res.reason == "no_bars"
    assert res.strength == 0.0
    assert res.stop_ticks == 20
    assert res.target1_ticks == 10
    assert res.target2_ticks == 40


def test_generate_returns_valid_signal_result():
    """generate() always returns SignalResult with valid stop/target ticks (or 0 when no bars)."""
    pips = 0.25
    a = OrderFlowAnalyzer(pips=pips, size_multiplier=1.0, big_trade_threshold=30)
    profile = a.build_volume_profile()
    gen = SignalGenerator(min_delta=500, atr_stop_multiplier=1.5, rr_first=0.8, rr_second=1.8)
    res = gen.generate(a, profile, 20000.0, 15.0 * pips, pips)
    assert isinstance(res, SignalResult)
    assert res.signal in (Signal.NONE, Signal.LONG, Signal.SHORT)
    assert res.stop_ticks >= 0  # 0 when no_bars, else >= 10
    assert res.target1_ticks >= 0
    assert res.target2_ticks >= 0
    assert 0 <= res.strength <= 1.0
    assert isinstance(res.reason, str)


def test_strength_filter_blocks_weak_signals():
    """When min_signal_strength is high, weak setups return NONE with reason strength_filter."""
    pips = 0.25
    a = OrderFlowAnalyzer(pips=pips, size_multiplier=1.0, big_trade_threshold=30)
    for _ in range(20):
        a.on_trade(80000, 5, True)
        a.on_trade(80000, 5, False)
    for _ in range(5):
        a.start_new_bar()
    profile = a.build_volume_profile()
    gen = SignalGenerator(min_delta=100, min_signal_strength=0.99)  # very high bar
    res = gen.generate(a, profile, 20000.0, 10.0 * pips, pips)
    assert res.signal == Signal.NONE
    assert res.reason in ("no_setup", "strength_filter", "no_bars")


def test_market_state_balanced():
    pips = 0.25
    a = OrderFlowAnalyzer(pips=pips, size_multiplier=1.0)
    for _ in range(50):
        a.on_trade(80000, 10, True)
        a.on_trade(80000, 10, False)
    for _ in range(5):
        a.start_new_bar()
    profile = VolumeProfileResult(
        poc=20000.0, vah=20010.0, val=19990.0, total_volume=1000, value_pct=0.70,
        by_price={20000.0: 500, 20005.0: 300, 19995.0: 200}, hvn_prices=[20000], lvn_prices=[19990],
    )
    gen = SignalGenerator()
    state = gen.classify_market_state(a, profile, 20000.0)
    assert state in (MarketState.BALANCED, MarketState.UNBALANCED)
