"""
Fabio Valentini (Fabervaale) Order Flow Scalping Bot - Bookmap Add-on Entry Point.
Run from Bookmap: Settings > API Plugins > Add Python script -> select this file.
Uses Bookmap for depth/trades/MBO and routes orders via Bookmap's Tradovate connection.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any, Dict, Optional

# Add project root so fabio_bot package is importable
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    import bookmap as bm
except ImportError:
    bm = None

from fabio_bot.config_loader import load_config
from fabio_bot.order_flow_analyzer import OrderFlowAnalyzer, VolumeProfileResult
from fabio_bot.signal_generator import Signal, SignalGenerator
from fabio_bot.risk_manager import RiskManager
from fabio_bot.execution_engine import ExecutionEngine, BracketRequest

# --- Config ---
CONFIG_PATH = os.path.join(_ROOT, "config.yaml")
config = load_config(CONFIG_PATH) if os.path.exists(CONFIG_PATH) else {}
strategy = config.get("strategy", {})
risk_cfg = config.get("risk", {})
targets_cfg = config.get("targets", {})
mode = config.get("mode", "simulation")
scalp_cfg = config.get("scalp", {})
# When mode is scalp, overlay scalp params for 1m-only max trades
if mode == "scalp" and scalp_cfg:
    strategy = {**strategy, **{k: scalp_cfg[k] for k in ("min_signal_strength", "min_delta", "min_delta_multiplier", "big_trade_edge", "big_trade_threshold") if k in scalp_cfg}}
    targets_cfg = {**targets_cfg, **{k: scalp_cfg[k] for k in ("rr_first", "rr_second") if k in scalp_cfg}}
    risk_cfg = {**risk_cfg, **{k: scalp_cfg[k] for k in ("max_daily_trades",) if k in scalp_cfg}}

# --- Logging ---
log_dir = os.path.join(_ROOT, "logs")
os.makedirs(log_dir, exist_ok=True)
log_file = config.get("logging", {}).get("file", "logs/fabio_bot.log")
if not os.path.isabs(log_file):
    log_file = os.path.join(_ROOT, log_file)
logging.basicConfig(
    level=getattr(logging, config.get("logging", {}).get("level", "INFO")),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("fabio_bot")

# --- Per-instrument state (alias -> state) ---
_instrument_state: Dict[str, Dict[str, Any]] = {}
_interval_counter: Dict[str, int] = {}
BAR_INTERVAL_SEC = int(scalp_cfg.get("interval_seconds", strategy.get("interval_seconds", 15))) if mode == "scalp" and scalp_cfg else strategy.get("interval_seconds", 15)


def _get_state(alias: str, pips: float, size_multiplier: float) -> Dict[str, Any]:
    if alias not in _instrument_state:
        _instrument_state[alias] = {
            "analyzer": OrderFlowAnalyzer(
                pips=pips,
                size_multiplier=size_multiplier,
                big_trade_threshold=float(strategy.get("big_trade_threshold", 30)),
                absorption_ticks=int(strategy.get("absorption_ticks", 3)),
                value_area_pct=float(strategy.get("vah_val_pct", 0.70)),
            ),
            "signal_gen": SignalGenerator(
                min_delta=float(strategy.get("min_delta", 500)),
                delta_sensitivity=float(strategy.get("delta_sensitivity", 1.0)),
                big_trade_confirm_min=2,
                big_trade_edge=int(strategy.get("big_trade_edge", 2)),
                require_absorption=bool(strategy.get("require_absorption", True)),
                require_at_structure=bool(strategy.get("require_at_structure", True)),
                min_delta_multiplier=float(strategy.get("min_delta_multiplier", 1.3)),
                min_signal_strength=float(strategy.get("min_signal_strength", 0.65)),
                rr_first=float(targets_cfg.get("rr_first", 0.8)),
                rr_second=float(targets_cfg.get("rr_second", 1.8)),
                atr_stop_multiplier=float(risk_cfg.get("atr_stop_multiplier", 1.5)),
            ),
            "risk": RiskManager(
                risk_pct=float(strategy.get("risk_pct", 0.01)),
                max_daily_drawdown_pct=float(risk_cfg.get("max_daily_drawdown_pct", 0.03)),
                max_consecutive_losses=int(risk_cfg.get("max_consecutive_losses", 3)),
                max_daily_trades=int(risk_cfg.get("max_daily_trades", 20)),
                session_start=str(strategy.get("session_start", "09:30")),
                session_end=str(strategy.get("session_end", "16:00")),
                tick_value=float(risk_cfg.get("tick_value", 5)),
                use_globex=bool(strategy.get("use_globex", False)),
            ),
            "execution": None,
            "pips": pips,
            "size_multiplier": size_multiplier,
            "last_price": 0.0,
            "atr": 20.0,
            "position": 0,
            "in_position": False,
        }
        _interval_counter[alias] = 0
    return _instrument_state[alias]


def handle_subscribe_instrument(
    addon: Any,
    alias: str,
    full_name: str,
    is_crypto: bool,
    pips: float,
    size_multiplier: float,
    instrument_multiplier: float,
    supported_features: Dict[str, object],
) -> None:
    logger.info("Subscribe instrument: %s (pips=%s, size_mult=%s)", alias, pips, size_multiplier)
    state = _get_state(alias, pips, size_multiplier)
    state["execution"] = ExecutionEngine(addon=addon, pips=pips, tick_value=risk_cfg.get("tick_value", 5))
    state["pips"] = pips
    state["size_multiplier"] = size_multiplier
    if bm:
        bm.subscribe_to_depth(addon, alias, 1)
        bm.subscribe_to_trades(addon, alias, 2)
        if supported_features.get("mbo"):
            bm.subscribe_to_mbo(addon, alias, 3)
        if supported_features.get("trading"):
            bm.subscribe_to_order_info(addon, alias, 4)
            bm.subscribe_to_position_updates(addon, alias, 5)
            bm.subscribe_to_balance_updates(addon, alias, 6)
    state["risk"].reset_daily()


def handle_unsubscribe_instrument(addon: Any, alias: str) -> None:
    logger.info("Unsubscribe instrument: %s", alias)
    _instrument_state.pop(alias, None)
    _interval_counter.pop(alias, None)


def on_depth(addon: Any, alias: str, is_bid: bool, price_level: int, size_level: int) -> None:
    state = _instrument_state.get(alias)
    if not state:
        return
    price = price_level * state["pips"]
    state["last_price"] = price


def on_trade(
    addon: Any,
    alias: str,
    price_level: int,
    size_level: int,
    is_otc: bool,
    is_bid: bool,
    is_execution_start: bool,
    is_execution_end: bool,
    aggressor_order_id: Optional[str],
    passive_order_id: Optional[str],
) -> None:
    state = _instrument_state.get(alias)
    if not state:
        return
    state["analyzer"].on_trade(price_level, size_level, is_bid)
    state["last_price"] = price_level * state["pips"]


def on_interval(addon: Any, alias: str) -> None:
    state = _instrument_state.get(alias)
    if not state or state.get("in_position"):
        return
    _interval_counter[alias] = _interval_counter.get(alias, 0) + 1
    # Every 0.1s; bar = 15s -> 150 intervals
    intervals_per_bar = max(1, int(BAR_INTERVAL_SEC * 10))
    if _interval_counter[alias] % intervals_per_bar != 0:
        return
    analyzer = state["analyzer"]
    bar = analyzer.start_new_bar()
    last_price = state["last_price"]
    if last_price <= 0:
        return
    profile = analyzer.build_volume_profile()
    sig_result = state["signal_gen"].generate(
        analyzer, profile, last_price, state["atr"], state["pips"]
    )
    if sig_result.signal == Signal.NONE:
        return
    risk_mgr = state["risk"]
    can_trade, reason = risk_mgr.can_trade(1_000_000.0)
    if not can_trade:
        if bm:
            bm.send_user_message(addon, alias, f"Blocked: {reason}")
        return
    size = risk_mgr.position_size(1_000_000.0, sig_result.stop_ticks, state["pips"])
    if size <= 0:
        return
    exec_engine = state["execution"]
    if exec_engine and mode != "backtest":
        req = BracketRequest(
            alias=alias,
            is_buy=(sig_result.signal == Signal.LONG),
            size=size,
            entry_price=last_price,
            stop_ticks=sig_result.stop_ticks,
            target1_ticks=sig_result.target1_ticks,
            target2_ticks=sig_result.target2_ticks,
            pips=state["pips"],
            scale_out_pct=float(targets_cfg.get("scale_out_pct", 0.5)),
        )
        order_id = exec_engine.place_bracket(req)
        if order_id:
            state["in_position"] = True
            if bm:
                bm.send_user_message(
                    addon, alias,
                    f"Signal: {sig_result.signal.name} | {sig_result.reason} | size={size}",
                )


def on_position_update(addon: Any, position_update: Dict[str, Any]) -> None:
    alias = position_update.get("instrumentAlias", "")
    state = _instrument_state.get(alias)
    if state is not None:
        state["position"] = position_update.get("position", 0)
        state["in_position"] = state["position"] != 0


def on_order_executed(addon: Any, alias: str, event: Dict[str, Any]) -> None:
    logger.info("Order executed: %s %s", alias, event)


if __name__ == "__main__":
    if not bm:
        print("Bookmap API not available. Run this script from within Bookmap.", flush=True)
        sys.exit(1)
    addon = bm.create_addon()
    bm.add_depth_handler(addon, on_depth)
    bm.add_trades_handler(addon, on_trade)
    bm.add_on_interval_handler(addon, on_interval)
    bm.add_on_position_update_handler(addon, on_position_update)
    bm.add_on_order_executed_handler(addon, on_order_executed)
    bm.start_addon(addon, handle_subscribe_instrument, handle_unsubscribe_instrument)
    logger.info("Fabio Bot add-on started. Enable for an instrument in Bookmap.")
    bm.wait_until_addon_is_turned_off(addon)
