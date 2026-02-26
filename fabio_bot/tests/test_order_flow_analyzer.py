"""Unit tests for order flow analyzer (CVD, volume profile, absorption)."""
import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fabio_bot.order_flow_analyzer import OrderFlowAnalyzer, BarSnapshot, VolumeProfileResult


def test_cvd_accumulates():
    pips = 0.25
    size_mult = 1.0
    a = OrderFlowAnalyzer(pips=pips, size_multiplier=size_mult, big_trade_threshold=30)
    # 10 buys at 20000, 5 sells at 20000
    for _ in range(10):
        a.on_trade(int(20000 / pips), int(5 * size_mult), True)
    for _ in range(5):
        a.on_trade(int(20000 / pips), int(5 * size_mult), False)
    assert a.get_cvd() == (10 * 5 - 5 * 5)


def test_bar_snapshot():
    pips = 0.25
    size_mult = 1.0
    a = OrderFlowAnalyzer(pips=pips, size_multiplier=size_mult)
    a.on_trade(80000, 20, True)   # 20000, 20 contracts
    a.on_trade(80004, 10, False)   # 20001, 10
    bar = a.start_new_bar()
    assert bar is not None
    assert bar.buy_volume == 20
    assert bar.sell_volume == 10
    assert bar.delta == 10


def test_volume_profile_poc():
    pips = 0.25
    a = OrderFlowAnalyzer(pips=pips, size_multiplier=1.0, value_area_pct=0.70)
    # Most volume at 20000
    for _ in range(100):
        a.on_trade(int(20000 / pips), 10, True)
    for _ in range(20):
        a.on_trade(int(20001 / pips), 10, False)
    for _ in range(10):
        a.on_trade(int(19999 / pips), 10, False)
    profile = a.build_volume_profile()
    assert profile.total_volume > 0
    assert profile.poc == 20000.0


def test_big_trades():
    pips = 0.25
    a = OrderFlowAnalyzer(pips=pips, size_multiplier=1.0, big_trade_threshold=25)
    a.on_trade(80000, 30, True)   # 30 >= 25
    a.on_trade(80000, 40, False)
    buys, sells = a.get_big_trade_cluster(10)
    assert buys == 1
    assert sells == 1
