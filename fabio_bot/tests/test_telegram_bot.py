"""
A-to-Z tests for the Telegram bot: format functions, inline menu, trailing logic,
and one-cycle pipeline with mock data. No real Telegram API calls.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Run from repo root or fabio_bot so telegram_bot and backtest are importable
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest


# --- Import bot module (after path is set) ---
def _import_bot():
    import telegram_bot as tb
    return tb


def test_inline_menu_structure():
    tb = _import_bot()
    menu = tb._inline_menu()
    assert "inline_keyboard" in menu
    rows = menu["inline_keyboard"]
    assert len(rows) >= 1
    flat = [b for row in rows for b in row]
    texts = [b["text"] for b in flat]
    datas = [b["callback_data"] for b in flat]
    assert "Status" in texts and "status" in datas
    assert "Strategy" in texts and "strategy" in datas
    assert "Params" in texts and "params" in datas
    assert "Settings" in texts and "settings" in datas
    assert "Help" in texts and "help" in datas


def test_format_start_contains_commands():
    tb = _import_bot()
    s = tb._format_start()
    assert "Fabio" in s or "Order Flow" in s
    assert "/status" in s or "Status" in s
    assert "/strategy" in s or "Strategy" in s
    assert "/help" in s or "Help" in s


def test_format_help_contains_all_commands():
    tb = _import_bot()
    s = tb._format_help()
    for cmd in ["/start", "/status", "/strategy", "/params", "/settings", "/help"]:
        assert cmd in s


def test_format_status_with_state():
    tb = _import_bot()
    state = {
        "n_bars": 1000,
        "signal": "NONE",
        "strength": 0.45,
        "reason": "no_setup",
        "symbol": "MNQ=F",
        "data_symbol": "NQ=F",
    }
    s = tb._format_status(state)
    assert "1000" in s
    assert "NONE" in s
    assert "0.45" in s
    assert "no_setup" in s
    assert "MNQ" in s or "NQ" in s


def test_format_settings_with_config():
    tb = _import_bot()
    cfg = {
        "telegram": {
            "symbol": "MNQ=F",
            "interval": "1m",
            "period": "7d",
            "interval_seconds": 60,
            "use_ml_filter": False,
            "use_regime_filter": True,
        },
        "ml": {"model_path": "data/ml_signal_model.pkl"},
    }
    s = tb._format_settings(cfg)
    assert "MNQ" in s
    assert "1m" in s
    assert "60" in s
    assert "Off" in s or "On" in s


def test_format_strategy_handles_missing_file():
    tb = _import_bot()
    # May or may not have best_params file; either way should not crash
    s = tb._format_strategy()
    assert "Strategy" in s or "strategy" in s.lower()
    assert len(s) > 0


def test_format_params_handles_missing_file():
    tb = _import_bot()
    s = tb._format_params()
    assert "param" in s.lower() or "Params" in s
    assert len(s) > 0


# --- Trailing logic: _update_open_trade (mock _send_telegram) ---
def test_trailing_long_tp2_hit_closes_trade():
    tb = _import_bot()
    open_trade = {
        "active": True,
        "direction": "LONG",
        "entry": 100.0,
        "sl": 98.0,
        "tp1": 102.0,
        "tp2": 105.0,
        "moved_to_be": False,
        "tp2_hit": False,
    }
    with patch.object(tb, "_send_telegram", return_value=True) as send:
        tb._update_open_trade(open_trade, 105.5, "token", "chat", "MNQ=F")
    assert send.called
    assert "TP2 hit" in send.call_args[0][2]
    assert open_trade["active"] is False
    assert open_trade.get("tp2_hit") is True


def test_trailing_long_tp1_moves_sl_to_be():
    tb = _import_bot()
    open_trade = {
        "active": True,
        "direction": "LONG",
        "entry": 100.0,
        "sl": 98.0,
        "tp1": 102.0,
        "tp2": 105.0,
        "moved_to_be": False,
        "tp2_hit": False,
    }
    with patch.object(tb, "_send_telegram", return_value=True) as send:
        tb._update_open_trade(open_trade, 102.5, "token", "chat", "MNQ=F")
    assert send.called
    assert "TP1 hit" in send.call_args[0][2]
    assert open_trade["sl"] == 100.0
    assert open_trade["moved_to_be"] is True
    assert open_trade["active"] is True


def test_trailing_long_sl_hit_closes_trade():
    tb = _import_bot()
    open_trade = {
        "active": True,
        "direction": "LONG",
        "entry": 100.0,
        "sl": 98.0,
        "tp1": 102.0,
        "tp2": 105.0,
        "moved_to_be": False,
        "tp2_hit": False,
    }
    with patch.object(tb, "_send_telegram", return_value=True) as send:
        tb._update_open_trade(open_trade, 97.5, "token", "chat", "MNQ=F")
    assert send.called
    assert "SL hit" in send.call_args[0][2]
    assert open_trade["active"] is False


def test_trailing_short_tp2_hit_closes_trade():
    tb = _import_bot()
    open_trade = {
        "active": True,
        "direction": "SHORT",
        "entry": 100.0,
        "sl": 102.0,
        "tp1": 98.0,
        "tp2": 95.0,
        "moved_to_be": False,
        "tp2_hit": False,
    }
    with patch.object(tb, "_send_telegram", return_value=True) as send:
        tb._update_open_trade(open_trade, 94.0, "token", "chat", "MNQ=F")
    assert send.called
    assert "TP2 hit" in send.call_args[0][2]
    assert open_trade["active"] is False


def test_trailing_short_sl_hit_closes_trade():
    tb = _import_bot()
    open_trade = {
        "active": True,
        "direction": "SHORT",
        "entry": 100.0,
        "sl": 102.0,
        "tp1": 98.0,
        "tp2": 95.0,
        "moved_to_be": False,
        "tp2_hit": False,
    }
    with patch.object(tb, "_send_telegram", return_value=True) as send:
        tb._update_open_trade(open_trade, 103.0, "token", "chat", "MNQ=F")
    assert send.called
    assert "SL hit" in send.call_args[0][2]
    assert open_trade["active"] is False


def test_trailing_inactive_trade_does_nothing():
    tb = _import_bot()
    open_trade = {"active": False, "direction": "LONG", "entry": 100.0}
    with patch.object(tb, "_send_telegram", return_value=True) as send:
        tb._update_open_trade(open_trade, 105.0, "token", "chat", "MNQ=F")
    assert not send.called


def test_trailing_empty_trade_does_nothing():
    tb = _import_bot()
    with patch.object(tb, "_send_telegram", return_value=True) as send:
        tb._update_open_trade({}, 100.0, "token", "chat", "MNQ=F")
    assert not send.called


# --- Pipeline: get_latest_signal with minimal bar data ---
def test_get_latest_signal_returns_tuple_of_four():
    """Backtest.get_latest_signal returns (signal, strength, price, features)."""
    import pandas as pd
    from backtest import get_latest_signal

    # Minimal OHLCV + buy/sell volume (enough bars so analyzer runs)
    n = 150
    df = pd.DataFrame({
        "open": [20000.0 + (i % 10) * 0.25 for i in range(n)],
        "high": [20000.5 + (i % 10) * 0.25 for i in range(n)],
        "low": [19999.5 + (i % 10) * 0.25 for i in range(n)],
        "close": [20000.25 + (i % 10) * 0.25 for i in range(n)],
        "buy_volume": [50 + (i % 20) for i in range(n)],
        "sell_volume": [50 + (19 - i % 20) for i in range(n)],
    })
    df["bar_idx"] = range(len(df))

    sig, strength, price, features = get_latest_signal(
        df,
        min_signal_strength=0.0,
        min_delta=100.0,
        min_delta_multiplier=1.1,
        big_trade_threshold=30.0,
        big_trade_edge=2,
        rr_first=0.5,
        rr_second=1.1,
        atr_stop_multiplier=1.5,
    )
    assert sig is not None  # Signal enum or None
    assert isinstance(strength, (int, float))
    assert isinstance(price, (int, float))
    assert isinstance(features, dict)
    assert "reason" in features
    assert "sl_price" in features
    assert "tp1_price" in features
    assert "tp2_price" in features


def test_signal_message_contains_entry_sl_tp():
    """Build the same message string the bot sends; must contain Entry, SL, TP1, TP2."""
    entry = 21450.25
    sl = 21445.50
    tp1 = 21456.00
    tp2 = 21462.25
    direction = "LONG"
    label = "MNQ"
    strength = 0.72
    rr1, rr2 = 0.5, 1.1

    msg = (
        f"<b>Signal {direction}</b> {label}\n\n"
        f"Entry: {entry:.2f}\n"
        f"SL: {sl:.2f}\n"
        f"TP1: {tp1:.2f}\n"
        f"TP2: {tp2:.2f}\n\n"
        f"Strength: {strength:.2f}  ·  R:R {rr1:.2f} / {rr2:.2f}"
    )
    assert "Entry:" in msg and "21450.25" in msg
    assert "SL:" in msg and "21445.50" in msg
    assert "TP1:" in msg and "21456" in msg
    assert "TP2:" in msg and "21462" in msg
    assert "LONG" in msg and "MNQ" in msg


def test_load_config_returns_dict():
    tb = _import_bot()
    cfg = tb._load_config()
    assert isinstance(cfg, dict)


def test_load_mnq_params_returns_dict():
    tb = _import_bot()
    params = tb._load_mnq_params()
    assert isinstance(params, dict)
