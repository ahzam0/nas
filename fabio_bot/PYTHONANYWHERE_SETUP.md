# Setup Fabio Bot on PythonAnywhere

Run the full application (Telegram signals + optional API) on PythonAnywhere **without uploading a folder**. Use **Git** to clone the repo, then schedule a task.

---

## 1. Put the project on GitHub (if not already)

On your PC:

```bash
cd d:\orderflow
git init
git add fabio_bot
git commit -m "Fabio bot"
# Create a new repo on GitHub (github.com -> New repository), then:
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
git branch -M main
git push -u origin main
```

If the project is already in a GitHub repo, skip this.

---

## 2. On PythonAnywhere: clone the repo

1. Log in to [pythonanywhere.com](https://www.pythonanywhere.com).
2. Open the **Consoles** tab → **Bash**.
3. Run (replace with your repo URL and use a folder name you like):

```bash
cd ~
git clone https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git fabio_bot
cd fabio_bot
```

If your repo is named `orderflow` and contains a `fabio_bot` folder (so the app files are inside `fabio_bot`), clone and then go into that folder:

```bash
git clone https://github.com/YOUR_USERNAME/orderflow.git orderflow
cd orderflow/fabio_bot
```

Use `orderflow/fabio_bot` as the project root in the paths below (e.g. `/home/YOUR_USERNAME/orderflow/fabio_bot`).

**Check structure** – from the folder that has `telegram_signal_once.py`:

```bash
ls -la
# You should see: backtest.py, telegram_signal_once.py, fabio_bot/, requirements.txt, config.yaml (or create it)
```

---

## 3. Virtualenv and dependencies

In the same Bash console (in the project root, where `requirements.txt` is):

```bash
# Use Python 3.10 (or 3.11 if available)
mkvirtualenv fabio_bot --python=python3.10
# or: python3.10 -m venv venv && source venv/bin/activate

pip install -r requirements.txt
```

If `yfinance` or others fail, you can install the minimum for the signal-once script:

```bash
pip install pandas numpy pyyaml requests
pip install yfinance
```

---

## 4. Config and secrets

You can use **environment variables** only (no `config.yaml`), or create `config.yaml`.

### Option A: Environment variables (easiest on PythonAnywhere)

1. **Dashboard** → **Account** → **Environment variables** (or add them when creating the scheduled task).
2. Add:
   - `TELEGRAM_BOT_TOKEN` = your bot token from @BotFather  
   - `TELEGRAM_CHAT_ID` = your chat ID (e.g. from @userinfobot)

Optional (for Alpaca or Binance data):

- `ALPACA_KEY_ID`, `ALPACA_SECRET_KEY`  
- (Binance needs no key; data source is set in config.)

### Option B: Create config.yaml in the project

In Bash:

```bash
cd ~/fabio_bot   # or your project path
nano config.yaml
```

Paste (replace with your token and chat_id):

```yaml
telegram:
  bot_token: "YOUR_BOT_TOKEN"
  chat_id: "YOUR_CHAT_ID"
  data_source: yahoo
  symbol: "MNQ=F"
  interval_seconds: 60
```

Save (Ctrl+O, Enter, Ctrl+X).

---

## 5. Strategy parameters (MNQ)

The script reads `data/best_params_mnq_1m.json`. Create the folder and file if you don’t have it:

```bash
mkdir -p data
nano data/best_params_mnq_1m.json
```

Paste (minimal set):

```json
{
  "params": {
    "min_signal_strength": 0.56,
    "min_delta": 432,
    "min_delta_multiplier": 1.32,
    "big_trade_edge": 3,
    "big_trade_threshold": 30,
    "rr_first": 0.58,
    "rr_second": 1.42,
    "atr_stop_multiplier": 1.32
  },
  "tick_value": 1
}
```

Save. Or copy `data/best_params_mnq_1m.json` from your local project (e.g. with `git add` and `git push` so it’s in the repo).

---

## 6. Schedule the Telegram signal (run every 1–2 minutes)

1. **Dashboard** → **Tasks**.
2. **Create a new task**:
   - **Time**: e.g. every 1 minute (or 2 minutes).
   - **Command** (use your PythonAnywhere username and path):

```bash
/home/YOUR_USERNAME/.virtualenvs/fabio_bot/bin/python /home/YOUR_USERNAME/fabio_bot/telegram_signal_once.py
```

If you use a venv inside the project:

```bash
/home/YOUR_USERNAME/fabio_bot/venv/bin/python /home/YOUR_USERNAME/fabio_bot/telegram_signal_once.py
```

Replace `YOUR_USERNAME` with your PythonAnywhere username (e.g. in the top-right or in the Bash prompt).

3. Save. The task will run every minute: fetch MNQ (or Alpaca/Binance) data, run the strategy, and send a Telegram message only when there is a LONG or SHORT signal. Open-trade state (TP1/TP2/SL) is stored in `data/open_trade.json` between runs.

---

## 7. Test once in the console

In a Bash console:

```bash
cd ~/fabio_bot
workon fabio_bot
# or: source venv/bin/activate
python telegram_signal_once.py
```

If you see no errors and you have a signal, you should get a message in Telegram. If there’s no signal, the script still exits with 0 (success).

---

## 8. Optional: run the API (Order Flow bars)

The main app (FastAPI) needs a long-running process. On the **free** tier you don’t get an always-on web app 24/7, but you can:

- Use **run_signal_anywhere.py** in the console whenever you want a quick signal (single file, stdlib only; see that file or the copy-paste instructions in the repo).
- On a **paid** account you can add a Web app and run the API (e.g. with uvicorn/gunicorn) if you want the Order Flow API endpoints.

For most users, **scheduling `telegram_signal_once.py`** is enough for the full Telegram signal app.

---

## 9. Checklist

- [ ] Repo on GitHub (or already cloned).
- [ ] Clone repo on PythonAnywhere; `cd` into project root (where `telegram_signal_once.py` is).
- [ ] Virtualenv created; `pip install -r requirements.txt` (or minimal deps above).
- [ ] `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` set (or `config.yaml` with `telegram.bot_token` and `telegram.chat_id`).
- [ ] `data/best_params_mnq_1m.json` present (created or copied).
- [ ] Task scheduled: run `python telegram_signal_once.py` every 1 (or 2) minutes.
- [ ] Test run in console: `python telegram_signal_once.py`.

---

## Paths summary (replace YOUR_USERNAME)

| Item              | Path |
|-------------------|------|
| Project root      | `/home/YOUR_USERNAME/fabio_bot` |
| Virtualenv (workon) | `fabio_bot` (after `mkvirtualenv fabio_bot`) |
| Task command     | `/home/YOUR_USERNAME/.virtualenvs/fabio_bot/bin/python /home/YOUR_USERNAME/fabio_bot/telegram_signal_once.py` |

If your repo is under a different folder (e.g. `orderflow/fabio_bot`), use that path in the task command and in `cd` steps.
