"""
End-to-end tests for signal generation: get_latest_signal with real param sets and bar data.
Ensures the full pipeline (bars -> analyzer -> signal_gen -> features) works correctly.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import pytest

from backtest import get_latest_signal
from fabio_bot.signal_generator import Signal


def _synthetic_bars(n: int = 200, seed: int = 42) -> pd.DataFrame:
    """Minimal OHLCV + buy/sell for get_latest_signal."""
    import random
    random.seed(seed)
    base = 20000.0
    rows = []
    for i in range(n):
        o = base + (i % 15) * 0.25
        h = o + 0.5
        l = o - 0.5
        c = o + (random.random() - 0.5) * 0.5
        bv = 40 + (i % 25)
        sv = 40 + (24 - i % 25)
        rows.append({"open": o, "high": h, "low": l, "close": c, "buy_volume": bv, "sell_volume": sv})
    df = pd.DataFrame(rows)
    df["bar_idx"] = range(len(df))
    return df


def test_get_latest_signal_e2e_synthetic():
    """Full pipeline on synthetic bars: returns valid (signal, strength, price, features)."""
    df = _synthetic_bars(200)
    sig, strength, price, features = get_latest_signal(
        df,
        min_signal_strength=0.0,
        min_delta=200.0,
        min_delta_multiplier=1.2,
        big_trade_threshold=30.0,
        big_trade_edge=2,
        rr_first=0.58,
        rr_second=1.25,
        atr_stop_multiplier=1.5,
    )
    assert sig in (Signal.NONE, Signal.LONG, Signal.SHORT)
    assert isinstance(strength, (int, float))
    assert isinstance(price, (int, float))
    assert price > 0
    assert isinstance(features, dict)
    assert "reason" in features
    assert "sl_price" in features
    assert "tp1_price" in features
    assert "tp2_price" in features
    assert "strength" in features
    assert "stop_ticks" in features
    assert "target1_ticks" in features
    assert "target2_ticks" in features
    # SL/TP should be numeric
    assert isinstance(features["sl_price"], (int, float))
    assert isinstance(features["tp1_price"], (int, float))
    assert isinstance(features["tp2_price"], (int, float))


def test_get_latest_signal_with_best_params_from_json():
    """Run get_latest_signal with params from best_params_mnq_1m.json if present."""
    params_file = ROOT / "data" / "best_params_mnq_1m.json"
    if not params_file.exists():
        pytest.skip("best_params_mnq_1m.json not found")
    with open(params_file) as f:
        data = json.load(f)
    p = data.get("params", {})
    if not p:
        pytest.skip("No params in JSON")
    df = _synthetic_bars(250)
    sig, strength, price, features = get_latest_signal(
        df,
        min_signal_strength=p.get("min_signal_strength", 0.6),
        min_delta=float(p.get("min_delta", 400)),
        min_delta_multiplier=float(p.get("min_delta_multiplier", 1.3)),
        big_trade_threshold=float(p.get("big_trade_threshold", 30)),
        big_trade_edge=int(p.get("big_trade_edge", 2)),
        rr_first=float(p.get("rr_first", 0.58)),
        rr_second=float(p.get("rr_second", 1.25)),
        atr_stop_multiplier=float(p.get("atr_stop_multiplier", 1.4)),
    )
    assert sig in (Signal.NONE, Signal.LONG, Signal.SHORT)
    assert isinstance(features["sl_price"], (int, float))
    assert isinstance(features["tp1_price"], (int, float))
    assert isinstance(features["tp2_price"], (int, float))
    assert "reason" in features


@pytest.mark.parametrize("min_strength", [0.0, 0.5, 0.65])
def test_get_latest_signal_respects_min_strength(min_strength):
    """Higher min_signal_strength may yield NONE more often; pipeline must not crash."""
    df = _synthetic_bars(180)
    sig, strength, price, features = get_latest_signal(
        df,
        min_signal_strength=min_strength,
        min_delta=150.0,
        min_delta_multiplier=1.15,
        big_trade_threshold=30.0,
        big_trade_edge=2,
        rr_first=0.5,
        rr_second=1.1,
        atr_stop_multiplier=1.5,
    )
    assert sig in (Signal.NONE, Signal.LONG, Signal.SHORT)
    if sig != Signal.NONE:
        assert strength >= min_strength
    assert "sl_price" in features and "tp1_price" in features


def test_signal_e2e_on_real_csv_if_present():
    """If data/mnq_1m.csv exists, run get_latest_signal on it; validate structure (no crash)."""
    csv_path = ROOT / "data" / "mnq_1m.csv"
    if not csv_path.exists():
        pytest.skip("data/mnq_1m.csv not found (run backtest --fetch-real --save-csv data/mnq_1m.csv)")
    df = pd.read_csv(csv_path)
    for col in ["open", "high", "low", "close"]:
        if col not in df.columns:
            pytest.skip(f"CSV missing {col}")
    if "buy_volume" not in df.columns:
        df["buy_volume"] = 50
    if "sell_volume" not in df.columns:
        df["sell_volume"] = 50
    if "bar_idx" not in df.columns:
        df["bar_idx"] = range(len(df))
    # Use last 500 bars to keep test fast
    df = df.tail(500).reset_index(drop=True)
    params_file = ROOT / "data" / "best_params_mnq_1m.json"
    if params_file.exists():
        with open(params_file) as f:
            p = json.load(f).get("params", {})
        sig, strength, price, features = get_latest_signal(
            df,
            min_signal_strength=p.get("min_signal_strength", 0.6),
            min_delta=float(p.get("min_delta", 400)),
            min_delta_multiplier=float(p.get("min_delta_multiplier", 1.3)),
            big_trade_threshold=float(p.get("big_trade_threshold", 30)),
            big_trade_edge=int(p.get("big_trade_edge", 2)),
            rr_first=float(p.get("rr_first", 0.58)),
            rr_second=float(p.get("rr_second", 1.25)),
            atr_stop_multiplier=float(p.get("atr_stop_multiplier", 1.4)),
        )
    else:
        sig, strength, price, features = get_latest_signal(
            df, min_signal_strength=0.0, min_delta=300, min_delta_multiplier=1.2,
            big_trade_threshold=30, big_trade_edge=2, rr_first=0.58, rr_second=1.25, atr_stop_multiplier=1.4,
        )
    assert sig in (Signal.NONE, Signal.LONG, Signal.SHORT)
    assert "sl_price" in features and "tp1_price" in features and "tp2_price" in features
    assert "reason" in features