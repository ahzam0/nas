"""Generate a realistic NQ-style bar CSV for backtest when live fetch is unavailable."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

def main():
    np.random.seed(123)
    n = 504  # ~2 years daily
    base = 19500.0
    pips = 0.25
    price = base
    bars = []
    for i in range(n):
        ret = np.random.randn() * 0.008 - 0.0002
        price = price * (1 + ret)
        price = max(15000, min(22000, price))
        open_p = price / (1 + ret)
        high = max(open_p, price) + np.random.rand() * 30
        low = min(open_p, price) - np.random.rand() * 30
        vol = max(5000, np.random.exponential(80000) + 20000)
        ratio = (price - open_p) / (high - low) if high != low else 0
        ratio = np.clip(ratio, -1, 1)
        buy_vol = vol * (0.5 + 0.5 * ratio)
        sell_vol = vol - buy_vol
        bars.append({
            "open": open_p, "high": high, "low": low, "close": price,
            "volume": vol, "buy_volume": max(1, buy_vol), "sell_volume": max(1, sell_vol),
        })
    df = pd.DataFrame(bars)
    out = ROOT / "data" / "nq_realistic_sample.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"Saved {len(df)} bars to {out}")

if __name__ == "__main__":
    main()
