"""
Tune MNQ for highest achievable win rate with good PF and minimum drawdown.
Uses session (RTH) + trend filters when enabled. Balanced strictness.
"""
import json
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

MIN_TRADES = 12
# US RTH 9:30-16:00 ET: 570-960 min from midnight (1m bars, 1440/day)
SESSION_1440, SESSION_START, SESSION_END = 1440, 570, 960

# Base param sets; we'll combine with filter options
trials = [
    # Tier 1: 0.62-0.66 strength, 420-470 delta, fast rr, tight DD
    {"min_strength": 0.63, "min_delta": 430, "min_delta_mult": 1.28, "rr1": 0.50, "rr2": 1.08, "risk": 0.006, "atr": 1.52, "max_dd": 0.016, "big": 29},
    {"min_strength": 0.64, "min_delta": 445, "min_delta_mult": 1.30, "rr1": 0.49, "rr2": 1.06, "risk": 0.0055, "atr": 1.54, "max_dd": 0.015, "big": 30},
    {"min_strength": 0.62, "min_delta": 420, "min_delta_mult": 1.26, "rr1": 0.51, "rr2": 1.10, "risk": 0.006, "atr": 1.50, "max_dd": 0.017, "big": 28},
    {"min_strength": 0.65, "min_delta": 460, "min_delta_mult": 1.32, "rr1": 0.48, "rr2": 1.04, "risk": 0.005, "atr": 1.56, "max_dd": 0.014, "big": 31},
    {"min_strength": 0.63, "min_delta": 438, "min_delta_mult": 1.28, "rr1": 0.50, "rr2": 1.08, "risk": 0.0055, "atr": 1.53, "max_dd": 0.015, "big": 29},
    {"min_strength": 0.64, "min_delta": 450, "min_delta_mult": 1.30, "rr1": 0.49, "rr2": 1.06, "risk": 0.0055, "atr": 1.55, "max_dd": 0.014, "big": 30},
    {"min_strength": 0.62, "min_delta": 425, "min_delta_mult": 1.26, "rr1": 0.51, "rr2": 1.10, "risk": 0.006, "atr": 1.51, "max_dd": 0.016, "big": 28},
    {"min_strength": 0.66, "min_delta": 470, "min_delta_mult": 1.34, "rr1": 0.47, "rr2": 1.02, "risk": 0.005, "atr": 1.58, "max_dd": 0.013, "big": 31},
    {"min_strength": 0.63, "min_delta": 442, "min_delta_mult": 1.29, "rr1": 0.49, "rr2": 1.07, "risk": 0.0055, "atr": 1.53, "max_dd": 0.015, "big": 29},
    {"min_strength": 0.61, "min_delta": 412, "min_delta_mult": 1.24, "rr1": 0.52, "rr2": 1.12, "risk": 0.006, "atr": 1.49, "max_dd": 0.017, "big": 28},
    # Tier 2: Slightly stricter for more WR, same fast targets
    {"min_strength": 0.64, "min_delta": 448, "min_delta_mult": 1.30, "rr1": 0.48, "rr2": 1.04, "risk": 0.005, "atr": 1.55, "max_dd": 0.014, "big": 30},
    {"min_strength": 0.65, "min_delta": 455, "min_delta_mult": 1.32, "rr1": 0.48, "rr2": 1.04, "risk": 0.005, "atr": 1.56, "max_dd": 0.013, "big": 30},
    {"min_strength": 0.62, "min_delta": 418, "min_delta_mult": 1.25, "rr1": 0.51, "rr2": 1.10, "risk": 0.006, "atr": 1.50, "max_dd": 0.016, "big": 28},
    {"min_strength": 0.60, "min_delta": 400, "min_delta_mult": 1.22, "rr1": 0.52, "rr2": 1.12, "risk": 0.0065, "atr": 1.46, "max_dd": 0.018, "big": 27},
    {"min_strength": 0.63, "min_delta": 435, "min_delta_mult": 1.28, "rr1": 0.50, "rr2": 1.08, "risk": 0.0055, "atr": 1.52, "max_dd": 0.015, "big": 29},
    # Tier 3: Fastest targets (lock profit very fast) with moderate strictness
    {"min_strength": 0.61, "min_delta": 408, "min_delta_mult": 1.23, "rr1": 0.50, "rr2": 1.08, "risk": 0.006, "atr": 1.48, "max_dd": 0.016, "big": 28},
    {"min_strength": 0.62, "min_delta": 422, "min_delta_mult": 1.26, "rr1": 0.50, "rr2": 1.08, "risk": 0.006, "atr": 1.51, "max_dd": 0.015, "big": 28},
    {"min_strength": 0.64, "min_delta": 443, "min_delta_mult": 1.30, "rr1": 0.48, "rr2": 1.04, "risk": 0.0055, "atr": 1.54, "max_dd": 0.014, "big": 30},
    {"min_strength": 0.59, "min_delta": 392, "min_delta_mult": 1.20, "rr1": 0.53, "rr2": 1.14, "risk": 0.007, "atr": 1.44, "max_dd": 0.018, "big": 26},
    {"min_strength": 0.60, "min_delta": 402, "min_delta_mult": 1.22, "rr1": 0.52, "rr2": 1.12, "risk": 0.0065, "atr": 1.46, "max_dd": 0.017, "big": 27},
    # big_trade_edge=3 (stricter order flow)
    {"min_strength": 0.61, "min_delta": 415, "min_delta_mult": 1.24, "rr1": 0.51, "rr2": 1.10, "risk": 0.006, "atr": 1.49, "max_dd": 0.016, "big": 29, "bte": 3},
    {"min_strength": 0.62, "min_delta": 428, "min_delta_mult": 1.26, "rr1": 0.50, "rr2": 1.08, "risk": 0.0055, "atr": 1.52, "max_dd": 0.015, "big": 30, "bte": 3},
    {"min_strength": 0.60, "min_delta": 405, "min_delta_mult": 1.22, "rr1": 0.52, "rr2": 1.11, "risk": 0.0065, "atr": 1.47, "max_dd": 0.016, "big": 28, "bte": 3},
]

# Filter options: (session_on, trend_ma_bars). Add more trend lengths to push WR.
filter_options = [
    (False, 0),
    (True, 0),
    (True, 5),
    (True, 8),
    (True, 6),
    (True, 10),
    (False, 5),
    (False, 8),
    (False, 6),
]

# Extra trials: very fast targets (lock profit ASAP) + slightly stricter to push WR 59-62%
extra_trials = [
    {"min_strength": 0.61, "min_delta": 410, "min_delta_mult": 1.24, "rr1": 0.46, "rr2": 1.00, "risk": 0.0055, "atr": 1.48, "max_dd": 0.015, "big": 28},
    {"min_strength": 0.62, "min_delta": 422, "min_delta_mult": 1.26, "rr1": 0.45, "rr2": 0.98, "risk": 0.005, "atr": 1.51, "max_dd": 0.014, "big": 29},
    {"min_strength": 0.60, "min_delta": 398, "min_delta_mult": 1.21, "rr1": 0.48, "rr2": 1.04, "risk": 0.006, "atr": 1.46, "max_dd": 0.016, "big": 27},
    {"min_strength": 0.63, "min_delta": 435, "min_delta_mult": 1.28, "rr1": 0.44, "rr2": 0.96, "risk": 0.005, "atr": 1.53, "max_dd": 0.014, "big": 29},
    {"min_strength": 0.61, "min_delta": 415, "min_delta_mult": 1.24, "rr1": 0.47, "rr2": 1.02, "risk": 0.0055, "atr": 1.49, "max_dd": 0.015, "big": 28},
    {"min_strength": 0.62, "min_delta": 428, "min_delta_mult": 1.27, "rr1": 0.45, "rr2": 0.98, "risk": 0.005, "atr": 1.52, "max_dd": 0.014, "big": 29},
    {"min_strength": 0.60, "min_delta": 405, "min_delta_mult": 1.22, "rr1": 0.49, "rr2": 1.06, "risk": 0.006, "atr": 1.47, "max_dd": 0.016, "big": 27},
    {"min_strength": 0.59, "min_delta": 388, "min_delta_mult": 1.19, "rr1": 0.50, "rr2": 1.08, "risk": 0.0065, "atr": 1.44, "max_dd": 0.017, "big": 26},
]
trials = trials + extra_trials

best_score = -1e9
best_metrics = None
best_p = None
best_filters = (False, 0)

for session_on, trend_ma in filter_options:
    for p in trials:
        bte = p.get("bte", 2)
        kw = dict(
            initial_balance=50_000.0,
            risk_pct=p["risk"],
            big_trade_threshold=p["big"],
            min_delta=p["min_delta"],
            min_signal_strength=p["min_strength"],
            rr_first=p["rr1"],
            rr_second=p["rr2"],
            min_delta_multiplier=p["min_delta_mult"],
            big_trade_edge=bte,
            atr_stop_multiplier=p["atr"],
            max_daily_drawdown_pct=p["max_dd"],
            tick_value=1.0,
        )
        if session_on:
            kw["session_bars_per_day"] = SESSION_1440
            kw["session_start_bar"] = SESSION_START
            kw["session_end_bar"] = SESSION_END
        if trend_ma > 0:
            kw["trend_ma_bars"] = trend_ma
        res = run_backtest(df, **kw)
        m = res.to_metrics()
        if m["total_trades"] < MIN_TRADES:
            continue
        if m["total_pnl"] < 0:
            continue  # Only consider profitable configs
        # Score: heavy weight on WR, then PF, then low DD
        score = m["win_rate"] * 1.4 + min(m["profit_factor"], 3) * 12 + (2.0 - m["max_drawdown_pct"]) * 6
        if m["win_rate"] >= 58:
            score += 10
        if m["win_rate"] >= 59:
            score += 14
        if m["win_rate"] >= 60:
            score += 18
        if m["win_rate"] >= 62:
            score += 22
        if m["max_drawdown_pct"] <= 1.5:
            score += 10
        if m["profit_factor"] >= 1.08:
            score += 5
        if score > best_score:
            best_score = score
            best_metrics = m
            best_p = p
            best_filters = (session_on, trend_ma)

if best_metrics is None:
    print("No profitable config with enough trades. Keeping previous best.")
    sys.exit(0)

print("\n--- Best MNQ 1m (high WR + good PF + min DD) ---")
print(f"  Win Rate:       {best_metrics['win_rate']:.1f}%")
print(f"  Profit Factor:  {best_metrics['profit_factor']:.2f}")
print(f"  Max Drawdown:   {best_metrics['max_drawdown_pct']:.1f}%")
print(f"  Total Trades:   {best_metrics['total_trades']}")
print(f"  Total P/L:     ${best_metrics['total_pnl']:,.2f}")
print("  Filters: session(RTH)={}, trend_ma={}".format(best_filters[0], best_filters[1]))
print("  Best params:", best_p)

out = ROOT / "data" / "best_params_mnq_1m.json"
with open(out, "w") as f:
    params = {
        "min_signal_strength": best_p["min_strength"],
        "min_delta": best_p["min_delta"],
        "rr_first": best_p["rr1"],
        "rr_second": best_p["rr2"],
        "min_delta_multiplier": best_p["min_delta_mult"],
        "big_trade_edge": best_p.get("bte", 2),
        "big_trade_threshold": best_p["big"],
        "risk_pct": best_p["risk"],
        "atr_stop_multiplier": best_p["atr"],
        "max_daily_drawdown_pct": best_p["max_dd"],
    }
    if best_filters[0]:
        params["session_bars_per_day"] = SESSION_1440
        params["session_start_bar"] = SESSION_START
        params["session_end_bar"] = SESSION_END
    if best_filters[1] > 0:
        params["trend_ma_bars"] = best_filters[1]
    json.dump({"metrics": best_metrics, "params": params, "tick_value": 1.0}, f, indent=2)
print(f"Saved to {out}")
