"""
Telegram bot: sends MNQ/NQ trading signals to a Telegram chat.
Uses 1m bar data (Yahoo), runs order-flow strategy, optional ML filter + regime.
No frontend; signals only via Telegram.

Config: config.yaml telegram.bot_token, telegram.chat_id.
Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("telegram_bot")

# Load config
def _load_config():
    cfg = {}
    try:
        from fabio_bot.config_loader import load_config
        cfg = load_config(ROOT / "config.yaml") if (ROOT / "config.yaml").exists() else {}
    except Exception:
        pass
    return cfg

def _load_mnq_params():
    p_path = ROOT / "data" / "best_params_mnq_1m.json"
    if not p_path.exists():
        return {}
    try:
        with open(p_path) as f:
            return json.load(f).get("params", {})
    except Exception:
        return {}

def _send_telegram(token: str, chat_id: str, text: str, reply_markup: Optional[dict] = None) -> bool:
    try:
        import urllib.request
        import urllib.parse
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)
        data = urllib.parse.urlencode(payload).encode()
        req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        logger.warning("Telegram send failed: %s", e)
        return False


def _answer_callback(token: str, callback_query_id: str) -> bool:
    """Answer a callback query so Telegram clears the loading state. 400 = already answered or expired (expected)."""
    try:
        import urllib.request
        import urllib.parse
        import urllib.error
        url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
        # Telegram expects callback_query_id as string
        cq_id_str = str(callback_query_id).strip()
        if not cq_id_str:
            return False
        data = urllib.parse.urlencode({"callback_query_id": cq_id_str}).encode()
        req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as e:
        if e.code == 400:
            # Query already answered or expired (normal when processing is delayed)
            logger.debug("answerCallbackQuery 400 (already answered or expired): %s", e.reason)
        else:
            logger.warning("answerCallbackQuery failed: %s", e)
        return False
    except Exception as e:
        logger.warning("answerCallbackQuery failed: %s", e)
        return False


def _inline_menu() -> dict:
    """Inline keyboard for main menu (tap instead of typing commands)."""
    return {
        "inline_keyboard": [
            [
                {"text": "Status", "callback_data": "status"},
                {"text": "Strategy", "callback_data": "strategy"},
            ],
            [
                {"text": "Params", "callback_data": "params"},
                {"text": "Settings", "callback_data": "settings"},
            ],
            [{"text": "Help", "callback_data": "help"}],
        ]
    }


# --- Formatted replies for commands ---
def _format_start() -> str:
    return (
        "<b>Fabio Bot – Order Flow Signals</b>\n\n"
        "I send MNQ/NQ trading signals and status.\n\n"
        "<b>Commands</b>\n"
        "/status  – Last cycle (bars, signal, strength)\n"
        "/strategy – Backtest win rate &amp; metrics\n"
        "/params  – Strategy parameters\n"
        "/settings – Bot config (symbol, filters)\n"
        "/help    – This list\n\n"
        "Signals use Yahoo 1m data (volume approximated)."
    )


def _format_help() -> str:
    return (
        "<b>Commands</b>\n"
        "/start   – Welcome &amp; command list\n"
        "/status  – Last run: bars, signal, strength, reason\n"
        "/strategy – Win rate, profit factor, max DD (from backtest)\n"
        "/params  – min_strength, min_delta, R:R, etc.\n"
        "/settings – Symbol, interval, ML filter, regime filter\n"
        "/help    – Show this"
    )


def _format_status(state: dict) -> str:
    n_bars = state.get("n_bars", 0)
    sig = state.get("signal", "NONE")
    strength = state.get("strength", 0.0)
    reason = state.get("reason", "no_setup")
    symbol = state.get("symbol", "MNQ=F")
    data_sym = state.get("data_symbol", symbol)
    lines = [
        "<b>Status</b>",
        f"Symbol: {symbol}",
        f"Data source: {data_sym}",
        f"Last cycle: <b>{n_bars}</b> bars",
        f"Signal: <b>{sig}</b>",
        f"Strength: {strength:.2f}",
        f"Reason: {reason}",
    ]
    if sig == "NONE":
        lines.append("\nℹ️ Yahoo volume is approximated; live data may trigger more.")
    return "\n".join(lines)


def _format_strategy() -> str:
    p_path = ROOT / "data" / "best_params_mnq_1m.json"
    if not p_path.exists():
        return "<b>Strategy</b>\nNo backtest metrics found (run backtest and save to data/best_params_mnq_1m.json)."
    try:
        with open(p_path) as f:
            data = json.load(f)
    except Exception:
        return "<b>Strategy</b>\nCould not read metrics."
    m = data.get("metrics", {})
    wr = m.get("win_rate", 0)
    pf = m.get("profit_factor", 0)
    dd_pct = m.get("max_drawdown_pct", 0)
    trades = m.get("total_trades", 0)
    pnl = m.get("total_pnl", 0)
    sharpe = m.get("sharpe_ratio", 0)
    return (
        "<b>Strategy (MNQ 1m backtest)</b>\n\n"
        f"Win rate: <b>{wr:.1f}%</b>\n"
        f"Profit factor: <b>{pf:.2f}</b>\n"
        f"Max drawdown: <b>{dd_pct:.2f}%</b>\n"
        f"Total trades: {trades}\n"
        f"Total PnL: ${pnl:.2f}\n"
        f"Sharpe: {sharpe:.2f}\n\n"
        "Order-flow scalping (CVD + big trades + optional structure)."
    )


def _format_params() -> str:
    params = _load_mnq_params()
    if not params:
        return "<b>Params</b>\nNo saved params (data/best_params_mnq_1m.json)."
    lines = ["<b>Strategy parameters</b>\n"]
    for k, v in sorted(params.items()):
        if isinstance(v, float) and 0 < v < 1 and "pct" not in k.lower():
            lines.append(f"{k}: {v:.3f}")
        elif isinstance(v, float):
            lines.append(f"{k}: {v:.2f}")
        else:
            lines.append(f"{k}: {v}")
    return "\n".join(lines)


def _format_settings(cfg: dict) -> str:
    tg = cfg.get("telegram", {})
    ml = cfg.get("ml", {})
    symbol = tg.get("symbol", "MNQ=F")
    interval = tg.get("interval", "1m")
    period = tg.get("period", "7d")
    interval_sec = tg.get("interval_seconds", 60)
    use_ml = tg.get("use_ml_filter", False)
    use_regime = tg.get("use_regime_filter", True)
    model_path = ml.get("model_path", "data/ml_signal_model.pkl")
    return (
        "<b>Settings</b>\n\n"
        f"Symbol: {symbol}\n"
        f"Interval: {interval} (period {period})\n"
        f"Check every: {interval_sec}s\n\n"
        f"ML filter: {'On' if use_ml else 'Off'}\n"
        f"Regime filter: {'On' if use_regime else 'Off'}\n"
        f"ML model: {model_path}"
    )


def _update_open_trade(open_trade: dict, last_price: float, token: str, chat_id: str, symbol: str) -> None:
    """
    Simple trailing logic for the last signal:
    - LONG: if price hits TP2 -> close; if hits TP1 first -> move SL to BE; if falls to SL -> stopped.
    - SHORT: mirrored.
    Sends Telegram updates when TP1/TP2/SL are hit.
    """
    if not open_trade or not open_trade.get("active", False):
        return
    direction = open_trade.get("direction")
    entry = float(open_trade.get("entry", last_price))
    sl = float(open_trade.get("sl", entry))
    tp1 = float(open_trade.get("tp1", entry))
    tp2 = float(open_trade.get("tp2", entry))
    moved_to_be = bool(open_trade.get("moved_to_be", False))
    tp2_hit = bool(open_trade.get("tp2_hit", False))

    # LONG trade
    if direction == "LONG":
        # Full target first
        if not tp2_hit and last_price >= tp2:
            msg = (
                f"<b>TP2 hit</b> {symbol.replace('=F', '').strip()} LONG\n"
                f"Entry: {entry:.2f}\nExit: {last_price:.2f}\n"
                f"Result: +{last_price - entry:.2f}"
            )
            _send_telegram(token, chat_id, msg)
            open_trade["active"] = False
            open_trade["tp2_hit"] = True
            return
        # Move SL to breakeven after TP1
        if not moved_to_be and last_price >= tp1:
            open_trade["sl"] = entry
            open_trade["moved_to_be"] = True
            msg = (
                f"<b>TP1 hit</b> {symbol.replace('=F', '').strip()} LONG\n"
                f"SL moved to breakeven at {entry:.2f}"
            )
            _send_telegram(token, chat_id, msg)
            return
        # Stop loss
        if last_price <= sl:
            msg = (
                f"<b>SL hit</b> {symbol.replace('=F', '').strip()} LONG\n"
                f"Entry: {entry:.2f}\nExit: {last_price:.2f}\n"
                f"Result: {last_price - entry:.2f}"
            )
            _send_telegram(token, chat_id, msg)
            open_trade["active"] = False
            return

    # SHORT trade
    if direction == "SHORT":
        if not tp2_hit and last_price <= tp2:
            msg = (
                f"<b>TP2 hit</b> {symbol.replace('=F', '').strip()} SHORT\n"
                f"Entry: {entry:.2f}\nExit: {last_price:.2f}\n"
                f"Result: +{entry - last_price:.2f}"
            )
            _send_telegram(token, chat_id, msg)
            open_trade["active"] = False
            open_trade["tp2_hit"] = True
            return
        if not moved_to_be and last_price <= tp1:
            open_trade["sl"] = entry
            open_trade["moved_to_be"] = True
            msg = (
                f"<b>TP1 hit</b> {symbol.replace('=F', '').strip()} SHORT\n"
                f"SL moved to breakeven at {entry:.2f}"
            )
            _send_telegram(token, chat_id, msg)
            return
        if last_price >= sl:
            msg = (
                f"<b>SL hit</b> {symbol.replace('=F', '').strip()} SHORT\n"
                f"Entry: {entry:.2f}\nExit: {last_price:.2f}\n"
                f"Result: {entry - last_price:.2f}"
            )
            _send_telegram(token, chat_id, msg)
            open_trade["active"] = False
            return


def _handle_commands(token: str, state: dict, cfg: dict) -> None:
    """Poll getUpdates; handle button taps (callback_query) and text commands. Uses state['last_update_id'] for offset."""
    try:
        import urllib.request
        offset = state.get("last_update_id", -1) + 1
        url = f"https://api.telegram.org/bot{token}/getUpdates?timeout=2&limit=15&offset={offset}"
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        return
    results = data.get("result", [])
    if not results:
        return
    state["last_update_id"] = max(upd["update_id"] for upd in results)

    # 1) Handle all button taps first (callback_query) so every button gets a reply
    for upd in results:
        cq = upd.get("callback_query")
        if not cq:
            continue
        cq_id = cq.get("id")
        msg = cq.get("message", {})
        reply_chat = str(msg.get("chat", {}).get("id", ""))
        data_key = (cq.get("data") or "").strip().lower()
        if not reply_chat or not cq_id:
            continue
        if data_key == "status":
            body = _format_status(state)
        elif data_key == "strategy":
            body = _format_strategy()
        elif data_key == "params":
            body = _format_params()
        elif data_key == "settings":
            body = _format_settings(cfg)
        elif data_key == "help":
            body = _format_help()
        else:
            body = "Use /help for commands."
        _send_telegram(token, reply_chat, body)
        _answer_callback(token, str(cq_id))

    # 2) Handle one text command per cycle (/start, /status, etc.)
    for upd in results:
        msg = upd.get("message", {})
        if not msg:
            continue
        text = (msg.get("text") or "").strip()
        if not text:
            continue
        reply_chat = str(msg.get("chat", {}).get("id", ""))
        if not reply_chat:
            continue
        cmd = text.lower().split()[0].split("@")[0]
        if cmd == "/start":
            body = _format_start()
            _send_telegram(token, reply_chat, body, reply_markup=_inline_menu())
        elif cmd == "/status":
            _send_telegram(token, reply_chat, _format_status(state))
        elif cmd == "/strategy":
            _send_telegram(token, reply_chat, _format_strategy())
        elif cmd == "/params":
            _send_telegram(token, reply_chat, _format_params())
        elif cmd == "/settings":
            _send_telegram(token, reply_chat, _format_settings(cfg))
        elif cmd == "/help":
            body = _format_help()
            _send_telegram(token, reply_chat, body, reply_markup=_inline_menu())
        else:
            _send_telegram(token, reply_chat, "Use /help for commands.", reply_markup=_inline_menu())
        break  # one text command per cycle

def main():
    cfg = _load_config()
    telegram_cfg = cfg.get("telegram", {})
    token = (telegram_cfg.get("bot_token") or os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (telegram_cfg.get("chat_id") or os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        logger.error("Set telegram.bot_token and telegram.chat_id in config.yaml or TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID")
        return 1

    data_source = (telegram_cfg.get("data_source") or "yahoo").strip().lower()
    symbol = telegram_cfg.get("symbol", "MNQ=F")
    alpaca_symbol = telegram_cfg.get("alpaca_symbol", "QQQ").strip()
    alpaca_key_id = (telegram_cfg.get("alpaca_key_id") or os.environ.get("ALPACA_KEY_ID") or "").strip()
    alpaca_secret_key = (telegram_cfg.get("alpaca_secret_key") or os.environ.get("ALPACA_SECRET_KEY") or "").strip()
    binance_symbol = telegram_cfg.get("binance_symbol", "BTCUSDT").strip()
    if data_source == "alpaca":
        display_symbol = alpaca_symbol
    elif data_source == "binance":
        display_symbol = binance_symbol
    else:
        display_symbol = symbol
    interval = telegram_cfg.get("interval", "1m")
    period = telegram_cfg.get("period", "7d")
    interval_sec = telegram_cfg.get("interval_seconds", 60)
    use_ml = telegram_cfg.get("use_ml_filter", False)
    use_regime = telegram_cfg.get("use_regime_filter", True)

    params = _load_mnq_params()
    min_strength = params.get("min_signal_strength", 0.585)
    min_delta = params.get("min_delta", 392)
    min_delta_mult = params.get("min_delta_multiplier", 1.22)
    big_trade = params.get("big_trade_threshold", 27)
    big_edge = params.get("big_trade_edge", 2)
    rr1 = params.get("rr_first", 0.5)
    rr2 = params.get("rr_second", 1.1)
    atr_stop = params.get("atr_stop_multiplier", 1.46)

    try:
        from fabio_bot.fetch_market_data import fetch_nq_or_mnq_1m, fetch_binance_1m, fetch_alpaca_1m
    except ImportError:
        logger.error("fetch_market_data not available. pip install yfinance")
        return 1
    from backtest import get_latest_signal
    from fabio_bot.signal_generator import Signal

    ml_filter = None
    if use_ml:
        try:
            from fabio_bot.ml_filter import MLSignalFilter
            ml_filter = MLSignalFilter(ROOT / "data" / "ml_signal_model.pkl", threshold=0.52)
        except Exception as e:
            logger.warning("ML filter disabled: %s", e)
    regime_detector = None
    if use_regime:
        try:
            from fabio_bot.ml_filter import RegimeDetector
            regime_detector = RegimeDetector(window=20, allowed_regimes=(0, 1))
        except Exception as e:
            logger.warning("Regime filter disabled: %s", e)

    logger.info("Telegram signal bot started. data_source=%s, symbol=%s, interval=%ss, ML=%s, regime=%s", data_source, display_symbol, interval_sec, use_ml, use_regime)
    logger.info("Commands: /start /status /strategy /params /settings /help")

    # Shared state for /status and command replies (last_update_id for Telegram getUpdates offset)
    state = {
        "n_bars": 0,
        "signal": "NONE",
        "strength": 0.0,
        "reason": "no_setup",
        "symbol": display_symbol,
        "data_symbol": display_symbol,
        "last_update_id": -1,
    }
    open_trade: dict = {}
    last_signal_bar = -1
    last_sig_str = "NONE"
    last_strength = 0.0
    last_reason = "no_setup"
    n_bars_last = 0
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            while True:
                try:
                    if data_source == "binance":
                        future = pool.submit(fetch_binance_1m, symbol=binance_symbol)
                    elif data_source == "alpaca":
                        future = pool.submit(
                            fetch_alpaca_1m,
                            symbol=alpaca_symbol,
                            key_id=alpaca_key_id or None,
                            secret_key=alpaca_secret_key or None,
                        )
                    else:
                        future = pool.submit(fetch_nq_or_mnq_1m, symbol=symbol, interval=interval, period=period)
                    df, data_symbol = future.result(timeout=35)
                    # If Alpaca returns 403/empty, fall back to Yahoo (MNQ) so bot still runs
                    min_bars = 50 if data_source == "alpaca" else 100
                    if data_source == "alpaca" and (df.empty or len(df) < min_bars):
                        df, data_symbol = fetch_nq_or_mnq_1m(symbol=symbol, interval=interval, period=period)
                        if not df.empty and len(df) >= 100:
                            logger.info("Alpaca failed or too few bars; using Yahoo %s for this cycle", data_symbol)
                except FuturesTimeoutError:
                    logger.warning("Fetch timed out (35s)")
                    state["n_bars"] = n_bars_last
                    state["signal"] = last_sig_str
                    state["strength"] = last_strength
                    state["reason"] = last_reason
                    _handle_commands(token, state, cfg)
                    time.sleep(interval_sec)
                    continue
                except Exception as e:
                    logger.warning("Fetch error: %s", e)
                    state["n_bars"] = n_bars_last
                    state["signal"] = last_sig_str
                    state["strength"] = last_strength
                    state["reason"] = last_reason
                    _handle_commands(token, state, cfg)
                    time.sleep(interval_sec)
                    continue

                min_bars = 50 if data_source == "alpaca" else 100
                if df.empty or len(df) < min_bars:
                    logger.warning("No data for %s (tried %s, got %d bars)", display_symbol, data_symbol, len(df) if not df.empty else 0)
                    state["n_bars"] = n_bars_last
                    state["signal"] = last_sig_str
                    state["strength"] = last_strength
                    state["reason"] = last_reason
                    _handle_commands(token, state, cfg)
                    time.sleep(interval_sec)
                    continue
                if data_source not in ("binance", "alpaca") and data_symbol != symbol:
                    logger.debug("Using %s for data (signals apply to %s)", data_symbol, symbol)

                n_bars_last = len(df)
                state["data_symbol"] = data_symbol
                if "buy_volume" not in df.columns:
                    df["buy_volume"] = 50
                if "sell_volume" not in df.columns:
                    df["sell_volume"] = 50
                df["bar_idx"] = range(len(df))
                total_vol = df["buy_volume"] + df["sell_volume"]
                # Scale volume so strategy (tuned for ~hundreds delta) sees comparable magnitude
                mean_vol = total_vol.replace(0, 1).mean()
                if mean_vol > 500:
                    scale = (120.0 / mean_vol)
                    if scale < 1.0:
                        df["buy_volume"] = (df["buy_volume"] * scale).clip(lower=1)
                        df["sell_volume"] = (df["sell_volume"] * scale).clip(lower=1)
                elif (data_source == "binance" or data_source == "alpaca") and mean_vol > 0 and mean_vol < 400:
                    scale = 120.0 / mean_vol
                    df["buy_volume"] = (df["buy_volume"] * scale).clip(lower=1)
                    df["sell_volume"] = (df["sell_volume"] * scale).clip(lower=1)

                # Trailing updates for any open trade (using last close)
                try:
                    last_close = float(df["close"].iloc[-1])
                    _update_open_trade(open_trade, last_close, token, chat_id, display_symbol)
                except Exception:
                    pass

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

                last_sig_str = getattr(sig, "name", str(sig)) if sig is not None else "NONE"
                last_strength = float(strength)
                last_reason = str(features.get("reason", "no_setup"))
                state["n_bars"] = n_bars_last
                state["signal"] = last_sig_str
                state["strength"] = last_strength
                state["reason"] = last_reason
                state["symbol"] = display_symbol
                state["data_symbol"] = data_symbol
                logger.info("Cycle: %d bars, signal=%s strength=%.2f reason=%s", n_bars_last, last_sig_str, last_strength, last_reason)

                bar_idx = len(df) - 1
                if sig == Signal.NONE or strength < min_strength:
                    _handle_commands(token, state, cfg)
                    time.sleep(interval_sec)
                    continue

                if regime_detector and not regime_detector.should_trade(df, bar_idx):
                    logger.debug("Regime filter: skip")
                    _handle_commands(token, state, cfg)
                    time.sleep(interval_sec)
                    continue

                if ml_filter and not ml_filter.should_take_signal(features):
                    logger.debug("ML filter: skip (P(win)=%.2f)", ml_filter.predict_win_probability(features))
                    _handle_commands(token, state, cfg)
                    time.sleep(interval_sec)
                    continue

                if bar_idx == last_signal_bar:
                    _handle_commands(token, state, cfg)
                    time.sleep(interval_sec)
                    continue
                last_signal_bar = bar_idx

                direction = "LONG" if sig == Signal.LONG else "SHORT"
                label = display_symbol.replace("=F", "").strip()
                entry = price
                sl = features.get("sl_price", entry)
                tp1 = features.get("tp1_price", entry)
                tp2 = features.get("tp2_price", entry)
                msg = (
                    f"<b>Signal {direction}</b> {label}\n\n"
                    f"Entry: {entry:.2f}\n"
                    f"SL: {sl:.2f}\n"
                    f"TP1: {tp1:.2f}\n"
                    f"TP2: {tp2:.2f}\n\n"
                    f"Strength: {strength:.2f}  ·  R:R {rr1:.2f} / {rr2:.2f}"
                )
                 # Track open trade for trailing notifications
                open_trade.clear()
                open_trade.update(
                    {
                        "active": True,
                        "direction": direction,
                        "entry": entry,
                        "sl": sl,
                        "tp1": tp1,
                        "tp2": tp2,
                        "moved_to_be": False,
                        "tp2_hit": False,
                    }
                )
                if _send_telegram(token, chat_id, msg):
                    logger.info("Sent %s at %.2f", direction, price)
                _handle_commands(token, state, cfg)
                time.sleep(interval_sec)
    except KeyboardInterrupt:
        logger.info("Stopped")

if __name__ == "__main__":
    sys.exit(main() or 0)
