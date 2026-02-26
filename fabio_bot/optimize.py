"""
Strategy optimization: hit-and-try to reach ~80% win rate with good profit factor.
Runs backtests over a parameter grid and selects the best combo for live-style stats.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from backtest import generate_sample_bars, run_backtest

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

TARGET_WIN_RATE = 78.0   # aim for 80%, accept >= 78%
TARGET_PROFIT_FACTOR = 1.5
MIN_TRADES = 25
INITIAL_BALANCE = 50_000.0
OPTIMIZE_BARS = 20_000   # faster for many runs


def score_result(win_rate: float, profit_factor: float, total_trades: int, max_dd_pct: float) -> float:
    """Higher is better. Prioritize win rate near 80%, then profit factor, penalize low trades."""
    if total_trades < MIN_TRADES:
        return -1e9
    wr_score = 100 - abs(win_rate - 80.0)   # best at 80%
    pf_score = min(profit_factor * 25, 50)   # cap
    dd_penalty = max(0, max_dd_pct - 10) * 2
    return wr_score + pf_score - dd_penalty


def run_one(
    df: pd.DataFrame,
    min_signal_strength: float,
    min_delta: float,
    rr_first: float,
    rr_second: float,
    min_delta_multiplier: float,
    big_trade_edge: int,
    big_trade_threshold: float,
) -> Tuple[Dict[str, Any], float]:
    res = run_backtest(
        df,
        initial_balance=INITIAL_BALANCE,
        risk_pct=0.01,
        big_trade_threshold=big_trade_threshold,
        min_delta=min_delta,
        min_signal_strength=min_signal_strength,
        rr_first=rr_first,
        rr_second=rr_second,
        min_delta_multiplier=min_delta_multiplier,
        big_trade_edge=big_trade_edge,
    )
    m = res.to_metrics()
    sc = score_result(m["win_rate"], m["profit_factor"], m["total_trades"], m["max_drawdown_pct"])
    return m, sc


def main():
    print("Loading data...")
    df = generate_sample_bars(n_bars=OPTIMIZE_BARS, seed=42, order_flow_rich=True)
    # Backtest injects big ticks per-bar when processing; no need to modify df here.

    param_grid = [
        {"min_signal_strength": ms, "min_delta": md, "rr_first": r1, "rr_second": r2,
         "min_delta_multiplier": mdm, "big_trade_edge": be, "big_trade_threshold": bt}
        for ms in [0.70, 0.75, 0.78, 0.82]
        for md in [360, 420, 480]
        for r1 in [0.65, 0.75, 0.82]
        for r2 in [1.5, 1.8, 2.0]
        for mdm in [1.2, 1.3, 1.4]
        for be in [2, 3]
        for bt in [28, 32]
    ]
    np.random.seed(123)
    if len(param_grid) > 50:
        param_grid = [param_grid[i] for i in np.random.choice(len(param_grid), 50, replace=False)]

    print(f"Running {len(param_grid)} parameter combinations (target: ~80% win rate, good PF)...")
    results: List[Tuple[Dict, float, Dict[str, Any]]] = []
    for i, p in enumerate(param_grid):
        try:
            m, sc = run_one(df, **p)
            results.append((m, sc, p))
        except Exception as e:
            logger.warning("Run failed %s: %s", p, e)
        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{len(param_grid)} done...")

    # Sort by score desc, then by win_rate desc
    results.sort(key=lambda x: (-x[1], -x[0]["win_rate"], -x[0]["profit_factor"]))

    # Filter: win_rate >= TARGET_WIN_RATE, profit_factor >= TARGET_PROFIT_FACTOR, enough trades
    good = [(m, sc, p) for m, sc, p in results if m["total_trades"] >= MIN_TRADES and m["win_rate"] >= TARGET_WIN_RATE and m["profit_factor"] >= TARGET_PROFIT_FACTOR]
    if not good:
        # Take best by score even if below target
        best = results[0]
        print("\nNo combo reached target (78% WR, 1.5 PF). Best by score:")
    else:
        best = good[0]
        print(f"\nBest combo meeting target (>=78% WR, >=1.5 PF, >={MIN_TRADES} trades):")

    m, sc, p = best
    print(f"  Win Rate:       {m['win_rate']:.1f}%")
    print(f"  Profit Factor: {m['profit_factor']:.2f}")
    print(f"  Total Trades:  {m['total_trades']}")
    print(f"  Max Drawdown:  {m['max_drawdown_pct']:.1f}%")
    print(f"  Total P/L:     ${m['total_pnl']:,.2f}")
    print(f"  Params: {p}")

    out = ROOT / "data" / "best_params.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump({"metrics": m, "params": p}, f, indent=2)
    print(f"\nSaved to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
