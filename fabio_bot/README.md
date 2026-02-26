# Fabio Bot – Order Flow Scalping (Fabio Valentini / Fabervaale Style)

Production-ready trading bot that replicates **Fabio Valentini’s (Fabervaale)** order flow–based scalping approach for NASDAQ futures (NQ/MNQ). It runs as a **Bookmap Python add-on** for order flow analysis (depth, trades, MBO) and executes via **Tradovate** (through Bookmap’s connector or optional REST API).

## Strategy Overview

- **Auction Market Theory (AMT)** and volume profile: POC, VAH/VAL, HVN, LVN.
- **Order flow**: Cumulative Volume Delta (CVD), big-trade filter (e.g. ≥25–30 contracts), absorption and exhaustion.
- **Context**: Balanced (mean-reversion at HVN/POC) vs unbalanced (trend continuation through LVN).
- **Filters**: FVG-style retests, liquidity sweeps, session hours (e.g. 9:30–16:00 ET).
- **Targets**: Short scalps (e.g. 10–60 seconds), 1:1 and 1:2 R:R, trailing to breakeven.
- **Risk**: ~0.5–1% per trade, max daily drawdown 3–5%, consecutive-loss halt.

## Repository Layout

```
fabio_bot/
├── main.py                    # Bookmap add-on entry (run from Bookmap)
├── backtest.py                # Standalone backtester (no Bookmap)
├── config.yaml                # Strategy and API config (use env vars for secrets)
├── requirements.txt
├── fabio_bot/
│   ├── __init__.py
│   ├── config_loader.py       # YAML + env substitution
│   ├── order_flow_analyzer.py # CVD, big trades, absorption, volume profile
│   ├── signal_generator.py   # Long/short rules (Fabio-style)
│   ├── risk_manager.py       # Sizing, drawdown, session, consecutive loss
│   └── execution_engine.py   # Bookmap orders + optional Tradovate REST
├── tests/
│   ├── test_order_flow_analyzer.py
│   ├── test_signal_generator.py
│   └── test_risk_manager.py
└── README.md
```

## Requirements

- **Python 3.10+**
- **Bookmap** (latest stable) when running the add-on in Bookmap
- For standalone/backtest: `numpy`, `pandas`, `pyyaml` (see `requirements.txt`)

Bookmap’s Python API is provided by Bookmap at runtime; no separate `pip install bookmap`.

## Setup

### 1. Clone / copy project

```bash
cd d:\orderflow\fabio_bot
```

### 2. Install dependencies (for backtest and optional standalone)

```bash
pip install -r requirements.txt
```

### 3. Config and API keys

- Copy or edit `config.yaml`.
- **Secrets**: Prefer environment variables instead of putting keys in the file:
  - `TRADOVATE_CID` – API key (client id)
  - `TRADOVATE_SEC` – API secret
  - `TRADOVATE_USER` – username
  - `TRADOVATE_PASS` – password

Example (Windows PowerShell):

```powershell
$env:TRADOVATE_CID = "your_client_id"
$env:TRADOVATE_SEC = "your_secret"
$env:TRADOVATE_USER = "your_username"
$env:TRADOVATE_PASS = "your_password"
```

### 4. Bookmap add-on and Tradovate (live/simulation)

- In Bookmap: **Settings → Manage plugins → Bookmap Add-ons (L1)** (or **API Plugins**), add the Python script and select `main.py`.
- Connect Tradovate in Bookmap: **Connections → Configure → Tradovate** (username, password, and API credentials from Tradovate).
- Enable the add-on for the instrument (e.g. NQ or MNQ). The bot will subscribe to depth/trades and send orders through Bookmap to your Tradovate account.
- **To go live:** see **[LIVE_SETUP.md](LIVE_SETUP.md)** (Tradovate). If Tradovate charges for API, use a **free option** (e.g. Interactive Brokers) – see **[FREE_API_OPTIONS.md](FREE_API_OPTIONS.md)**.

### 5. Modes in config

- `mode: simulation` – Paper/sim (recommended first).
- `mode: live` – Live trading (use with caution; start with MNQ and small size).
- Backtest is run separately via `backtest.py`, not via Bookmap.

## Running

### Inside Bookmap (live/simulation)

1. Open Bookmap and connect data + Tradovate.
2. Load the add-on (point to `main.py`).
3. Enable the add-on for NQ (or MNQ). It will:
   - Subscribe to depth and trades (and MBO if supported).
   - Every 15 seconds (configurable) evaluate order flow and volume profile.
   - Generate long/short signals and place bracket orders when risk checks pass.

### Backtest (no Bookmap)

**Real market data (recommended for proper backtesting):**

```bash
# Download real NQ futures via Yahoo Finance and backtest (requires pip install yfinance)
python backtest.py --fetch-real --symbol "NQ=F" --interval 1h --period 60d --initial-balance 50000
# Daily bars, longer history:
python backtest.py --fetch-real --symbol "NQ=F" --interval 1d --period 2y --save-csv data/nq_1d.csv
```

If Yahoo returns no data (network/region), use your own CSV (export from Tradovate, IB, etc.):

```bash
python backtest.py --data path/to/your_nq_bars.csv --initial-balance 50000
```

**Synthetic or sample data:**

```bash
# Synthetic 8000 bars
python backtest.py --full

# Realistic NQ-style sample (in data/)
python backtest.py --data data/nq_realistic_sample.csv
```

CSV must have: `open`, `high`, `low`, `close`; optional `buy_volume`, `sell_volume`. See `data/README.md`.

Example output:

- Total P/L, win rate, profit factor, max drawdown, Sharpe ratio.

### Tests

```bash
pytest tests/ -v
```

## Order Flow Data and Approximations

- **In Bookmap**: The add-on uses Bookmap’s real-time depth, trades, and (if available) MBO. That gives proper CVD, big-trade detection, and volume-at-price for POC/HVN/LVN.
- **Tradovate feed**: If you use only Tradovate in Bookmap, you get the feed Tradovate provides (often L2 DOM + T&S; full MBO may require a premium data connection).
- **Backtest**: `backtest.py` approximates order flow by deriving buy/sell volume from bar data (e.g. synthetic or CSV). For more realistic backtests, use historical tick/T&S or footprint data (e.g. from CME, Bookmap export, or Sierra Chart) and feed bars/ticks that include aggressor side or delta.

**Premium options**: For full MBO and best order flow, connect Bookmap to **dxFeed** or **Rithmic** for data and keep Tradovate for execution (cross-trading supported in Bookmap).

## Risk and Compliance

- **Disclaimer**: Trading futures involves substantial risk. This bot is for educational and research use. Past backtest results do not guarantee future performance.
- **Recommendations**: Start in simulation; use micros (MNQ); enforce max daily loss and position limits; do not use martingale or high-risk sizing.

## High win rate and profit factor

Tuning for fewer, higher-quality trades: **min_signal_strength** (e.g. 0.65); **require_absorption** and **require_at_structure**; **big_trade_edge**; **min_delta_multiplier** (e.g. 1.3); **rr_first: 0.8** and **rr_second: 1.8**; **scale_out_pct: 0.6**. Backtest: `python backtest.py --min-strength 0.65 --rr-first 0.8 --rr-second 1.8`

## Parameters (config.yaml)

| Section     | Key                     | Description                          |
|------------|-------------------------|--------------------------------------|
| strategy   | symbol                  | NQ or MNQ                            |
| strategy   | big_trade_threshold     | Min contracts for “big trade” (25–50) |
| strategy   | risk_pct                | Max risk per trade (e.g. 0.01 = 1%)  |
| strategy   | session_start / end     | Session window (ET)                  |
| strategy   | min_delta               | Min CVD for signal                   |
| risk       | max_daily_drawdown_pct  | Pause bot at this drawdown           |
| risk       | max_consecutive_losses  | Halt after N losses                  |
| risk       | tick_value              | NQ = 5, MNQ = 1                      |
| targets    | rr_first / rr_second   | First and second target (R:R)        |

## Logs and Alerts

- Logs go to `logs/fabio_bot.log` (path configurable in `config.yaml`).
- Trades can be logged to CSV (see `logging.trade_log` in config).
- Email/SMS alerts can be wired via `smtplib` or Twilio using the provided config placeholders.

## Changelog

- **1.0.0**: Initial release: Bookmap add-on, CVD/big trades/absorption/volume profile, Fabio-style signals, risk management, Tradovate execution path, standalone backtester and tests.
