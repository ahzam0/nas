"""
A-to-Z tests for the Order Flow API: /api/orderflow/sources and /api/orderflow/bars.
Uses FastAPI TestClient; bars tests use mocked fetch to avoid network.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import pytest
from fastapi.testclient import TestClient

# Import app after path so api_server can resolve fabio_bot
from api_server import app

client = TestClient(app)


def test_orderflow_sources_returns_nasdaq100_first():
    """GET /api/orderflow/sources lists Nasdaq-100 sources first."""
    r = client.get("/api/orderflow/sources")
    assert r.status_code == 200
    data = r.json()
    assert "nasdaq100" in data
    assert "sources" in data
    ids = [s["id"] for s in data["sources"]]
    assert ids[0] == "yahoo"
    assert ids[1] == "alpaca"
    assert ids[2] == "binance"
    assert "MNQ=F" in data["sources"][0]["symbols"]
    assert "nasdaq100_one_click" in data


def test_orderflow_bars_default_uses_yahoo_mnq():
    """GET /api/orderflow/bars with no params returns Nasdaq-100 (Yahoo MNQ) or empty from mock."""
    with patch("fabio_bot.fetch_market_data.fetch_nq_or_mnq_1m") as mock_fetch:
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
        mock_fetch.return_value = (mock_df, "MNQ=F")
        r = client.get("/api/orderflow/bars?limit=10")
    assert r.status_code == 200
    data = r.json()
    assert data["source"] == "yahoo"
    assert "MNQ=F" in (data.get("symbol_requested") or data.get("symbol_used", ""))
    assert data["count"] == 2
    assert len(data["bars"]) == 2
    bar = data["bars"][0]
    for key in ["open", "high", "low", "close", "volume", "buy_volume", "sell_volume", "bar_idx"]:
        assert key in bar


def test_orderflow_bars_market_nasdaq100_uses_config():
    """GET /api/orderflow/bars?market=nasdaq100 uses config data_source and symbol."""
    with patch("api_server._load_telegram_config") as mock_cfg:
        mock_cfg.return_value = {"data_source": "yahoo", "symbol": "NQ=F"}
        with patch("fabio_bot.fetch_market_data.fetch_nq_or_mnq_1m") as mock_fetch:
            mock_df = pd.DataFrame({
                "open": [21400.0], "high": [21401.0], "low": [21399.0], "close": [21400.5],
                "volume": [100.0], "buy_volume": [55.0], "sell_volume": [45.0], "bar_idx": [0],
            })
            mock_fetch.return_value = (mock_df, "NQ=F")
            r = client.get("/api/orderflow/bars?market=nasdaq100&limit=5")
    assert r.status_code == 200
    data = r.json()
    assert data["source"] == "yahoo"
    assert data["symbol_requested"] == "NQ=F"
    assert data["count"] == 1


def test_orderflow_bars_empty_fetch_returns_200_empty_bars():
    """When fetch returns empty dataframe, API returns 200 with bars=[]."""
    with patch("fabio_bot.fetch_market_data.fetch_nq_or_mnq_1m") as mock_fetch:
        mock_fetch.return_value = (pd.DataFrame(), "MNQ=F")
        r = client.get("/api/orderflow/bars?source=yahoo&symbol=MNQ=F&limit=10")
    assert r.status_code == 200
    data = r.json()
    assert data["bars"] == []
    assert data["count"] == 0
    assert "updated_utc" in data


def test_orderflow_bars_explicit_yahoo_symbol():
    """GET /api/orderflow/bars?source=yahoo&symbol=NQ=F returns NQ bars from mock."""
    with patch("fabio_bot.fetch_market_data.fetch_nq_or_mnq_1m") as mock_fetch:
        mock_df = pd.DataFrame({
            "open": [21400.0], "high": [21401.0], "low": [21399.0], "close": [21400.0],
            "volume": [100.0], "buy_volume": [50.0], "sell_volume": [50.0], "bar_idx": [0],
        })
        mock_fetch.return_value = (mock_df, "NQ=F")
        r = client.get("/api/orderflow/bars?source=yahoo&symbol=NQ=F&limit=5")
    assert r.status_code == 200
    data = r.json()
    assert data["source"] == "yahoo"
    assert data["symbol_used"] == "NQ=F"
    assert len(data["bars"]) == 1
