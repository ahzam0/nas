"""
Tests for fetch_orderflow_bars: unified fetcher returns correct shape.
Uses mocks to avoid network; no real Yahoo/Binance/Alpaca calls.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import pytest

from fabio_bot.fetch_market_data import fetch_orderflow_bars

REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume", "buy_volume", "sell_volume", "bar_idx"]


def test_fetch_orderflow_bars_yahoo_returns_shape():
    """fetch_orderflow_bars(source=yahoo) returns (df, symbol) with required columns."""
    with patch("fabio_bot.fetch_market_data.fetch_nq_or_mnq_1m") as mock:
        mock_df = pd.DataFrame({
            "open": [21400.0, 21401.0],
            "high": [21402.0, 21403.0],
            "low": [21399.0, 21400.0],
            "close": [21401.0, 21402.0],
            "volume": [100.0, 110.0],
            "buy_volume": [60.0, 65.0],
            "sell_volume": [40.0, 45.0],
            "bar_idx": [0, 1],
        })
        mock.return_value = (mock_df, "MNQ=F")
        df, symbol = fetch_orderflow_bars(source="yahoo", symbol="MNQ=F")
    assert symbol == "MNQ=F"
    assert not df.empty
    for c in REQUIRED_COLUMNS:
        assert c in df.columns
    assert len(df) == 2


def test_fetch_orderflow_bars_binance_returns_shape():
    """fetch_orderflow_bars(source=binance) returns (df, symbol) with required columns."""
    with patch("fabio_bot.fetch_market_data.fetch_binance_1m") as mock:
        mock_df = pd.DataFrame({
            "open": [97000.0],
            "high": [97100.0],
            "low": [96900.0],
            "close": [97050.0],
            "volume": [1000.0],
            "buy_volume": [520.0],
            "sell_volume": [480.0],
            "bar_idx": [0],
        })
        mock.return_value = (mock_df, "BTCUSDT")
        df, symbol = fetch_orderflow_bars(source="binance", symbol="BTCUSDT")
    assert symbol == "BTCUSDT"
    assert not df.empty
    for c in REQUIRED_COLUMNS:
        assert c in df.columns


def test_fetch_orderflow_bars_alpaca_returns_shape():
    """fetch_orderflow_bars(source=alpaca) returns (df, symbol) with required columns."""
    with patch("fabio_bot.fetch_market_data.fetch_alpaca_1m") as mock:
        mock_df = pd.DataFrame({
            "open": [500.0],
            "high": [501.0],
            "low": [499.0],
            "close": [500.5],
            "volume": [1e6],
            "buy_volume": [520000.0],
            "sell_volume": [480000.0],
            "bar_idx": [0],
        })
        mock.return_value = (mock_df, "QQQ")
        df, symbol = fetch_orderflow_bars(source="alpaca", symbol="QQQ")
    assert symbol == "QQQ"
    assert not df.empty
    for c in REQUIRED_COLUMNS:
        assert c in df.columns


def test_fetch_orderflow_bars_default_is_yahoo():
    """No source/symbol defaults to yahoo and MNQ=F."""
    with patch("fabio_bot.fetch_market_data.fetch_nq_or_mnq_1m") as mock:
        mock.return_value = (pd.DataFrame(), "MNQ=F")
        _, symbol = fetch_orderflow_bars()
    mock.assert_called_once()
    call_kw = mock.call_args[1]
    assert call_kw.get("symbol") == "MNQ=F"
