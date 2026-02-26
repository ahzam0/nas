"""
Optimize scalp params on real 1m data to improve win rate, profit factor, and max drawdown.
Supports NQ (default) and MNQ via --data and --tick-value.
"""
import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import pandas as pd

from backtest import run_backtest

logging.basicConfig(level=logging.WARNING)

DATA_1M = ROOT / "data" / "nq_1m_live.csv"
INITIAL_BALANCE = 50_000.0
MIN_TRADES = 20  # Allow fewer trades for higher-quality (stricter filters)


def score(wr: float, pf: float, dd_pct: float, trades: int, pnl: float = 0) -> float:
    """Higher better. Maximize WR, PF; minimize DD; prefer positive P/L."""
    if trades < MIN_TRADES:
        return -1e9
    if pnl < 0:
        return -1e9  # require profitable
    # Prioritize: win rate, profit factor, then low drawdown
    wr_term = wr * 1.6  # stronger weight on win rate
    pf_term = min(pf, 5) * 28  # stronger weight on profit factor
    dd_term = max(0, 25 - dd_pct) * 5.0  # lower DD = much higher score
    pnl_term = (pnl / 1000) * 1.0
    return wr_term + pf_term + dd_term + pnl_term


def main():
    parser = argparse.ArgumentParser(description="Optimize 1m scalp params for WR, PF, low DD")
    parser.add_argument("--data", type=str, default="", help="CSV path (e.g. data/mnq_1m.csv). Default: data/nq_1m_live.csv")
    parser.add_argument("--tick-value", type=float, default=None, help="Tick value (MNQ=1, NQ=5). Auto from --data path if not set.")
    parser.add_argument("--quick", action="store_true", help="Smaller grid (60 + 24 local) for faster run.")
    parser.add_argument("--fine", action="store_true", help="Fine-tune only: load best_params, run tiny grid around it (~48 runs).")
    args, _ = parser.parse_known_args()

    data_path = Path(args.data) if args.data else DATA_1M
    tick_val = args.tick_value
    if tick_val is None and "mnq" in data_path.name.lower():
        tick_val = 1.0
    else:
        tick_val = tick_val if tick_val is not None else 5.0

    if not data_path.exists():
        print(f"Missing {data_path}. Run: python backtest.py --fetch-real --symbol MNQ=F --scalp --save-csv data/mnq_1m.csv")
        return 1
    df = pd.read_csv(data_path)
    for col in ["open", "high", "low", "close"]:
        if col not in df.columns:
            print(f"CSV missing {col}")
            return 1
    if "buy_volume" not in df.columns:
        df["buy_volume"] = 50
    if "sell_volume" not in df.columns:
        df["sell_volume"] = 50
    df["bar_idx"] = range(len(df))
    if (df["buy_volume"] + df["sell_volume"]).mean() > 500:
        total_vol = df["buy_volume"] + df["sell_volume"]
        scale = (120.0 / total_vol.replace(0, 1)).clip(upper=1.0)
        df["buy_volume"] = (df["buy_volume"] * scale).clip(lower=1)
        df["sell_volume"] = (df["sell_volume"] * scale).clip(lower=1)

    import random

    # --- Fine mode: tiny grid around existing best params ---
    if args.fine:
        out_name = "best_params_mnq_1m.json" if "mnq" in str(data_path).lower() else "best_params_1m.json"
        best_file = ROOT / "data" / out_name
        if not best_file.exists():
            print(f"No {best_file}. Run full optimization first.")
            return 1
        with open(best_file) as f:
            data = json.load(f)
        b = data.get("params", {})
        if not b:
            print("No params in file.")
            return 1
        # Very tight steps
        ms_vals = [round(b["min_signal_strength"] + x, 2) for x in (-0.02, 0, 0.02)]
        ms_vals = [x for x in ms_vals if 0.50 <= x <= 0.75]
        md_vals = [b["min_delta"] + x for x in (-10, 0, 10)]
        md_vals = [x for x in md_vals if 350 <= x <= 520]
        r1_vals = [round(b["rr_first"] + x, 2) for x in (-0.02, 0, 0.02)]
        r1_vals = [x for x in r1_vals if 0.48 <= x <= 0.72]
        r2_vals = [round(b["rr_second"] + x, 2) for x in (-0.06, 0, 0.06)]
        r2_vals = [x for x in r2_vals if 1.0 <= x <= 1.6]
        mdm_vals = [round(b["min_delta_multiplier"] + x, 2) for x in (-0.03, 0, 0.03)]
        mdm_vals = [x for x in mdm_vals if 1.1 <= x <= 1.45]
        bt_vals = [b["big_trade_threshold"] + x for x in (-1, 0, 1)]
        bt_vals = [x for x in bt_vals if 26 <= x <= 34]
        risk_vals = [round(b["risk_pct"] + x, 4) for x in (-0.0005, 0, 0.0005)]
        risk_vals = [x for x in risk_vals if 0.004 <= x <= 0.01]
        atr_vals = [round(b["atr_stop_multiplier"] + x, 2) for x in (-0.05, 0, 0.05)]
        atr_vals = [x for x in atr_vals if 1.2 <= x <= 1.75]
        dd_vals = sorted(set([0.015, 0.02, 0.022, 0.025, b.get("max_daily_drawdown_pct", 0.025)]))
        bte_vals = [2, 3] if b.get("big_trade_edge", 2) == 2 else [2, 3]
        fine_grid = [
            {"min_signal_strength": ms, "min_delta": md, "rr_first": r1, "rr_second": r2,
             "min_delta_multiplier": mdm, "big_trade_edge": bte, "big_trade_threshold": bt,
             "risk_pct": risk, "atr_stop_multiplier": atr, "max_daily_drawdown_pct": dd_cap}
            for ms in (ms_vals or [b["min_signal_strength"]])
            for md in (md_vals or [b["min_delta"]])
            for r1 in (r1_vals or [b["rr_first"]])
            for r2 in (r2_vals or [b["rr_second"]])
            for mdm in (mdm_vals or [b["min_delta_multiplier"]])
            for bt in (bt_vals or [b["big_trade_threshold"]])
            for risk in (risk_vals or [b["risk_pct"]])
            for atr in (atr_vals or [b["atr_stop_multiplier"]])
            for dd_cap in dd_vals
            for bte in bte_vals
        ]
        fine_grid = random.sample(fine_grid, min(48, len(fine_grid)))
        best_score = -1e9
        best_metrics = None
        best_params = None
        for i, p in enumerate(fine_grid):
            res = run_backtest(
                df, initial_balance=INITIAL_BALANCE, risk_pct=p["risk_pct"],
                big_trade_threshold=p["big_trade_threshold"], min_delta=p["min_delta"],
                min_signal_strength=p["min_signal_strength"], rr_first=p["rr_first"],
                rr_second=p["rr_second"], min_delta_multiplier=p["min_delta_multiplier"],
                big_trade_edge=p["big_trade_edge"], atr_stop_multiplier=p["atr_stop_multiplier"],
                max_daily_drawdown_pct=p.get("max_daily_drawdown_pct", 0.03), tick_value=tick_val,
            )
            m = res.to_metrics()
            sc = score(m["win_rate"], m["profit_factor"], m["max_drawdown_pct"], m["total_trades"], m["total_pnl"])
            if sc > best_score:
                best_score = sc
                best_metrics = m
                best_params = dict(p)
            if (i + 1) % 12 == 0:
                print(f"  Fine {i+1}/{len(fine_grid)}...")
        if best_params is None:
            print("No valid run in fine grid.")
            return 1
        print("\n--- Best (fine-tuned) ---")
        print(f"  Win Rate:       {best_metrics['win_rate']:.1f}%")
        print(f"  Profit Factor:  {best_metrics['profit_factor']:.2f}")
        print(f"  Max Drawdown:   {best_metrics['max_drawdown_pct']:.1f}%")
        print(f"  Total Trades:   {best_metrics['total_trades']}")
        print(f"  Total P/L:     ${best_metrics['total_pnl']:,.2f}")
        out = ROOT / "data" / out_name
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w") as f:
            json.dump({"metrics": best_metrics, "params": best_params, "tick_value": tick_val}, f, indent=2)
        print(f"Saved to {out}")
        return 0

    # Grid tuned for high WR, high PF, low DD (stricter filters + tight DD cap)
    base = [
        {"min_signal_strength": ms, "min_delta": md, "rr_first": r1, "rr_second": r2,
         "min_delta_multiplier": mdm, "big_trade_edge": bte, "big_trade_threshold": bt,
         "risk_pct": risk, "atr_stop_multiplier": atr, "max_daily_drawdown_pct": dd_cap}
        for ms in [0.62, 0.64, 0.66, 0.68]   # Stricter = higher WR, fewer bad trades
        for md in [420, 450, 480, 500]
        for r1 in [0.52, 0.56, 0.60, 0.62]
        for r2 in [1.15, 1.22, 1.30, 1.36]
        for mdm in [1.22, 1.28, 1.34]
        for bt in [28, 30, 32]
        for risk in [0.005, 0.006, 0.007]
        for atr in [1.28, 1.38, 1.46, 1.54]
        for dd_cap in [0.015, 0.02, 0.025]
        for bte in [2, 3]
    ]
    random.seed(789)
    grid_size = 60 if args.quick else 150
    param_grid = random.sample(base, min(grid_size, len(base)))

    best_score = -1e9
    best_metrics = None
    best_params = None
    for i, p in enumerate(param_grid):
        res = run_backtest(
            df,
            initial_balance=INITIAL_BALANCE,
            risk_pct=p["risk_pct"],
            big_trade_threshold=p["big_trade_threshold"],
            min_delta=p["min_delta"],
            min_signal_strength=p["min_signal_strength"],
            rr_first=p["rr_first"],
            rr_second=p["rr_second"],
            min_delta_multiplier=p["min_delta_multiplier"],
            big_trade_edge=p["big_trade_edge"],
            atr_stop_multiplier=p["atr_stop_multiplier"],
            max_daily_drawdown_pct=p.get("max_daily_drawdown_pct", 0.03),
            tick_value=tick_val,
        )
        m = res.to_metrics()
        sc = score(m["win_rate"], m["profit_factor"], m["max_drawdown_pct"], m["total_trades"], m["total_pnl"])
        if sc > best_score:
            best_score = sc
            best_metrics = m
            best_params = dict(p)
        if (i + 1) % 16 == 0:
            print(f"  {i+1}/{len(param_grid)}...")

    if best_params is None:
        print("No valid run.")
        return 1

    # Stage 2: local search around best (finer steps)
    print("  Local search around best...")
    b = best_params
    ms_vals = [max(0.50, b["min_signal_strength"] - 0.01), b["min_signal_strength"], min(0.75, b["min_signal_strength"] + 0.01)]
    md_vals = [max(300, b["min_delta"] - 12), b["min_delta"], min(450, b["min_delta"] + 12)]
    r1_vals = [max(0.50, b["rr_first"] - 0.02), b["rr_first"], min(0.80, b["rr_first"] + 0.02)]
    r2_vals = [max(1.10, b["rr_second"] - 0.04), b["rr_second"], min(1.60, b["rr_second"] + 0.04)]
    mdm_vals = [max(1.05, b["min_delta_multiplier"] - 0.02), b["min_delta_multiplier"], min(1.35, b["min_delta_multiplier"] + 0.02)]
    bt_vals = sorted(set([max(24, b["big_trade_threshold"] - 1), b["big_trade_threshold"], min(31, b["big_trade_threshold"] + 1)]))
    risk_vals = [max(0.005, b["risk_pct"] - 0.0005), b["risk_pct"], min(0.012, b["risk_pct"] + 0.0005)]
    atr_vals = [max(1.2, b["atr_stop_multiplier"] - 0.06), b["atr_stop_multiplier"], min(1.8, b["atr_stop_multiplier"] + 0.06)]
    dd_vals = sorted(set([0.015, 0.02, 0.025, 0.03, b.get("max_daily_drawdown_pct", 0.03)]))
    bte_vals = sorted(set([2, 3, b.get("big_trade_edge", 2)]))
    local_grid = [
        {"min_signal_strength": ms, "min_delta": md, "rr_first": r1, "rr_second": r2,
         "min_delta_multiplier": mdm, "big_trade_edge": bte, "big_trade_threshold": bt,
         "risk_pct": risk, "atr_stop_multiplier": atr, "max_daily_drawdown_pct": dd_cap}
        for ms in ms_vals
        for md in md_vals
        for r1 in r1_vals
        for r2 in r2_vals
        for mdm in mdm_vals
        for bt in bt_vals
        for risk in risk_vals
        for atr in atr_vals
        for dd_cap in dd_vals
        for bte in bte_vals
    ]
    # Dedupe and sample (local grid can be large)
    seen = set()
    local_list = []
    for p in local_grid:
        key = tuple(sorted((k, round(v, 6) if isinstance(v, float) else v) for k, v in p.items()))
        if key not in seen:
            seen.add(key)
            local_list.append(p)
    local_size = 24 if args.quick else 36
    local_list = random.sample(local_list, min(local_size, len(local_list)))
    for p in local_list:
        res = run_backtest(
            df,
            initial_balance=INITIAL_BALANCE,
            risk_pct=p["risk_pct"],
            big_trade_threshold=p["big_trade_threshold"],
            min_delta=p["min_delta"],
            min_signal_strength=p["min_signal_strength"],
            rr_first=p["rr_first"],
            rr_second=p["rr_second"],
            min_delta_multiplier=p["min_delta_multiplier"],
            big_trade_edge=p["big_trade_edge"],
            atr_stop_multiplier=p["atr_stop_multiplier"],
            max_daily_drawdown_pct=p.get("max_daily_drawdown_pct", 0.03),
            tick_value=tick_val,
        )
        m = res.to_metrics()
        sc = score(m["win_rate"], m["profit_factor"], m["max_drawdown_pct"], m["total_trades"], m["total_pnl"])
        if sc > best_score:
            best_score = sc
            best_metrics = m
            best_params = dict(p)
    print(f"  Local search done. Best score: {best_score:.2f}")

    print("\n--- Best on real 1m (win rate, profit factor, max drawdown) ---")
    print(f"  Win Rate:       {best_metrics['win_rate']:.1f}%")
    print(f"  Profit Factor:  {best_metrics['profit_factor']:.2f}")
    print(f"  Max Drawdown:   {best_metrics['max_drawdown_pct']:.1f}%")
    print(f"  Total Trades:   {best_metrics['total_trades']}")
    print(f"  Total P/L:     ${best_metrics['total_pnl']:,.2f}")
    print(f"  Params: {best_params}")
    out_name = "best_params_mnq_1m.json" if "mnq" in str(data_path).lower() else "best_params_1m.json"
    out = ROOT / "data" / out_name
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump({"metrics": best_metrics, "params": best_params, "tick_value": tick_val}, f, indent=2)
    print(f"\nSaved to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
