# Custom Trading API – No Direct Tradovate API

You **do not use Tradovate’s API** in your code or dashboard. This server is your **single custom API** that:

1. **Automatically connects** to your Tradovate account when the server starts (using credentials from `config.yaml`).
2. **Takes trades for you** via simple HTTP calls to this server only.

## Setup (one time)

1. Add your Tradovate credentials to `config.yaml` under `tradovate:`:
   - `username`, `password`
   - `client_id`, `client_secret` (from Tradovate API / developer settings)
   - `symbol` (e.g. NQ, MNQ)
   - Optional: `contract_id` if order placement needs it

2. Start the server:
   ```bash
   cd fabio_bot
   uvicorn api_server:app --host 0.0.0.0 --port 8000
   ```

3. Open **http://localhost:8000** for the dashboard, or call the API from any client.

## What you use (this API only)

| What you want           | How you do it                                      |
|-------------------------|----------------------------------------------------|
| Connect to Tradovate    | Server does it automatically on startup           |
| See account / positions | `GET /api/account`, `GET /api/positions`           |
| Place a market order    | `POST /api/trade` with `{"side": "buy"\|"sell", "quantity": 1}` |
| Close a position        | `POST /api/positions/{ticket}/close`               |
| Check connection        | `GET /api/status`                                 |

All of these go to **this server** (e.g. `http://localhost:8000`). The server talks to Tradovate internally; you never call Tradovate’s API directly.

## Summary

- **Custom API** = this FastAPI server (`api_server.py`).
- **Automatic connect** = credentials in config; server connects on startup.
- **Takes trades for you** = use `POST /api/trade` and `POST /api/positions/{id}/close`; the bot also uses the same connection to place trades when it runs.

For more endpoints, see `GET http://localhost:8000/api`.
