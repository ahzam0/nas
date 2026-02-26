"""
Standalone backtester for Fabio-style order flow strategy.
Uses bar/tick data (CSV or DataFrame) and replays through order_flow_analyzer + signal_generator.
No Bookmap required. For 1-month NQ sample run and metrics.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

# Project root
_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))

from fabio_bot.order_flow_analyzer import OrderFlowAnalyzer, BarSnapshot, VolumeProfileResult
from fabio_bot.signal_generator import Signal, SignalGenerator
from fabio_bot.risk_manager import RiskManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PIPS_NQ = 0.25
SIZE_MULT = 1.0
TICK_VALUE_NQ = 5.0


@dataclass
class BacktestTrade:
    entry_time: str
    exit_time: str
    side: str
    entry_price: float
    exit_price: float
    size: int
    pnl: float
    pnl_ticks: float
    exit_reason: str  # target1, target2, stop, timeout


@dataclass
class BacktestResult:
    trades: List[BacktestTrade] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)
    initial_balance: float = 100_000.0
    final_balance: float = 100_000.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    total_trades: int = 0
    sharpe_ratio: float = 0.0

    def to_metrics(self) -> dict:
        return {
            "initial_balance": self.initial_balance,
            "final_balance": self.final_balance,
            "total_pnl": self.final_balance - self.initial_balance,
            "total_trades": self.total_trades,
            "win_rate": self.win_rate,
            "profit_factor": self.profit_factor,
            "max_drawdown": self.max_drawdown,
            "max_drawdown_pct": self.max_drawdown_pct,
            "sharpe_ratio": self.sharpe_ratio,
        }


def generate_sample_bars(n_bars: int = 8000, seed: int = 42, order_flow_rich: bool = False) -> pd.DataFrame:
    """Generate synthetic 15s-style bars. If order_flow_rich, add regimes of strong delta and big trades."""
    np.random.seed(seed)
    base = 20000.0
    pips = PIPS_NQ
    bars = []
    price = base
    # Regime: bias for order_flow_rich (persistent buy/sell pressure + occasional big lots)
    regime = 0  # -1 sell pressure, 0 neutral, 1 buy pressure
    regime_len = 0
    for i in range(n_bars):
        if order_flow_rich:
            if regime_len <= 0:
                regime_len = np.random.randint(30, 120)
                regime = np.random.choice([-1, 0, 1], p=[0.35, 0.3, 0.35])
            regime_len -= 1
            # Volume biased by regime; occasional big-trade bars (30+ contracts one side)
            base_buy = 40 + (25 if regime == 1 else (-10 if regime == -1 else 0)) + np.random.exponential(20)
            base_sell = 40 + (25 if regime == -1 else (-10 if regime == 1 else 0)) + np.random.exponential(20)
            if np.random.rand() < 0.08:
                base_buy += np.random.randint(25, 60) if regime >= 0 else 0
                base_sell += np.random.randint(25, 60) if regime <= 0 else 0
            buy_vol = max(5, base_buy + np.random.randn() * 15)
            sell_vol = max(5, base_sell + np.random.randn() * 15)
            ret = (buy_vol - sell_vol) / 100.0
        else:
            ret = np.random.randn() * 2.0 - 0.1 * (price - base) / 100
            buy_vol = max(0, np.random.exponential(50) + (10 if ret > 0 else 0))
            sell_vol = max(0, np.random.exponential(50) + (10 if ret < 0 else 0))
        price = price + ret * pips * 2
        price = max(base - 500, min(base + 500, price))
        open_p = price - ret * pips * 2
        high = max(open_p, price) + np.random.rand() * pips * 2
        low = min(open_p, price) - np.random.rand() * pips * 2
        bars.append({
            "open": open_p,
            "high": high,
            "low": low,
            "close": price,
            "buy_volume": max(1, buy_vol),
            "sell_volume": max(1, sell_vol),
            "bar_idx": i,
        })
    return pd.DataFrame(bars)


def bars_to_tick_stream(df: pd.DataFrame, ticks_per_bar: int = 20) -> pd.DataFrame:
    """Expand bars into tick-like rows for analyzer.on_trade simulation."""
    rows = []
    for _, r in df.iterrows():
        buy_vol = r["buy_volume"]
        sell_vol = r["sell_volume"]
        n_buy = max(1, int(buy_vol / 5))
        n_sell = max(1, int(sell_vol / 5))
        lo, hi = r["low"], r["high"]
        for _ in range(n_buy):
            p = lo + (hi - lo) * np.random.rand()
            rows.append({"price": p, "size": 5.0, "is_bid": True})
        for _ in range(n_sell):
            p = lo + (hi - lo) * np.random.rand()
            rows.append({"price": p, "size": 5.0, "is_bid": False})
    return pd.DataFrame(rows)


def run_backtest(
    df_bars: pd.DataFrame,
    initial_balance: float = 100_000.0,
    risk_pct: float = 0.01,
    big_trade_threshold: float = 30.0,
    min_delta: float = 500.0,
    bar_sec: float = 15.0,
    min_signal_strength: float = 0.0,
    rr_first: float = 0.8,
    rr_second: float = 1.8,
    min_delta_multiplier: float = 1.2,
    big_trade_edge: int = 2,
    atr_stop_multiplier: float = 1.5,
    max_daily_drawdown_pct: float = 0.03,
    tick_value: Optional[float] = None,
    session_bars_per_day: int = 0,
    session_start_bar: int = 0,
    session_end_bar: int = 0,
    trend_ma_bars: int = 0,
) -> BacktestResult:
    """Run backtest over bar data by simulating ticks and signal logic.
    Optional: session_bars_per_day/start/end for RTH filter (1m: 1440, 570, 960);
    trend_ma_bars > 0: only long when close > MA(close), only short when close < MA.
    """
    pips = PIPS_NQ
    size_mult = SIZE_MULT
    if tick_value is None:
        tick_value = TICK_VALUE_NQ
    df_bars = df_bars.copy()
    if trend_ma_bars > 0:
        df_bars["_trend_ma"] = df_bars["close"].rolling(int(trend_ma_bars), min_periods=1).mean()
    use_session = session_bars_per_day > 0 and session_end_bar > session_start_bar
    analyzer = OrderFlowAnalyzer(
        pips=pips,
        size_multiplier=size_mult,
        big_trade_threshold=big_trade_threshold,
        value_area_pct=0.70,
    )
    signal_gen = SignalGenerator(
        min_delta=min_delta,
        delta_sensitivity=1.0,
        big_trade_edge=big_trade_edge,
        require_absorption=False,
        require_at_structure=False,
        min_delta_multiplier=min_delta_multiplier,
        min_signal_strength=min_signal_strength,
        rr_first=rr_first,
        rr_second=rr_second,
        atr_stop_multiplier=atr_stop_multiplier,
    )
    risk_mgr = RiskManager(
        risk_pct=risk_pct,
        max_daily_drawdown_pct=max_daily_drawdown_pct,
        max_consecutive_losses=12,    # Allow more before halt so backtest runs full dataset
        max_daily_trades=500,  # High for backtest; drawdown/consecutive losses are the limit
        session_start="00:00",
        session_end="23:59",
        use_globex=True,
        tick_value=tick_value,
    )
    risk_mgr.set_session_equity(initial_balance)
    balance = initial_balance
    equity_curve = [balance]
    trades: List[BacktestTrade] = []
    in_position = False
    entry_price = 0.0
    entry_bar = 0
    position_side = ""
    position_size = 0
    stop_ticks = 20
    target1_ticks = 20
    target2_ticks = 40
    atr = 15.0 * pips
    # Reset risk state per "day" when we have a date column (real data); else every N bars
    last_reset_bar = 0
    reset_interval_bars = 400  # ~1 session for 1m bars

    for i, row in df_bars.iterrows():
        bar_idx = int(row.get("bar_idx", i))
        # New "day" reset: clear consecutive losses / daily counts only (keep session_equity = initial so 3% DD cap applies to full run)
        if "date" in df_bars.columns and bar_idx > 0 and i > 0:
            bar_date = row.get("date")
            prev_date = df_bars.iloc[i - 1].get("date")
            if bar_date != prev_date:
                risk_mgr.reset_daily()
        elif bar_idx - last_reset_bar >= reset_interval_bars:
            risk_mgr.reset_daily()
            last_reset_bar = bar_idx
        o, h, l, c = row["open"], row["high"], row["low"], row["close"]
        buy_vol = row.get("buy_volume", 50)
        sell_vol = row.get("sell_volume", 50)
        # Simulate ticks within bar for CVD; inject occasional big ticks (30+ contracts) so signals can trigger
        price_level = int(c / pips)
        big_size = 35  # above typical 30 threshold
        n_buy = max(1, int(buy_vol / 5))
        n_sell = max(1, int(sell_vol / 5))
        # When volume is large, make one tick "big" so big_trade cluster can form
        if buy_vol >= 45 and n_buy >= 2:
            analyzer.on_trade(price_level, int(big_size * size_mult), True)
            for _ in range(n_buy - 2):
                analyzer.on_trade(price_level, int(5 * size_mult), True)
        else:
            for _ in range(n_buy):
                analyzer.on_trade(price_level, int(5 * size_mult), True)
        if sell_vol >= 45 and n_sell >= 2:
            analyzer.on_trade(price_level, int(big_size * size_mult), False)
            for _ in range(n_sell - 2):
                analyzer.on_trade(price_level, int(5 * size_mult), False)
        else:
            for _ in range(n_sell):
                analyzer.on_trade(price_level, int(5 * size_mult), False)
        # New bar
        bar = analyzer.start_new_bar()
        if bar is None:
            continue
        profile = analyzer.build_volume_profile()
        last_price = c
        sig = signal_gen.generate(analyzer, profile, last_price, atr, pips)

        if in_position:
            # Check exit
            if position_side == "long":
                pnl_ticks = (c - entry_price) / pips
                if c <= entry_price - stop_ticks * pips:
                    pnl = -position_size * stop_ticks * pips * tick_value
                    balance += pnl
                    risk_mgr.record_trade(pnl)
                    trades.append(BacktestTrade(
                        entry_time=str(entry_bar), exit_time=str(bar_idx), side="long",
                        entry_price=entry_price, exit_price=entry_price - stop_ticks * pips,
                        size=position_size, pnl=pnl, pnl_ticks=-stop_ticks, exit_reason="stop",
                    ))
                    in_position = False
                elif c >= entry_price + target2_ticks * pips:
                    pnl = position_size * target2_ticks * pips * tick_value
                    balance += pnl
                    risk_mgr.record_trade(pnl)
                    trades.append(BacktestTrade(
                        entry_time=str(entry_bar), exit_time=str(bar_idx), side="long",
                        entry_price=entry_price, exit_price=entry_price + target2_ticks * pips,
                        size=position_size, pnl=pnl, pnl_ticks=target2_ticks, exit_reason="target2",
                    ))
                    in_position = False
                elif c >= entry_price + target1_ticks * pips:
                    pnl = position_size * target1_ticks * pips * tick_value
                    balance += pnl
                    risk_mgr.record_trade(pnl)
                    trades.append(BacktestTrade(
                        entry_time=str(entry_bar), exit_time=str(bar_idx), side="long",
                        entry_price=entry_price, exit_price=entry_price + target1_ticks * pips,
                        size=position_size, pnl=pnl, pnl_ticks=target1_ticks, exit_reason="target1",
                    ))
                    in_position = False
            else:
                pnl_ticks = (entry_price - c) / pips
                if c >= entry_price + stop_ticks * pips:
                    pnl = -position_size * stop_ticks * pips * tick_value
                    balance += pnl
                    risk_mgr.record_trade(pnl)
                    trades.append(BacktestTrade(
                        entry_time=str(entry_bar), exit_time=str(bar_idx), side="short",
                        entry_price=entry_price, exit_price=entry_price + stop_ticks * pips,
                        size=position_size, pnl=pnl, pnl_ticks=-stop_ticks, exit_reason="stop",
                    ))
                    in_position = False
                elif c <= entry_price - target2_ticks * pips:
                    pnl = position_size * target2_ticks * pips * tick_value
                    balance += pnl
                    risk_mgr.record_trade(pnl)
                    trades.append(BacktestTrade(
                        entry_time=str(entry_bar), exit_time=str(bar_idx), side="short",
                        entry_price=entry_price, exit_price=entry_price - target2_ticks * pips,
                        size=position_size, pnl=pnl, pnl_ticks=target2_ticks, exit_reason="target2",
                    ))
                    in_position = False
                elif c <= entry_price - target1_ticks * pips:
                    pnl = position_size * target1_ticks * pips * tick_value
                    balance += pnl
                    risk_mgr.record_trade(pnl)
                    trades.append(BacktestTrade(
                        entry_time=str(entry_bar), exit_time=str(bar_idx), side="short",
                        entry_price=entry_price, exit_price=entry_price - target1_ticks * pips,
                        size=position_size, pnl=pnl, pnl_ticks=target1_ticks, exit_reason="target1",
                    ))
                    in_position = False
            equity_curve.append(balance)
            continue

        # Optional: only take new trades in session window (e.g. US RTH) and with trend
        if use_session:
            bar_in_day = bar_idx % session_bars_per_day
            if bar_in_day < session_start_bar or bar_in_day > session_end_bar:
                equity_curve.append(balance)
                continue
        if trend_ma_bars > 0 and sig.signal != Signal.NONE:
            ma = row.get("_trend_ma", c)
            if sig.signal == Signal.LONG and c <= ma:
                equity_curve.append(balance)
                continue
            if sig.signal == Signal.SHORT and c >= ma:
                equity_curve.append(balance)
                continue

        can_trade, _ = risk_mgr.can_trade(balance)
        if not can_trade or sig.signal == Signal.NONE or sig.strength < min_signal_strength:
            equity_curve.append(balance)
            continue

        position_size = risk_mgr.position_size(balance, sig.stop_ticks, pips)
        if position_size <= 0:
            equity_curve.append(balance)
            continue

        entry_price = last_price
        entry_bar = bar_idx
        stop_ticks = sig.stop_ticks
        target1_ticks = max(8, sig.target1_ticks)
        target2_ticks = max(16, sig.target2_ticks)
        position_side = "long" if sig.signal == Signal.LONG else "short"
        in_position = True
        equity_curve.append(balance)

    # Compute metrics
    total = len(trades)
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    win_count = len(wins)
    gross_profit = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (gross_profit and 99.0)
    win_rate = (win_count / total * 100) if total else 0
    peak = initial_balance
    max_dd = 0.0
    for b in equity_curve:
        peak = max(peak, b)
        max_dd = max(max_dd, peak - b)
    max_dd_pct = (max_dd / peak * 100) if peak > 0 else 0
    returns = np.diff(equity_curve)
    sharpe = (np.mean(returns) / np.std(returns) * np.sqrt(252 * 24 * 4)) if len(returns) > 1 and np.std(returns) > 0 else 0.0

    return BacktestResult(
        trades=trades,
        equity_curve=equity_curve,
        initial_balance=initial_balance,
        final_balance=balance,
        win_rate=win_rate,
        profit_factor=profit_factor,
        max_drawdown=max_dd,
        max_drawdown_pct=max_dd_pct,
        total_trades=total,
        sharpe_ratio=float(sharpe),
    )


def get_latest_signal(
    df_bars: pd.DataFrame,
    min_signal_strength: float = 0.0,
    min_delta: float = 500.0,
    min_delta_multiplier: float = 1.2,
    big_trade_threshold: float = 30.0,
    big_trade_edge: int = 2,
    rr_first: float = 0.8,
    rr_second: float = 1.8,
    atr_stop_multiplier: float = 1.5,
) -> Tuple[Optional[Signal], float, float, dict]:
    """
    Run analyzer + signal_gen on bar data and return signal at the last bar.
    Returns (signal_enum, strength, last_price, features_dict).
    features_dict can be used by ML filter.
    """
    pips = PIPS_NQ
    size_mult = SIZE_MULT
    analyzer = OrderFlowAnalyzer(
        pips=pips,
        size_multiplier=size_mult,
        big_trade_threshold=big_trade_threshold,
        value_area_pct=0.70,
    )
    signal_gen = SignalGenerator(
        min_delta=min_delta,
        delta_sensitivity=1.0,
        big_trade_edge=big_trade_edge,
        require_absorption=False,
        require_at_structure=False,
        min_delta_multiplier=min_delta_multiplier,
        min_signal_strength=min_signal_strength,
        rr_first=rr_first,
        rr_second=rr_second,
        atr_stop_multiplier=atr_stop_multiplier,
    )
    atr = 15.0 * pips
    last_sig = Signal.NONE
    last_strength = 0.0
    last_price = 0.0
    last_features: dict = {}

    for i, row in df_bars.iterrows():
        bar_idx = int(row.get("bar_idx", i))
        o, h, l, c = row["open"], row["high"], row["low"], row["close"]
        buy_vol = row.get("buy_volume", 50)
        sell_vol = row.get("sell_volume", 50)
        price_level = int(c / pips)
        big_size = 35
        n_buy = max(1, int(buy_vol / 5))
        n_sell = max(1, int(sell_vol / 5))
        if buy_vol >= 45 and n_buy >= 2:
            analyzer.on_trade(price_level, int(big_size * size_mult), True)
            for _ in range(n_buy - 2):
                analyzer.on_trade(price_level, int(5 * size_mult), True)
        else:
            for _ in range(n_buy):
                analyzer.on_trade(price_level, int(5 * size_mult), True)
        if sell_vol >= 45 and n_sell >= 2:
            analyzer.on_trade(price_level, int(big_size * size_mult), False)
            for _ in range(n_sell - 2):
                analyzer.on_trade(price_level, int(5 * size_mult), False)
        else:
            for _ in range(n_sell):
                analyzer.on_trade(price_level, int(5 * size_mult), False)
        bar = analyzer.start_new_bar()
        if bar is None:
            continue
        profile = analyzer.build_volume_profile()
        last_price = c
        sig_result = signal_gen.generate(analyzer, profile, last_price, atr, pips)
        last_sig = sig_result.signal
        last_strength = sig_result.strength
        if (h - l) > 0:
            atr = (h - l) * 0.5 + atr * 0.5
        big_buy, big_sell = analyzer.get_big_trade_cluster(30)
        stop_ticks = getattr(sig_result, "stop_ticks", 20)
        t1_ticks = getattr(sig_result, "target1_ticks", 20)
        t2_ticks = getattr(sig_result, "target2_ticks", 40)
        # SL/TP prices for LONG: SL below entry, TP above. SHORT: opposite.
        if last_sig == Signal.LONG:
            sl_price = last_price - stop_ticks * pips
            tp1_price = last_price + t1_ticks * pips
            tp2_price = last_price + t2_ticks * pips
        elif last_sig == Signal.SHORT:
            sl_price = last_price + stop_ticks * pips
            tp1_price = last_price - t1_ticks * pips
            tp2_price = last_price - t2_ticks * pips
        else:
            sl_price = tp1_price = tp2_price = last_price
        last_features = {
            "strength": last_strength,
            "cvd": analyzer.get_cvd(),
            "close": c,
            "poc": profile.poc,
            "atr": atr,
            "big_buy": float(big_buy),
            "big_sell": float(big_sell),
            "dist_poc": abs(c - profile.poc) if profile.poc else 0,
            "dist_val": abs(c - profile.val) if profile.val else 0,
            "dist_vah": abs(c - profile.vah) if profile.vah else 0,
            "bar_delta": buy_vol - sell_vol,
            "side_long": 1.0 if last_sig == Signal.LONG else 0.0,
            "reason": getattr(sig_result, "reason", "no_setup"),
            "stop_ticks": stop_ticks,
            "target1_ticks": t1_ticks,
            "target2_ticks": t2_ticks,
            "sl_price": sl_price,
            "tp1_price": tp1_price,
            "tp2_price": tp2_price,
        }

    return last_sig, last_strength, last_price, last_features


def main():
    parser = argparse.ArgumentParser(description="Fabio Bot Backtest")
    parser.add_argument("--bars", type=int, default=8000, help="Number of bars (synthetic)")
    parser.add_argument("--data", type=str, default="", help="CSV path with columns: open,high,low,close,buy_volume,sell_volume")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--risk", type=float, default=0.01)
    parser.add_argument("--big-trade", type=float, default=30.0)
    parser.add_argument("--min-delta", type=float, default=500.0)
    parser.add_argument("--min-strength", type=float, default=0.0, help="Min signal strength (0.6-0.75 for high win rate)")
    parser.add_argument("--rr-first", type=float, default=0.8, help="First target R:R (0.8 = lock wins faster)")
    parser.add_argument("--rr-second", type=float, default=1.8, help="Second target R:R")
    parser.add_argument("--full", action="store_true", help="Full backtest: 120k bars, order-flow-rich data, relaxed filters")
    parser.add_argument("--order-flow-rich", action="store_true", help="Use synthetic data with delta regimes and big trades")
    parser.add_argument("--initial-balance", type=float, default=100_000.0, help="Starting account balance (default 100000)")
    parser.add_argument("--fetch-real", action="store_true", help="Download real NQ futures data (yfinance) and run backtest on it")
    parser.add_argument("--symbol", type=str, default="NQ=F", help="Symbol for real data (e.g. NQ=F, MNQ=F)")
    parser.add_argument("--interval", type=str, default="1h", help="Bar interval: 1d, 1h, 1m (scalp=1m only), 5m disabled")
    parser.add_argument("--period", type=str, default="60d", help="Data period for real data: 60d, 1mo, 3mo, 6mo, 1y, 2y, max")
    parser.add_argument("--start", type=str, default="", help="Start date YYYY-MM-DD (overrides --period)")
    parser.add_argument("--end", type=str, default="", help="End date YYYY-MM-DD")
    parser.add_argument("--save-csv", type=str, default="", help="Save fetched real data to this CSV path")
    parser.add_argument("--min-delta-multiplier", type=float, default=1.4, help="Stricter CVD multiplier (optimized 1.4)")
    parser.add_argument("--big-trade-edge", type=int, default=2, help="Min big-buy vs big-sell edge")
    parser.add_argument("--atr-stop", type=float, default=1.5, help="ATR multiplier for stop (1.25 = tighter, lower DD)")
    parser.add_argument("--max-dd", type=float, default=0.03, help="Max drawdown from peak to pause (e.g. 0.025 = 2.5%%)")
    parser.add_argument("--scalp", action="store_true", help="Scalp mode: 1m only, max trades (lower thresholds)")
    parser.add_argument("--tick-value", type=float, default=None, help="Tick value in USD (NQ=5, MNQ=1). Auto-set for MNQ=F.")
    args = parser.parse_args()

    if args.scalp:
        # Default NQ scalp params (best_params_1m.json)
        args.min_strength = 0.58
        args.min_delta = 383
        args.min_delta_multiplier = 1.19
        args.big_trade_edge = 2
        args.big_trade = 27
        args.rr_first = 0.62
        args.rr_second = 1.28
        if args.risk == 0.01:
            args.risk = 0.0085
        args.interval = "1m"
        args.period = "7d"
        # MNQ: use tuned params for higher WR, better PF, lower DD (best_params_mnq_1m.json)
        is_mnq = (args.symbol and "MNQ" in args.symbol.upper()) or (args.data and "mnq" in args.data.lower())
        mnq_json = _ROOT / "data" / "best_params_mnq_1m.json"
        if is_mnq and mnq_json.exists():
            try:
                import json
                with open(mnq_json) as f:
                    best = json.load(f)
                p = best.get("params", {})
                if p:
                    args.min_strength = p.get("min_signal_strength", args.min_strength)
                    args.min_delta = p.get("min_delta", args.min_delta)
                    args.min_delta_multiplier = p.get("min_delta_multiplier", args.min_delta_multiplier)
                    args.big_trade = p.get("big_trade_threshold", args.big_trade)
                    args.big_trade_edge = p.get("big_trade_edge", args.big_trade_edge)
                    args.rr_first = p.get("rr_first", args.rr_first)
                    args.rr_second = p.get("rr_second", args.rr_second)
                    args.risk = p.get("risk_pct", args.risk)
                    args.atr_stop = p.get("atr_stop_multiplier", getattr(args, "atr_stop", 1.5))
                    args.max_dd = p.get("max_daily_drawdown_pct", getattr(args, "max_dd", 0.03))
                    args.session_bars_per_day = p.get("session_bars_per_day", 0)
                    args.session_start_bar = p.get("session_start_bar", 0)
                    args.session_end_bar = p.get("session_end_bar", 0)
                    args.trend_ma_bars = p.get("trend_ma_bars", 0)
                    logger.info("Using MNQ-tuned params from data/best_params_mnq_1m.json")
            except Exception:
                pass
        logger.info("Scalp mode: 1m only, optimized for WR/PF/DD")

    if args.full:
        args.bars = 120000
        args.order_flow_rich = True
        if args.min_delta == 500.0:
            args.min_delta = 380.0
        logger.info("Full backtest: %d bars, order-flow-rich data", args.bars)

    if args.fetch_real:
        try:
            from fabio_bot.fetch_market_data import fetch_nq_yfinance, fetch_nq_yahoo_chart_api
        except ImportError:
            raise SystemExit("Real data fetch requires yfinance. Install with: pip install yfinance")
        start = args.start or None
        end = args.end or None
        period = args.period if not (start and end) else None
        df = fetch_nq_yfinance(symbol=args.symbol, interval=args.interval, period=period, start=start, end=end)
        if df.empty:
            logger.info("Trying Yahoo Chart API fallback for real data...")
            df = fetch_nq_yahoo_chart_api(symbol=args.symbol, interval=args.interval, period=period, start=start, end=end)
        if df.empty:
            fallback_csv = (_ROOT / "data" / "nq_realistic_sample.csv").resolve()
            if fallback_csv.exists():
                logger.warning("Live fetch failed (Yahoo often blocks). Using realistic sample: %s", fallback_csv)
                df = pd.read_csv(fallback_csv)
                for col in ["open", "high", "low", "close"]:
                    if col not in df.columns:
                        raise SystemExit("Fallback CSV missing column: " + col)
                if "buy_volume" not in df.columns:
                    df["buy_volume"] = 50
                if "sell_volume" not in df.columns:
                    df["sell_volume"] = 50
                df["bar_idx"] = range(len(df))
                total_vol = df["buy_volume"] + df["sell_volume"]
                if total_vol.mean() > 500:
                    scale = (120.0 / total_vol.replace(0, 1)).clip(upper=1.0)
                    df["buy_volume"] = (df["buy_volume"] * scale).clip(lower=1)
                    df["sell_volume"] = (df["sell_volume"] * scale).clip(lower=1)
                args._used_fallback_sample = True  # so we can label metrics
            else:
                raise SystemExit(
                    "No real data returned (Yahoo may be blocking). Export NQ bars from your broker to CSV and run: "
                    "python backtest.py --data path/to/nq_bars.csv"
                )
        else:
            if args.save_csv:
                os.makedirs(os.path.dirname(args.save_csv) or ".", exist_ok=True)
                df.to_csv(args.save_csv, index=False)
                logger.info("Saved %d bars to %s", len(df), args.save_csv)
            # Scale volume so CVD/big-trade logic (tuned for 15s bars) is in range; preserve buy/sell ratio
            total_vol = df["buy_volume"] + df["sell_volume"]
            target_per_bar = 120.0
            scale = (target_per_bar / total_vol.replace(0, 1)).clip(upper=1.0)
            df["buy_volume"] = (df["buy_volume"] * scale).clip(lower=1)
            df["sell_volume"] = (df["sell_volume"] * scale).clip(lower=1)
            logger.info("Running backtest on REAL market data: %s %s (%d bars)", args.symbol, args.interval, len(df))
    elif args.data and os.path.exists(args.data):
        df = pd.read_csv(args.data)
        for col in ["open", "high", "low", "close"]:
            if col not in df.columns:
                raise SystemExit(f"CSV must have column: {col}")
        if "buy_volume" not in df.columns:
            df["buy_volume"] = 50
        if "sell_volume" not in df.columns:
            df["sell_volume"] = 50
        df["bar_idx"] = range(len(df))
        # Scale volume if CSV has large bars (e.g. real 1d/1h) so CVD/big-trade logic is in range
        total_vol = df["buy_volume"] + df["sell_volume"]
        if total_vol.mean() > 500:
            target_per_bar = 120.0
            scale = (target_per_bar / total_vol.replace(0, 1)).clip(upper=1.0)
            df["buy_volume"] = (df["buy_volume"] * scale).clip(lower=1)
            df["sell_volume"] = (df["sell_volume"] * scale).clip(lower=1)
            logger.info("Scaled volume for strategy (avg was %.0f)", total_vol.mean())
        logger.info("Running backtest on CSV data: %s (%d bars)", args.data, len(df))
    else:
        df = generate_sample_bars(n_bars=args.bars, seed=args.seed, order_flow_rich=args.order_flow_rich)
        logger.info("Running backtest on synthetic data (%d bars)", len(df))

    tick_value = args.tick_value
    if tick_value is None and args.symbol and "MNQ" in args.symbol.upper():
        tick_value = 1.0
        logger.info("MNQ detected: using tick value $1 (micro contract)")
    elif tick_value is None and args.data and "mnq" in args.data.lower():
        tick_value = 1.0
        logger.info("MNQ data detected: using tick value $1 (micro contract)")
    elif tick_value is None:
        tick_value = TICK_VALUE_NQ

    logger.info("Backtest on %d bars...", len(df))
    res = run_backtest(
        df,
        initial_balance=args.initial_balance,
        risk_pct=args.risk,
        big_trade_threshold=args.big_trade,
        min_delta=args.min_delta,
        min_signal_strength=args.min_strength,
        rr_first=args.rr_first,
        rr_second=args.rr_second,
        min_delta_multiplier=args.min_delta_multiplier,
        big_trade_edge=args.big_trade_edge,
        atr_stop_multiplier=getattr(args, "atr_stop", 1.5),
        max_daily_drawdown_pct=getattr(args, "max_dd", 0.03),
        tick_value=tick_value,
        session_bars_per_day=getattr(args, "session_bars_per_day", 0),
        session_start_bar=getattr(args, "session_start_bar", 0),
        session_end_bar=getattr(args, "session_end_bar", 0),
        trend_ma_bars=getattr(args, "trend_ma_bars", 0),
    )
    metrics = res.to_metrics()
    logger.info("Backtest complete.")
    data_src = "REAL MARKET DATA" if (args.fetch_real and not getattr(args, "_used_fallback_sample", False)) else ("REALISTIC SAMPLE (live fetch failed)" if getattr(args, "_used_fallback_sample", False) else ("CSV: " + args.data if args.data else "synthetic"))
    print("\n--- Backtest Metrics (%s) ---" % data_src)
    print(f"  Initial Balance:  ${metrics['initial_balance']:,.2f}")
    print(f"  Final Balance:    ${metrics['final_balance']:,.2f}")
    print(f"  Total P/L:        ${metrics['total_pnl']:,.2f}")
    print(f"  Total Trades:     {metrics['total_trades']}")
    print(f"  Win Rate:         {metrics['win_rate']:.1f}%")
    print(f"  Profit Factor:   {metrics['profit_factor']:.2f}")
    print(f"  Max Drawdown:     ${metrics['max_drawdown']:,.2f} ({metrics['max_drawdown_pct']:.1f}%)")
    print(f"  Sharpe Ratio:     {metrics['sharpe_ratio']:.2f}")
    print("--------------------------------------------------------\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
