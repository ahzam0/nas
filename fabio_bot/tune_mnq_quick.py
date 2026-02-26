"""Quick parameter sweep on MNQ 1m CSV. Goal: higher WR, higher PF, lower DD."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from backtest import run_backtest
import pandas as pd

DATA = ROOT / "data" / "mnq_1m.csv"
if not DATA.exists():
    print("Missing data/mnq_1m.csv")
    sys.exit(1)

df = pd.read_csv(DATA)
for col in ["open", "high", "low", "close"]:
    if col not in df.columns:
        print(f"Missing {col}")
        sys.exit(1)
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

# Final: Combine best — fast targets (57.8% WR) + moderate filters for PF/DD
trials = [
    {"min_strength": 0.60, "min_delta": 400, "min_delta_mult": 1.22, "rr1": 0.52, "rr2": 1.12, "risk": 0.007, "atr": 1.46, "max_dd": 0.018, "big": 27},
    {"min_strength": 0.60, "min_delta": 398, "min_delta_mult": 1.21, "rr1": 0.52, "rr2": 1.11, "risk": 0.0065, "atr": 1.47, "max_dd": 0.017, "big": 27},
    {"min_strength": 0.59, "min_delta": 392, "min_delta_mult": 1.20, "rr1": 0.53, "rr2": 1.13, "risk": 0.007, "atr": 1.44, "max_dd": 0.018, "big": 26},
    {"min_strength": 0.61, "min_delta": 408, "min_delta_mult": 1.23, "rr1": 0.51, "rr2": 1.10, "risk": 0.0065, "atr": 1.48, "max_dd": 0.016, "big": 28},
    {"min_strength": 0.60, "min_delta": 402, "min_delta_mult": 1.22, "rr1": 0.52, "rr2": 1.12, "risk": 0.0065, "atr": 1.46, "max_dd": 0.017, "big": 27},
]

best = None
best_score = -1e9
best_metrics = None
best_p = None

for p in trials:
    res = run_backtest(
        df,
        initial_balance=50_000.0,
        risk_pct=p["risk"],
        big_trade_threshold=p["big"],
        min_delta=p["min_delta"],
        min_signal_strength=p["min_strength"],
        rr_first=p["rr1"],
        rr_second=p["rr2"],
        min_delta_multiplier=p["min_delta_mult"],
        big_trade_edge=2,
        atr_stop_multiplier=p["atr"],
        max_daily_drawdown_pct=p["max_dd"],
        tick_value=1.0,
    )
    m = res.to_metrics()
    if m["total_trades"] < 15:
        continue
    # Score: heavy weight on WR and PF; bonus for low DD
    score = m["win_rate"] * 0.8 + min(m["profit_factor"], 4) * 18 + max(0, 2.5 - m["max_drawdown_pct"]) * 12
    if m["total_pnl"] < 0:
        score -= 50
    if score > best_score:
        best_score = score
        best = res
        best_metrics = m
        best_p = p

if best_metrics is None:
    print("No valid run with enough trades.")
    sys.exit(1)

print("\n--- Best MNQ 1m (quick sweep) ---")
print(f"  Win Rate:       {best_metrics['win_rate']:.1f}%")
print(f"  Profit Factor:  {best_metrics['profit_factor']:.2f}")
print(f"  Max Drawdown:   {best_metrics['max_drawdown_pct']:.1f}%")
print(f"  Total Trades:   {best_metrics['total_trades']}")
print(f"  Total P/L:     ${best_metrics['total_pnl']:,.2f}")
print("  Best params:", best_p)

# Write so backtest can use: overwrite scalp defaults when running with --data data/mnq_1m.csv
import json
out = ROOT / "data" / "best_params_mnq_1m.json"
with open(out, "w") as f:
    params = {
        "min_signal_strength": best_p["min_strength"],
        "min_delta": best_p["min_delta"],
        "rr_first": best_p["rr1"],
        "rr_second": best_p["rr2"],
        "min_delta_multiplier": best_p["min_delta_mult"],
        "big_trade_edge": 2,
        "big_trade_threshold": best_p["big"],
        "risk_pct": best_p["risk"],
        "atr_stop_multiplier": best_p["atr"],
        "max_daily_drawdown_pct": best_p["max_dd"],
    }
    json.dump({"metrics": best_metrics, "params": params, "tick_value": 1.0}, f, indent=2)
print(f"Saved to {out}")
