# Real market data for backtesting

## Option 1: Fetch automatically (when Yahoo Finance works)

```bash
python backtest.py --fetch-real --symbol "NQ=F" --interval 1h --period 60d
# or daily for longer history:
python backtest.py --fetch-real --symbol "NQ=F" --interval 1d --period 2y --save-csv data/nq_1d.csv
```

Requires: `pip install yfinance`. If you see `JSONDecodeError` or "No data returned", Yahoo may be blocking (try another network/VPN) or use Option 2.

## Option 2: Use your own CSV (real data from broker)

Export NQ/MNQ bars from your broker (Tradovate, IB, etc.) or a data vendor. CSV must have columns:

- **open**, **high**, **low**, **close** (required)
- **buy_volume**, **sell_volume** (optional; if missing, equal split is assumed)

Then run:

```bash
python backtest.py --data path/to/your_nq_bars.csv --initial-balance 50000
```

## 1-minute scalp only (max trades, order flow)

Strategy is **1m only**. 5m is disabled (was loss). For maximum trade frequency:

```bash
# Real 1m data (~7 days), scalp mode
python backtest.py --fetch-real --interval 1m --period 7d --scalp --initial-balance 50000
# Or use saved 1m CSV:
python backtest.py --data data/nq_1m_live.csv --scalp --initial-balance 50000
```

The backtest enforces **max daily drawdown** (4%) and **record_trade** so the risk manager pauses when drawdown is hit, improving win rate, profit factor, and capping max drawdown. For further tuning on your data, run `python optimize_1m.py` (uses `data/nq_1m_live.csv`).

In **Bookmap**, set `mode: scalp` in `config.yaml` to use 1m scan interval (60s) and scalp params (see `scalp:` section).

## Option 3: Realistic sample (included)

`nq_realistic_sample.csv` is a generated sample with NQ-like price range and volume structure for testing. It is not live market data.

```bash
python backtest.py --data data/nq_realistic_sample.csv
```
