# Telegram Signals Bot

The app sends **trading signals to Telegram** only (no web dashboard).

## Setup

1. **Create a Telegram bot**  
   - Open Telegram, search for `@BotFather`.  
   - Send `/newbot`, follow the steps, copy the **bot token**.

2. **Get your chat ID**  
   - Search for `@userinfobot` in Telegram, start it, send any message.  
   - It will reply with your **chat ID** (e.g. `123456789`).

3. **Configure**  
   In `config.yaml` under `telegram:` set (or use env vars):

   ```yaml
   telegram:
     bot_token: "123456:ABC-DEF..."   # or ${TELEGRAM_BOT_TOKEN}
     chat_id: "123456789"             # or ${TELEGRAM_CHAT_ID}
     data_source: "binance"           # "yahoo" (MNQ/NQ, approx delta) or "binance" (real buy/sell, free)
     symbol: "MNQ=F"                  # used when data_source=yahoo
     binance_symbol: "BTCUSDT"        # used when data_source=binance (no API key needed)
     interval_seconds: 60
     use_ml_filter: false
     use_regime_filter: true
   ```

   Or in PowerShell:

   ```powershell
   $env:TELEGRAM_BOT_TOKEN = "your_bot_token"
   $env:TELEGRAM_CHAT_ID = "your_chat_id"
   ```

## Run

```powershell
cd d:\orderflow\fabio_bot
python telegram_bot.py
```

Or:

```powershell
.\start_telegram_bot.ps1
```

The bot fetches 1m bars and runs the order-flow strategy.

### Data source alternatives (Nasdaq-100)

This is a **Nasdaq-100 signal app**. Use Yahoo or Alpaca for Nasdaq-100; Binance is optional (crypto only).

| Source   | What you get              | Real order flow? | Cost / signup        |
|---------|---------------------------|------------------|------------------------|
| **yahoo** | MNQ/NQ (Nasdaq-100 futures)| No (approximated)| Free, no signup       |
| **alpaca** | QQQ (Nasdaq-100 ETF)      | Best-effort (trades API) | Free paper account + keys |
| **binance** | Crypto only (not Nasdaq-100) | Yes           | Free, no API key      |

- **yahoo** – **Recommended for Nasdaq-100.** Micro E-mini NASDAQ 100 (MNQ). Set `data_source: "yahoo"`, `symbol: "MNQ=F"`. No signup; volume is approximated.
- **alpaca** – **QQQ** (same index as MNQ). Free at [alpaca.markets](https://alpaca.markets). Set `data_source: "alpaca"`, `alpaca_symbol: "QQQ"`, and Alpaca API keys. Free tier ~50 bars.
- **binance** – Crypto only (e.g. BTCUSDT). Use only if you want crypto signals instead of Nasdaq-100.

For **real MNQ futures** order flow you need a CME/data vendor; the bot uses free Yahoo/Alpaca for Nasdaq-100.

## Commands (in Telegram)

| Command    | Description |
|-----------|-------------|
| `/start`  | Welcome and command list |
| `/status` | Last cycle: bars, signal, strength, reason, data source |
| `/strategy` | Backtest metrics: win rate, profit factor, max drawdown, trades, PnL |
| `/params` | Strategy parameters (min_strength, min_delta, R:R, etc.) from best_params_mnq_1m.json |
| `/settings` | Bot config: symbol, interval, ML filter, regime filter |
| `/help`   | List all commands |

## Optional: ML filter

- Set `use_ml_filter: true` in `telegram` config when you have a trained model at `data/ml_signal_model.pkl`.  
- To train a model, use backtest trade outcomes and scikit-learn (see `fabio_bot/ml_filter.py`).  
- Without a model, the ML filter is neutral (signals are not blocked by ML).

## Order Flow API (Nasdaq-100, free real-time bars)

When you run the main API server (`uvicorn api_server:app --host 0.0.0.0 --port 8000`), you get **your own** order-flow API for **Nasdaq-100** (MNQ/QQQ) with free sources.

| Endpoint | Description |
|----------|-------------|
| `GET /api/orderflow/sources` | List sources (Yahoo MNQ/NQ, Alpaca QQQ; Binance is crypto-only). |
| `GET /api/orderflow/bars?source=&symbol=&limit=200` | Real-time 1m bars: open, high, low, close, volume, buy_volume, sell_volume. |

**Nasdaq-100 examples:**

- One-click (uses your config):  
  `GET /api/orderflow/bars?market=nasdaq100&limit=200`
- Yahoo (MNQ futures):  
  `GET /api/orderflow/bars?source=yahoo&symbol=MNQ=F&limit=100`
- Alpaca (QQQ ETF):  
  `GET /api/orderflow/bars?source=alpaca&symbol=QQQ&limit=100`  
  (Uses `alpaca_key_id` / `alpaca_secret_key` from `config.yaml` if set.)

Default when you omit params: **Yahoo + MNQ=F** (Nasdaq-100). Binance is available only if you explicitly set `source=binance` (crypto, not Nasdaq-100).
