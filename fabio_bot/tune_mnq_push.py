"""Quick push for higher WR: very fast targets + trend filter only."""
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from backtest import run_backtest
import pandas as pd

DATA = ROOT / "data" / "mnq_1m.csv"
df = pd.read_csv(DATA)
for col in ["open", "high", "low", "close"]:
    if col not in df.columns:
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

# Fine grid around current best (0.60, 402, 0.52/1.12) to try to reach 58%+
trials = []
for ms in [0.585, 0.59, 0.595, 0.60, 0.605, 0.61]:
    for md in [392, 398, 402, 408, 415]:
        for r1 in [0.50, 0.51, 0.52, 0.53]:
            for r2 in [1.08, 1.10, 1.12, 1.14]:
                trials.append({"min_strength": ms, "min_delta": md, "min_delta_mult": 1.22, "rr1": r1, "rr2": r2,
                              "risk": 0.0065, "atr": 1.46, "max_dd": 0.017, "big": 27})
# Cap at 60 to keep runtime ~3 min
trials = trials[:60]
filters = [(False, 0)]

best_score = -1e9
best_m = best_p = best_f = None

for (sess, trend) in filters:
    for p in trials:
        kw = dict(initial_balance=50_000.0, risk_pct=p["risk"], big_trade_threshold=p["big"], min_delta=p["min_delta"],
                  min_signal_strength=p["min_strength"], rr_first=p["rr1"], rr_second=p["rr2"],
                  min_delta_multiplier=p["min_delta_mult"], big_trade_edge=2, atr_stop_multiplier=p["atr"],
                  max_daily_drawdown_pct=p["max_dd"], tick_value=1.0)
        if sess:
            kw["session_bars_per_day"] = 1440
            kw["session_start_bar"] = 570
            kw["session_end_bar"] = 960
        if trend:
            kw["trend_ma_bars"] = trend
        res = run_backtest(df, **kw)
        m = res.to_metrics()
        if m["total_trades"] < 12 or m["total_pnl"] < 0:
            continue
        score = m["win_rate"] * 1.8 + min(m["profit_factor"], 3) * 12 + (2 - m["max_drawdown_pct"]) * 5
        if m["win_rate"] >= 58:
            score += 15
        if m["win_rate"] >= 58.5:
            score += 20
        if m["win_rate"] >= 59:
            score += 25
        if m["profit_factor"] >= 1.05:
            score += 5
        if score > best_score:
            best_score, best_m, best_p, best_f = score, m, p, (sess, trend)

if best_m is None:
    print("No better config found.")
    sys.exit(0)

print("--- Best (push) ---")
print(f"  Win Rate:   {best_m['win_rate']:.1f}%")
print(f"  Profit Factor: {best_m['profit_factor']:.2f}")
print(f"  Max DD:     {best_m['max_drawdown_pct']:.1f}%")
print(f"  Trades:     {best_m['total_trades']}  P/L: ${best_m['total_pnl']:,.0f}")
print(f"  Filters: session={best_f[0]}, trend_ma={best_f[1]}")
print("  Params:", best_p)

out = ROOT / "data" / "best_params_mnq_1m.json"
params = {"min_signal_strength": best_p["min_strength"], "min_delta": best_p["min_delta"], "rr_first": best_p["rr1"], "rr_second": best_p["rr2"],
         "min_delta_multiplier": best_p["min_delta_mult"], "big_trade_edge": 2, "big_trade_threshold": best_p["big"],
         "risk_pct": best_p["risk"], "atr_stop_multiplier": best_p["atr"], "max_daily_drawdown_pct": best_p["max_dd"]}
if best_f[0]:
    params["session_bars_per_day"] = 1440
    params["session_start_bar"] = 570
    params["session_end_bar"] = 960
if best_f[1]:
    params["trend_ma_bars"] = best_f[1]
with open(out, "w") as f:
    json.dump({"metrics": best_m, "params": params, "tick_value": 1.0}, f, indent=2)
print(f"Saved to {out}")
