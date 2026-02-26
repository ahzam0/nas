"""
Custom Trading API (no frontend).
Signals: run telegram_bot.py for Telegram trade signals.

- Put Tradovate credentials in config.yaml for trading.
- All trading: POST /api/trade, POST /api/positions/{id}/close.
Run: uvicorn api_server:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_BOT_PROCESS = None
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from datetime import datetime
from typing import Any, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Fabio Bot – Custom Trading API",
    version="1.0",
    description="Single API to connect your Tradovate account and place/close trades. No direct Tradovate API usage.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _auto_connect():
    """Automatically connect to Tradovate on startup using config credentials."""
    try:
        get_client()
    except Exception:
        pass


# Lazy broker client (Tradovate or Demo)
_client: Optional[Any] = None
_last_connection_error: Optional[str] = None
_demo_mode = False

# In-memory credentials from dashboard (override config when set)
_memory_credentials: dict = {}


def set_memory_credentials(creds: dict) -> None:
    """Store credentials from dashboard so get_client() uses them for connection."""
    global _memory_credentials
    _memory_credentials = {k: v for k, v in (creds or {}).items() if v}


def reset_client():
    """Clear cached client so next get_client() tries Tradovate again."""
    global _client
    _client = None


def get_client():
    """Return Tradovate or Demo client so dashboard always works."""
    global _client, _last_connection_error, _demo_mode
    if _client is not None:
        if getattr(_client, "is_connected", lambda: True)():
            return _client
        _client = None
        _demo_mode = False
    cfg = {}
    try:
        from fabio_bot.config_loader import load_config
        cfg = load_config(ROOT / "config.yaml") if (ROOT / "config.yaml").exists() else {}
    except Exception:
        pass

    tv = cfg.get("tradovate", {})
    if _memory_credentials:
        tv = {**tv, **_memory_credentials}
    base_url = (tv.get("base_url") or os.environ.get("TRADOVATE_BASE_URL") or "https://demo.tradovateapi.com").strip()
    name = (tv.get("username") or tv.get("name") or os.environ.get("TRADOVATE_USER") or "").strip()
    password = (tv.get("password") or os.environ.get("TRADOVATE_PASS") or "").strip()
    cid = (tv.get("client_id") or tv.get("cid") or os.environ.get("TRADOVATE_CID") or "").strip()
    sec = (tv.get("client_secret") or tv.get("sec") or os.environ.get("TRADOVATE_SEC") or "").strip()
    symbol = (tv.get("symbol") or os.environ.get("TRADOVATE_SYMBOL") or "NQ").strip()
    contract_id = tv.get("contract_id") or (int(os.environ["TRADOVATE_CONTRACT_ID"]) if os.environ.get("TRADOVATE_CONTRACT_ID") else None)

    if name and password and cid and sec:
        try:
            from fabio_bot.tradovate_client import TradovateClient
            _client = TradovateClient(
                base_url=base_url,
                name=name,
                password=password,
                cid=cid,
                sec=sec,
                symbol=symbol,
                contract_id=contract_id,
                app_id=tv.get("app_id") or "fabio_bot",
                app_version=tv.get("app_version") or "1.0",
            )
            if _client.connect():
                _last_connection_error = None
                _demo_mode = False
                return _client
            _last_connection_error = "Tradovate login failed. Check config tradovate (username, password, client_id, client_secret)."
        except Exception as e:
            _last_connection_error = str(e)

    from fabio_bot.demo_client import DemoClient
    _client = DemoClient(symbol=symbol or "NQ")
    _demo_mode = True
    if not _last_connection_error:
        _last_connection_error = "No Tradovate connection. Using demo data."
    return _client


@app.get("/api")
def api_info():
    """Custom API info – you use this server only; no direct Tradovate API."""
    return {
        "name": "Fabio Bot Custom Trading API",
        "usage": "Configure Tradovate in config.yaml. This server auto-connects and executes all trades.",
        "endpoints": {
            "GET /api/status": "Connection and symbol",
            "GET /api/symbols": "All tradable pairs (Tradovate contracts)",
            "GET /api/account": "Balance, equity, margin",
            "GET /api/positions": "Open positions",
            "GET /api/history": "Trade history",
            "GET /api/tick": "Bid/ask/last",
            "POST /api/trade": "Place market order (body: side, quantity)",
            "POST /api/positions/{ticket}/close": "Close position",
            "GET /api/bot-status": "Trading bot status",
            "POST /api/bot/start": "Start bot",
            "POST /api/bot/stop": "Stop bot",
            "GET /api/orderflow/sources": "Free order-flow data sources",
            "GET /api/orderflow/bars": "Real-time bars with buy/sell volume (source, symbol, limit)",
        },
    }


@app.post("/api/tradovate-credentials")
def api_tradovate_credentials(body: dict):
    """Save Tradovate credentials from dashboard and connect immediately. Body: username, password, client_id, client_secret."""
    username = (body.get("username") or body.get("name") or "").strip()
    password = (body.get("password") or "").strip()
    client_id = (body.get("client_id") or body.get("cid") or "").strip()
    client_secret = (body.get("client_secret") or body.get("sec") or "").strip()
    if not all([username, password, client_id, client_secret]):
        raise HTTPException(
            status_code=400,
            detail="Missing username, password, client_id, or client_secret",
        )
    set_memory_credentials({
        "username": username,
        "password": password,
        "client_id": client_id,
        "client_secret": client_secret,
    })
    reset_client()
    c = get_client()
    if _demo_mode:
        raise HTTPException(
            status_code=400,
            detail=_last_connection_error or "Tradovate login failed. Check credentials.",
        )
    return {"ok": True, "message": "Connected to Tradovate", "symbol": c.symbol}


@app.post("/api/reconnect")
def api_reconnect():
    """Clear cached connection so next request tries Tradovate again."""
    reset_client()
    get_client()
    return {"ok": True, "message": "Reconnected"}


@app.get("/api/status")
def api_status():
    c = get_client()
    return {
        "connected": True,
        "symbol": c.symbol,
        "demo": _demo_mode,
    }


@app.get("/api/account")
def api_account():
    c = get_client()
    acc = c.get_account_info()
    if not acc:
        raise HTTPException(status_code=503, detail="No account info")
    return {
        "login": acc.login,
        "balance": acc.balance,
        "equity": acc.equity,
        "margin": acc.margin,
        "free_margin": acc.margin_free,
        "leverage": acc.leverage,
        "server": acc.server,
        "currency": acc.currency,
    }


@app.get("/api/positions")
def api_positions():
    c = get_client()
    positions = c.get_positions()
    out = []
    for p in positions:
        out.append({
            "ticket": p.ticket,
            "symbol": p.symbol,
            "type": "buy" if p.type == 0 else "sell",
            "volume": p.volume,
            "price_open": p.price_open,
            "price_current": p.price_current,
            "sl": p.sl,
            "tp": p.tp,
            "profit": p.profit,
            "time": p.time,
        })
    return out


@app.get("/api/history")
def api_history(days: int = 7):
    c = get_client()
    deals = c.get_deals_history(days=days)
    out = []
    for d in deals:
        try:
            entry = d._asdict()
        except Exception:
            entry = {
                "ticket": getattr(d, "ticket", 0),
                "symbol": getattr(d, "symbol", ""),
                "type": "buy" if getattr(d, "type", 0) == 0 else "sell",
                "volume": getattr(d, "volume", 0),
                "price": getattr(d, "price", 0),
                "profit": getattr(d, "profit", 0),
                "time": getattr(d, "time", 0),
                "comment": getattr(d, "comment", ""),
            }
        # time may be int (unix); convert for JSON
        if "time" in entry and hasattr(entry["time"], "timestamp"):
            entry["time"] = int(entry["time"].timestamp())
        out.append(entry)
    return out[:200]


@app.get("/api/bars")
def api_bars(timeframe: str = "1m", count: int = 100):
    c = get_client()
    bars = c.get_bars(timeframe=timeframe, count=min(count, 500), start_pos=0)
    return [
        {"time": b.time, "open": b.open, "high": b.high, "low": b.low, "close": b.close, "volume": b.volume}
        for b in bars
    ]


@app.get("/api/activity")
def api_activity(limit: int = 80):
    try:
        from activity_store import get_all
        return get_all(limit=limit)
    except Exception:
        return []


@app.get("/api/connection-error")
def api_connection_error():
    """Last connection error message (if any) for dashboard display."""
    global _last_connection_error, _demo_mode
    if _demo_mode and _last_connection_error:
        return {
            "error": "Demo mode – using sample data. For live data: set Tradovate credentials in config (tradovate: username, password, client_id, client_secret), then restart the server.",
            "demo": True,
        }
    return {"error": _last_connection_error, "demo": _demo_mode}


@app.get("/api/bot-status")
def api_bot_status():
    """Whether the trading bot (run_bot.py) is running. Based on last heartbeat."""
    try:
        from activity_store import get_bot_status
        out = get_bot_status()
        global _BOT_PROCESS
        out["started_by_dashboard"] = _BOT_PROCESS is not None and _BOT_PROCESS.poll() is None
        return out
    except Exception:
        return {"running": False, "last_heartbeat": None, "started_by_dashboard": False}


@app.post("/api/bot/start")
def api_bot_start():
    """Start the trading bot (run_bot.py) in the background."""
    global _BOT_PROCESS
    if _BOT_PROCESS is not None and _BOT_PROCESS.poll() is None:
        return {"started": True, "message": "Bot already running"}
    run_bot = ROOT / "run_bot.py"
    if not run_bot.exists():
        raise HTTPException(status_code=501, detail="run_bot.py not found. Bot not configured.")
    try:
        env = os.environ.copy()
        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        _BOT_PROCESS = subprocess.Popen(
            [sys.executable, str(run_bot)],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        return {"started": True, "message": "Trading bot started", "pid": _BOT_PROCESS.pid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start bot: {e}")


@app.post("/api/bot/stop")
def api_bot_stop():
    """Stop the trading bot if it was started from this dashboard."""
    global _BOT_PROCESS
    if _BOT_PROCESS is None:
        return {"stopped": False, "message": "No bot process started from dashboard"}
    try:
        _BOT_PROCESS.terminate()
        _BOT_PROCESS.wait(timeout=10)
    except Exception:
        try:
            _BOT_PROCESS.kill()
        except Exception:
            pass
    _BOT_PROCESS = None
    return {"stopped": True, "message": "Trading bot stopped"}


@app.get("/api/symbols")
def api_symbols():
    """Return all tradable pairs (Tradovate contracts or demo list). Used by frontend symbol selector."""
    c = get_client()
    if hasattr(c, "get_contracts"):
        symbols = c.get_contracts()
    else:
        symbols = [{"id": None, "name": c.symbol, "symbol": c.symbol}]
    return {"symbols": symbols, "current": c.symbol}


@app.get("/api/tick")
def api_tick():
    c = get_client()
    t = c.get_tick()
    if not t:
        raise HTTPException(status_code=503, detail="No tick")
    return {"bid": t[0], "ask": t[1], "last": t[2]}


@app.post("/api/trade")
def api_trade(body: dict):
    """Place market order. Body: { "side": "buy"|"sell", "quantity": number, "symbol": optional }."""
    c = get_client()
    side = (body.get("side") or "").strip().lower()
    if side not in ("buy", "sell"):
        raise HTTPException(status_code=400, detail="side must be 'buy' or 'sell'")
    try:
        qty = float(body.get("quantity", 1))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="quantity must be a number")
    if qty <= 0:
        raise HTTPException(status_code=400, detail="quantity must be positive")
    is_buy = side == "buy"
    trade_symbol = (body.get("symbol") or "").strip() or None
    if hasattr(c, "place_market_order"):
        try:
            result = c.place_market_order(is_buy, qty, comment="Dashboard", symbol=trade_symbol)
        except TypeError:
            result = c.place_market_order(is_buy, qty, comment="Dashboard")
        if hasattr(result, "success"):
            ok, msg = result.success, getattr(result, "comment", "") or str(result)
        else:
            ok, msg = result[0], result[1] if len(result) > 1 else ""
        if not ok:
            raise HTTPException(status_code=400, detail=msg)
        return {"ok": True, "message": msg}
    raise HTTPException(status_code=501, detail="Trading not supported for this client")


@app.post("/api/positions/{ticket:int}/close")
def api_close_position(ticket: int):
    """Close position by ticket id."""
    c = get_client()
    if hasattr(c, "close_position"):
        if c.close_position(ticket):
            return {"ok": True, "message": "Position closed"}
        raise HTTPException(status_code=400, detail="Close failed or position not found")
    raise HTTPException(status_code=501, detail="Close not supported for this client")


# ---------- Order Flow API (free real-time bars with buy/sell volume) ----------


def _load_telegram_config() -> dict:
    try:
        from fabio_bot.config_loader import load_config
        cfg = load_config(ROOT / "config.yaml") if (ROOT / "config.yaml").exists() else {}
        return cfg.get("telegram", {})
    except Exception:
        return {}


@app.get("/api/orderflow/sources")
def api_orderflow_sources():
    """List free order-flow data sources. Nasdaq-100 first (for signal app)."""
    return {
        "nasdaq100": "Use source=yahoo with MNQ=F/NQ=F, or source=alpaca with QQQ (see sources below).",
        "sources": [
            {
                "id": "yahoo",
                "name": "Yahoo – Nasdaq-100 futures (MNQ/NQ)",
                "symbols": "MNQ=F, NQ=F",
                "params": "source=yahoo&symbol=MNQ=F",
                "note": "Free, no key. OHLC + approximated buy/sell. Best for Nasdaq-100 signals.",
            },
            {
                "id": "alpaca",
                "name": "Alpaca – Nasdaq-100 ETF (QQQ)",
                "symbols": "QQQ (same index as MNQ)",
                "params": "source=alpaca&symbol=QQQ",
                "note": "Free keys at alpaca.markets; real trades when available.",
            },
            {
                "id": "binance",
                "name": "Binance (crypto only – not Nasdaq-100)",
                "symbols": "BTCUSDT, ETHUSDT, etc.",
                "params": "source=binance&symbol=BTCUSDT",
                "note": "Optional; real buy/sell, no key. Use only if you want crypto instead of Nasdaq-100.",
            },
        ],
        "bars_endpoint": "GET /api/orderflow/bars?source=yahoo&symbol=MNQ=F&limit=200",
        "nasdaq100_one_click": "GET /api/orderflow/bars?market=nasdaq100&limit=200  (uses config data_source + symbol)",
    }


@app.get("/api/orderflow/bars")
def api_orderflow_bars(
    source: Optional[str] = None,
    symbol: Optional[str] = None,
    limit: int = 200,
    market: Optional[str] = None,
):
    """
    Fetch real-time order-flow style 1m bars for Nasdaq-100 (or crypto if you set source=binance).
    Default: Nasdaq-100 via Yahoo MNQ=F. Use market=nasdaq100 to use config data_source + symbol.
    """
    tg = _load_telegram_config()
    alpaca_key = (tg.get("alpaca_key_id") or "").strip()
    alpaca_secret = (tg.get("alpaca_secret_key") or "").strip()

    # Nasdaq-100 one-click: use config
    if (market or "").strip().lower() == "nasdaq100":
        source = (tg.get("data_source") or "yahoo").strip().lower()
        if source == "alpaca":
            symbol = (tg.get("alpaca_symbol") or "QQQ").strip()
        elif source == "binance":
            symbol = (tg.get("binance_symbol") or "BTCUSDT").strip()
        else:
            symbol = (tg.get("symbol") or "MNQ=F").strip()
    if not source:
        source = (tg.get("data_source") or "yahoo").strip().lower()
    if not symbol:
        if source == "alpaca":
            symbol = (tg.get("alpaca_symbol") or "QQQ").strip()
        elif source == "binance":
            symbol = (tg.get("binance_symbol") or "BTCUSDT").strip()
        else:
            symbol = (tg.get("symbol") or "MNQ=F").strip()
    try:
        from fabio_bot.fetch_market_data import fetch_orderflow_bars as fetch_bars
        df, symbol_used = fetch_bars(
            source=source,
            symbol=symbol,
            alpaca_key_id=alpaca_key or None,
            alpaca_secret_key=alpaca_secret or None,
            lookback_minutes=max(500, limit + 60),
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Order flow fetch failed: {e}")
    if df is None or df.empty:
        return {
            "source": source,
            "symbol_requested": symbol,
            "symbol_used": symbol_used,
            "bars": [],
            "count": 0,
            "updated_utc": datetime.utcnow().isoformat() + "Z",
        }
    # Normalize columns (some sources may have minute_id)
    cols = ["open", "high", "low", "close", "volume", "buy_volume", "sell_volume", "bar_idx"]
    available = [c for c in cols if c in df.columns]
    df = df[available].tail(int(limit))
    bars: List[dict] = df.to_dict(orient="records")
    for b in bars:
        for k, v in b.items():
            if hasattr(v, "item"):
                b[k] = v.item()
            elif isinstance(v, (float,)) and (v != v):  # nan
                b[k] = None
    return {
        "source": source,
        "symbol_requested": symbol,
        "symbol_used": symbol_used,
        "bars": bars,
        "count": len(bars),
        "updated_utc": datetime.utcnow().isoformat() + "Z",
    }


@app.get("/")
def root():
    return {"app": "Fabio Bot API", "signals": "Run telegram_bot.py for Telegram signals", "docs": "/docs"}
