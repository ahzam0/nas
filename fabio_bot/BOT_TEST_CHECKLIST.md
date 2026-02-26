# Nasdaq-100 Signal App – A-to-Z Test Checklist

Use this for full automated test runs and manual testing (Telegram + API).

---

## 0. Full A-to-Z automated run (one command)

Run from `fabio_bot` directory:

```powershell
cd d:\orderflow\fabio_bot
& "$env:LOCALAPPDATA\Microsoft\WindowsApps\python3.12.exe" -m pytest tests/ -v -p no:anchorpy --tb=short
```

**Expected:** All tests pass (36+). This is the main A-to-Z automated gate.

---

## 1. Automated tests by area (no Telegram / no network)

### 1.1 Order Flow API (`tests/test_orderflow_api.py`)

- `GET /api/orderflow/sources` – Nasdaq-100 first, yahoo/alpaca/binance list
- `GET /api/orderflow/bars` – default Yahoo MNQ, `market=nasdaq100` uses config, empty fetch returns 200, explicit `source=yahoo&symbol=NQ=F`

Run: `pytest tests/test_orderflow_api.py -v -p no:anchorpy`

### 1.2 Fetch order-flow bars (`tests/test_fetch_orderflow.py`)

- `fetch_orderflow_bars(source=yahoo|binance|alpaca)` returns (df, symbol) with columns: open, high, low, close, volume, buy_volume, sell_volume, bar_idx
- Default source/symbol is yahoo / MNQ=F

Run: `pytest tests/test_fetch_orderflow.py -v -p no:anchorpy`

### 1.3 Signal generation (`tests/test_signal_generator.py` + `tests/test_signal_generation_e2e.py`)

- **Signal generator:** SignalResult fields, generate() returns valid result, strength filter, market state, no setup → NONE
- **E2E:** `get_latest_signal` on synthetic bars returns (signal, strength, price, features) with sl_price, tp1_price, tp2_price, reason
- **Params:** get_latest_signal with best_params_mnq_1m.json (if present)
- **Min strength:** pipeline respects min_signal_strength; no crash for 0.0, 0.5, 0.65
- **Real CSV:** if data/mnq_1m.csv exists, run get_latest_signal on last 500 bars; validate structure

Run: `pytest tests/test_signal_generator.py tests/test_signal_generation_e2e.py -v -p no:anchorpy`

### 1.4 Telegram bot (`tests/test_telegram_bot.py`)

- Inline menu structure (Status, Strategy, Params, Settings, Help)
- Format functions: /start, /help, /status, /strategy, /params, /settings
- Trailing logic: LONG/SHORT TP2 hit, TP1 → move SL to BE, SL hit; inactive/empty trade no-op
- `get_latest_signal` returns (signal, strength, price, features) with sl_price, tp1_price, tp2_price
- Signal message contains Entry, SL, TP1, TP2
- Config/params loaders return dicts

Run: `pytest tests/test_telegram_bot.py -v -p no:anchorpy`

### 1.5 Other tests

- `tests/test_risk_manager.py`, `tests/test_order_flow_analyzer.py` – run with full suite above.

---

## 2. Manual tests in Telegram

### 2.1 Startup
- [ ] Run: `python telegram_bot.py` (or `.\start_telegram_bot.ps1`)
- [ ] Console shows: `Telegram signal bot started. Symbol=..., interval=60s, ...`
- [ ] Console shows: `Commands: /start /status /strategy /params /settings /help`
- [ ] No crash; cycle lines appear every ~60s: `Cycle: N bars, signal=... strength=... reason=...`

### 2.2 Commands (type in Telegram)
- [ ] **/start** – Welcome + command list + inline buttons (Status, Strategy, Params, Settings, Help)
- [ ] **/status** – Shows symbol, data source, last cycle bars, signal, strength, reason
- [ ] **/strategy** – Shows win rate, profit factor, max DD, trades, PnL (or “No backtest metrics” if file missing)
- [ ] **/params** – Shows strategy params (min_strength, min_delta, etc.) or “No saved params”
- [ ] **/settings** – Shows symbol, interval, period, interval_seconds, ML filter, regime filter, model path
- [ ] **/help** – Lists all commands + same inline buttons as /start
- [ ] Unknown text (e.g. `hello`) – Reply: “Use /help for commands.” + menu buttons

### 2.3 Inline buttons (tap, don’t type)
- [ ] Tap **Status** – Same content as /status
- [ ] Tap **Strategy** – Same as /strategy
- [ ] Tap **Params** – Same as /params
- [ ] Tap **Settings** – Same as /settings
- [ ] Tap **Help** – Same as /help
- [ ] Each tap gets exactly one reply (no duplicates after fix)

### 2.4 Signal message (when strategy fires)
If a LONG/SHORT signal is sent (rare on Yahoo data):
- [ ] Message has: **Signal LONG** or **Signal SHORT**, symbol (e.g. MNQ)
- [ ] **Entry:** price
- [ ] **SL:** price (below entry for LONG, above for SHORT)
- [ ] **TP1:** price
- [ ] **TP2:** price
- [ ] Strength and R:R at the bottom

### 2.5 Trailing notifications (when trade is “open”)
After a signal, the bot tracks one open trade. On later bars:
- [ ] **TP1 hit** – Message: “TP1 hit … SL moved to breakeven at &lt;entry&gt;”
- [ ] **TP2 hit** – Message: “TP2 hit … Entry / Exit / Result: +X.XX”; trade closed
- [ ] **SL hit** – Message: “SL hit … Entry / Exit / Result”; trade closed

(If no signal ever fires, these won’t appear; that’s expected on Yahoo-only data.)

### 2.6 Robustness
- [ ] Stop bot with Ctrl+C – Log shows “Stopped”, process exits
- [ ] Restart bot – No duplicate handling of old updates (offset works)
- [ ] Network glitch / fetch timeout – Console shows “Fetch timed out” or “Fetch error”, bot keeps running and retries next cycle

---

## 3. Manual tests – Order Flow API (optional)

With the API server running (`uvicorn api_server:app --host 0.0.0.0 --port 8000`):

- [ ] `GET http://localhost:8000/api/orderflow/sources` – JSON with nasdaq100, sources, nasdaq100_one_click
- [ ] `GET http://localhost:8000/api/orderflow/bars?market=nasdaq100&limit=50` – JSON with bars (open, high, low, close, buy_volume, sell_volume), count, updated_utc
- [ ] `GET http://localhost:8000/api/orderflow/bars?source=yahoo&symbol=MNQ=F&limit=10` – same shape, source=yahoo, symbol_used=MNQ=F or NQ=F

---

## 4. One-line full automated run

```powershell
cd d:\orderflow\fabio_bot; & "$env:LOCALAPPDATA\Microsoft\WindowsApps\python3.12.exe" -m pytest tests/ -v -p no:anchorpy -q
```

**Pass = automated A-to-Z (Order Flow API + fetch + Telegram bot + backtest pipeline) is OK.**  
Then use Section 2 in Telegram for full A-to-Z with real bot and UI.
