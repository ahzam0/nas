# Connecting to Tradovate and Going Live

This guide explains how to connect the Fabio bot to your **Tradovate** account and run it live (or in simulation first).

**Tradovate charges for API?** Use a **free alternative** instead: see **[FREE_API_OPTIONS.md](FREE_API_OPTIONS.md)**. The recommended free option is **Interactive Brokers** (free TWS API) – connect Bookmap to IB instead of Tradovate and use the same add-on; no code changes.

---

## Two ways to run live

| Method | Data & execution | Best for |
|--------|-------------------|----------|
| **A. Bookmap + Tradovate** | Bookmap gets data and sends orders via its Tradovate connection | Full order flow (depth/trades) and one place to manage everything |
| **B. Tradovate API only** | Your own script uses Tradovate REST for orders (data from elsewhere or limited) | Custom setups without Bookmap; requires more code for data |

**Recommended:** Use **Method A** (Bookmap + Tradovate) so the bot gets real-time depth and trades and sends orders through Bookmap.

---

## Method A: Live with Bookmap + Tradovate

### 1. Get Tradovate API credentials

1. Log in at [tradovate.com](https://www.tradovate.com).
2. Go to **Account → API Access** (or **Settings → API**).
3. Create an API key (Client ID + Secret).  
   - For **paper/simulation**: use a **sim** account and demo API if available.  
   - For **live**: use your **live** account and live API credentials.
4. Note:
   - **Client ID** (cid)
   - **API Secret** (sec)
   - Your **username** and **password** (same as web login).

### 2. Install and set up Bookmap

1. Install [Bookmap](https://bookmap.com) (latest stable).
2. Open Bookmap and add the Fabio bot add-on:
   - **Settings → Manage plugins → Bookmap Add-ons (L1)** (or **API Plugins**).
   - Add a Python script and select:  
     `d:\orderflow\fabio_bot\main.py`
3. Ensure the `fabio_bot` folder is on the Python path Bookmap uses (usually the folder containing `main.py` and the `fabio_bot` package).

### 3. Connect Tradovate in Bookmap

1. In Bookmap: **Connections → Configure** (or **Data/Trading → Connections**).
2. Add **Tradovate**.
3. Enter:
   - **Username** and **Password** (your Tradovate login).
   - **API credentials** if Bookmap asks for them (Client ID / Secret from step 1).
4. Choose **Simulation** (paper) or **Live**.
5. Save and connect. Confirm you see “Connected” and that you can open a chart (e.g. NQ) with data.

### 4. Configure the bot for live

1. Open `d:\orderflow\fabio_bot\config.yaml`.
2. Set **mode** to live and (if you use env vars) ensure base URL matches your account:

   **Simulation (paper):**
   ```yaml
   mode: simulation
   # tradovate.base_url can stay as demo if your sim uses it
   ```

   **Live:**
   ```yaml
   mode: live
   # If you ever use Tradovate REST directly, use:
   # tradovate:
   #   base_url: "https://live.tradovateapi.com"
   ```

3. (Optional) Put credentials in environment variables instead of typing them in Bookmap again:
   - Windows PowerShell (run before opening Bookmap, or set in System env vars):
     ```powershell
     $env:TRADOVATE_CID = "your_client_id"
     $env:TRADOVATE_SEC = "your_api_secret"
     $env:TRADOVATE_USER = "your_username"
     $env:TRADOVATE_PASS = "your_password"
     ```
   - The add-on’s config can reference these via `${TRADOVATE_CID}` etc. if you add that in `config.yaml`; Bookmap itself uses what you entered in Connections.

### 5. Run the bot (paper first)

1. In Bookmap, open a chart for **NQ** or **MNQ** with the Tradovate connection.
2. Enable the Fabio add-on for that instrument (e.g. checkbox or “Enable” for the script).
3. The bot will:
   - Subscribe to depth and trades from Bookmap (Tradovate feed).
   - Run the strategy every 15 seconds (configurable).
   - Send orders through Bookmap to your **Tradovate** account (sim or live depending on connection).
4. Watch the log: `d:\orderflow\fabio_bot\logs\fabio_bot.log`.
5. Start with **Simulation** for at least a few days. When satisfied, switch the Tradovate connection in Bookmap to **Live** and set `mode: live` in config.

### 6. Safety checklist before live

- [ ] Ran in **Simulation** and verified orders and behavior.
- [ ] **Risk** in `config.yaml` is acceptable (e.g. `risk_pct: 0.01`, `max_daily_drawdown_pct`, `max_consecutive_losses`, `max_daily_trades`).
- [ ] Symbol and size are correct (e.g. **MNQ** for smaller size).
- [ ] Session times (`session_start` / `session_end`) match when you want the bot to trade (e.g. 09:30–16:00 ET).
- [ ] You understand that past backtest results do not guarantee future performance.

---

## Method B: Standalone with Tradovate REST API

The codebase includes a `TradovateClient` in `fabio_bot/execution_engine.py` that can place orders via Tradovate’s REST API. To run **fully standalone** (no Bookmap):

- You would need a **separate script** that:
  1. Gets market data from somewhere (e.g. Tradovate WebSocket, or another provider).
  2. Runs the same strategy logic (order flow analyzer + signal generator).
  3. Uses `TradovateClient` to send orders (with correct `account_id` and `contract_id` from Tradovate API).

Right now, **main.py is built for Bookmap**; it does not use `TradovateClient` for execution when running as an add-on. So for “connect to Tradovate and go live” with minimal change, use **Method A (Bookmap + Tradovate)**.

---

## Quick reference

| Step | Action |
|------|--------|
| 1 | Get Tradovate API Client ID + Secret and note username/password. |
| 2 | Install Bookmap; add add-on: `main.py`. |
| 3 | In Bookmap: Connections → Add Tradovate → enter credentials → connect (Sim or Live). |
| 4 | In `config.yaml`: set `mode: simulation` (then `live` when ready). |
| 5 | Open NQ/MNQ chart, enable add-on, monitor `logs/fabio_bot.log`. |
| 6 | After testing in sim, switch connection to Live and `mode: live`. |

For more on strategy parameters and risk, see `README.md` and `config.yaml`.
