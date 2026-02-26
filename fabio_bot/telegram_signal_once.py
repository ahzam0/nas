"""
Run one signal cycle and exit. For PythonAnywhere: schedule this script every 1–2 minutes.
Fetches bars, runs strategy, sends Telegram if LONG/SHORT; optionally updates open-trade state (TP1/TP2/SL).
No long-running process. Config: same as telegram_bot (config.yaml or env vars).
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger("signal_once")

OPEN_TRADE_FILE = ROOT / "data" / "open_trade.json"


def _load_config():
    try:
        from fabio_bot.config_loader import load_config
        return load_config(ROOT / "config.yaml") if (ROOT / "config.yaml").exists() else {}
    except Exception:
        return {}


def _load_params():
    p_path = ROOT / "data" / "best_params_mnq_1m.json"
    if not p_path.exists():
        return {}
    try:
        with open(p_path) as f:
            return json.load(f).get("params", {})
    except Exception:
        return {}


def _send(token: str, chat_id: str, text: str) -> bool:
    try:
        import urllib.request
        import urllib.parse
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode()
        req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except Exception as e:
        logger.warning("Telegram send failed: %s", e)
        return False


def _load_open_trade():
    if not OPEN_TRADE_FILE.exists():
        return {}
    try:
        with open(OPEN_TRADE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_open_trade(open_trade: dict):
    OPEN_TRADE_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(OPEN_TRADE_FILE, "w") as f:
            json.dump(open_trade, f)
    except Exception:
        pass


def _update_trailing(open_trade: dict, last_price: float, token: str, chat_id: str, symbol: str):
    """Same logic as telegram_bot._update_open_trade; then save state."""
    if not open_trade.get("active"):
        return
    direction = open_trade.get("direction", "LONG")
    entry = open_trade.get("entry", 0)
    sl = open_trade.get("sl", 0)
    tp1 = open_trade.get("tp1", 0)
    tp2 = open_trade.get("tp2", 0)
    moved_to_be = open_trade.get("moved_to_be", False)
    tp2_hit = open_trade.get("tp2_hit", False)
    label = symbol.replace("=F", "").strip()

    if direction == "LONG":
        if not tp2_hit and last_price >= tp2:
            _send(token, chat_id, f"<b>TP2 hit</b> {label} LONG\nEntry: {entry:.2f}\nExit: {last_price:.2f}\nResult: +{last_price - entry:.2f}")
            open_trade["active"] = False
            open_trade["tp2_hit"] = True
            return
        if not moved_to_be and last_price >= tp1:
            open_trade["sl"] = entry
            open_trade["moved_to_be"] = True
            _send(token, chat_id, f"<b>TP1 hit</b> {label} LONG\nSL moved to breakeven at {entry:.2f}")
            return
        if last_price <= sl:
            _send(token, chat_id, f"<b>SL hit</b> {label} LONG\nEntry: {entry:.2f}\nExit: {last_price:.2f}\nResult: {last_price - entry:.2f}")
            open_trade["active"] = False
            return
    else:
        if not tp2_hit and last_price <= tp2:
            _send(token, chat_id, f"<b>TP2 hit</b> {label} SHORT\nEntry: {entry:.2f}\nExit: {last_price:.2f}\nResult: +{entry - last_price:.2f}")
            open_trade["active"] = False
            open_trade["tp2_hit"] = True
            return
        if not moved_to_be and last_price <= tp1:
            open_trade["sl"] = entry
            open_trade["moved_to_be"] = True
            _send(token, chat_id, f"<b>TP1 hit</b> {label} SHORT\nSL moved to breakeven at {entry:.2f}")
            return
        if last_price >= sl:
            _send(token, chat_id, f"<b>SL hit</b> {label} SHORT\nEntry: {entry:.2f}\nExit: {last_price:.2f}\nResult: {entry - last_price:.2f}")
            open_trade["active"] = False
            return


def main():
    cfg = _load_config()
    tg = cfg.get("telegram", {})
    token = (tg.get("bot_token") or os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (tg.get("chat_id") or os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        logger.error("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (or config.yaml telegram.bot_token, telegram.chat_id)")
        return 1

    data_source = (tg.get("data_source") or "yahoo").strip().lower()
    symbol = tg.get("symbol", "MNQ=F")
    alpaca_symbol = (tg.get("alpaca_symbol") or "QQQ").strip()
    alpaca_key = (tg.get("alpaca_key_id") or os.environ.get("ALPACA_KEY_ID") or "").strip()
    alpaca_secret = (tg.get("alpaca_secret_key") or os.environ.get("ALPACA_SECRET_KEY") or "").strip()
    binance_symbol = (tg.get("binance_symbol") or "BTCUSDT").strip()
    display_symbol = alpaca_symbol if data_source == "alpaca" else (binance_symbol if data_source == "binance" else symbol)

    params = _load_params()
    min_strength = params.get("min_signal_strength", 0.56)
    min_delta = params.get("min_delta", 432)
    min_delta_mult = params.get("min_delta_multiplier", 1.32)
    big_trade = params.get("big_trade_threshold", 30)
    big_edge = params.get("big_trade_edge", 3)
    rr1 = params.get("rr_first", 0.58)
    rr2 = params.get("rr_second", 1.42)
    atr_stop = params.get("atr_stop_multiplier", 1.32)

    try:
        from fabio_bot.fetch_market_data import fetch_orderflow_bars
    except ImportError:
        logger.error("pip install -r requirements.txt")
        return 1
    from backtest import get_latest_signal
    from fabio_bot.signal_generator import Signal

    df, data_symbol = fetch_orderflow_bars(
        source=data_source,
        symbol=symbol if data_source == "yahoo" else (alpaca_symbol if data_source == "alpaca" else binance_symbol),
        alpaca_key_id=alpaca_key or None,
        alpaca_secret_key=alpaca_secret or None,
    )
    min_bars = 50 if data_source == "alpaca" else 100
    if df is None or df.empty or len(df) < min_bars:
        if data_source == "alpaca":
            df, data_symbol = fetch_orderflow_bars(source="yahoo", symbol=symbol)
        if df is None or df.empty or len(df) < min_bars:
            logger.warning("No data (got %d bars)", len(df) if df is not None and not df.empty else 0)
            return 0
    if "buy_volume" not in df.columns:
        df["buy_volume"] = 50
    if "sell_volume" not in df.columns:
        df["sell_volume"] = 50
    df["bar_idx"] = range(len(df))
    total_vol = df["buy_volume"] + df["sell_volume"]
    mean_vol = total_vol.replace(0, 1).mean()
    if mean_vol > 500:
        scale = (120.0 / mean_vol)
        if scale < 1.0:
            df["buy_volume"] = (df["buy_volume"] * scale).clip(lower=1)
            df["sell_volume"] = (df["sell_volume"] * scale).clip(lower=1)
    elif data_source in ("binance", "alpaca") and 0 < mean_vol < 400:
        scale = 120.0 / mean_vol
        df["buy_volume"] = (df["buy_volume"] * scale).clip(lower=1)
        df["sell_volume"] = (df["sell_volume"] * scale).clip(lower=1)

    open_trade = _load_open_trade()
    last_close = float(df["close"].iloc[-1])
    _update_trailing(open_trade, last_close, token, chat_id, display_symbol)
    _save_open_trade(open_trade)

    sig, strength, price, features = get_latest_signal(
        df,
        min_signal_strength=min_strength,
        min_delta=min_delta,
        min_delta_multiplier=min_delta_mult,
        big_trade_threshold=big_trade,
        big_trade_edge=big_edge,
        rr_first=rr1,
        rr_second=rr2,
        atr_stop_multiplier=atr_stop,
    )
    if sig is None or sig == Signal.NONE or strength < min_strength:
        return 0
    direction = "LONG" if sig == Signal.LONG else "SHORT"
    entry = price
    sl = features.get("sl_price", entry)
    tp1 = features.get("tp1_price", entry)
    tp2 = features.get("tp2_price", entry)
    msg = (
        f"<b>Signal {direction}</b> {display_symbol.replace('=F', '').strip()}\n\n"
        f"Entry: {entry:.2f}\nSL: {sl:.2f}\nTP1: {tp1:.2f}\nTP2: {tp2:.2f}\n\n"
        f"Strength: {strength:.2f}  ·  R:R {rr1:.2f} / {rr2:.2f}"
    )
    if _send(token, chat_id, msg):
        logger.info("Sent %s at %.2f", direction, price)
    open_trade.clear()
    open_trade.update({
        "active": True, "direction": direction, "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2,
        "moved_to_be": False, "tp2_hit": False,
    })
    _save_open_trade(open_trade)
    return 0


if __name__ == "__main__":
    sys.exit(main())
