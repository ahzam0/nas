"""
Fetch real historical market data for backtesting.
Uses yfinance or Yahoo Chart API for NQ/MNQ futures (free). Approximates buy/sell volume from OHLCV.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def fetch_nq_yahoo_chart_api(
    symbol: str = "NQ=F",
    interval: str = "1d",
    period: Optional[str] = "1y",
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> pd.DataFrame:
    """
    Fetch OHLCV via Yahoo Finance Chart API (raw HTTP). Fallback when yfinance is blocked.
    """
    try:
        import requests
    except ImportError:
        return pd.DataFrame()
    if start and end:
        try:
            from datetime import datetime
            t1 = int(datetime.strptime(start, "%Y-%m-%d").timestamp())
            t2 = int(datetime.strptime(end, "%Y-%m-%d").timestamp())
        except Exception:
            return pd.DataFrame()
    else:
        # period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y. Yahoo caps intraday: 1m~7d, 5m/15m/1h~60d
        now = int(time.time())
        period_sec = {"1d": 86400, "5d": 5*86400, "7d": 7*86400, "1mo": 30*86400, "3mo": 90*86400, "6mo": 180*86400, "1y": 365*86400, "2y": 730*86400}
        requested = period_sec.get(period or "1y", 365*86400)
        if interval in ("1m", "2m"):
            requested = min(requested, 7*86400)  # 1m max 7 days
        elif interval in ("5m", "15m", "30m", "1h", "90m"):
            requested = min(requested, 60*86400)  # 5m/1h max 60 days
        t2 = now
        t1 = now - requested
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        + symbol.replace("=", "%3D") + "?period1=" + str(t1) + "&period2=" + str(t2)
        + "&interval=" + interval + "&events=history"
    )
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.warning("Yahoo chart API failed: %s", e)
        return pd.DataFrame()
    try:
        res = data.get("chart", {}).get("result", [])
        if not res:
            return pd.DataFrame()
        r0 = res[0]
        ts = r0.get("timestamp", [])
        quotes = r0.get("indicators", {}).get("quote", [{}])[0]
        o = quotes.get("open") or []
        h = quotes.get("high") or []
        l_ = quotes.get("low") or []
        c = quotes.get("close") or []
        v = quotes.get("volume") or [0] * len(ts)
        n = len(ts)
        if n < 2:
            return pd.DataFrame()
        df = pd.DataFrame({
            "open": o[:n], "high": h[:n], "low": l_[:n], "close": c[:n], "volume": v[:n],
        })
        df = df.dropna(subset=["open", "high", "low", "close"])
        df["volume"] = df["volume"].fillna(0).clip(lower=0)
        buy_vol, sell_vol = volume_split_from_ohlc(
            df["open"], df["high"], df["low"], df["close"], df["volume"]
        )
        df["buy_volume"] = buy_vol
        df["sell_volume"] = sell_vol
        df["bar_idx"] = range(len(df))
        return df.reset_index(drop=True)
    except Exception as e:
        logger.warning("Parse chart API response failed: %s", e)
        return pd.DataFrame()

# Optional dependency
try:
    import yfinance as yf
    HAS_YF = True
except ImportError:
    yf = None
    HAS_YF = False


def volume_split_from_ohlc(
    open_: pd.Series,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    """
    Approximate buy_volume and sell_volume from OHLCV when only total volume is available.
    Heuristic: bar delta proxy from (close - open) / range; allocate volume proportionally.
    """
    range_ = high - low
    range_ = range_.replace(0, np.nan)
    # ratio in [-1, 1]: positive => more buying
    ratio = (close - open_) / range_
    ratio = ratio.clip(-1.0, 1.0).fillna(0)
    buy_pct = 0.5 + 0.5 * ratio
    buy_vol = (volume * buy_pct).fillna(volume / 2)
    sell_vol = (volume - buy_vol).clip(lower=1)
    buy_vol = buy_vol.clip(lower=1)
    return buy_vol, sell_vol


def fetch_nq_yfinance(
    symbol: str = "NQ=F",
    interval: str = "1h",
    period: Optional[str] = "60d",
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> pd.DataFrame:
    """
    Download NQ (or MNQ) futures OHLCV from Yahoo Finance.
    Returns DataFrame with columns: open, high, low, close, volume, buy_volume, sell_volume, bar_idx.
    - interval: 1d, 1h, 15m, 5m (intraday limited to ~60 days by Yahoo).
    - period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, max (used if start/end not set).
    """
    if not HAS_YF:
        raise RuntimeError("yfinance is required for real data. Install with: pip install yfinance")

    # Use session with browser-like headers to reduce Yahoo blocking
    try:
        import requests
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        if start and end:
            df = yf.download(symbol, start=start, end=end, interval=interval, progress=False, auto_adjust=True, timeout=20, session=session)
        else:
            df = yf.download(symbol, period=period or "60d", interval=interval, progress=False, auto_adjust=True, timeout=20, session=session)
    except Exception as e:
        logger.warning("yfinance download failed: %s", e)
        return pd.DataFrame()

    if df.empty or len(df) < 2:
        logger.warning("No data returned for %s interval=%s period=%s", symbol, interval, period)
        return pd.DataFrame()

    # yfinance can return MultiIndex columns; flatten to lower case
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(c).lower() for c in df.columns.get_level_values(0)]
    else:
        df.columns = [str(c).lower() for c in df.columns]
    if "adj close" in df.columns and "close" not in df.columns:
        df["close"] = df["adj close"]
    for col in ["open", "high", "low", "close", "volume"]:
        if col not in df.columns:
            logger.warning("Missing column %s after download", col)
            return pd.DataFrame()

    df = df.dropna(subset=["open", "high", "low", "close"])
    df["volume"] = df["volume"].fillna(0).clip(lower=0)
    buy_vol, sell_vol = volume_split_from_ohlc(
        df["open"], df["high"], df["low"], df["close"], df["volume"]
    )
    df["buy_volume"] = buy_vol
    df["sell_volume"] = sell_vol
    df["bar_idx"] = range(len(df))
    return df.reset_index(drop=True)


def fetch_binance_1m(
    symbol: str = "BTCUSDT",
    limit_bars: int = 500,
) -> tuple[pd.DataFrame, str]:
    """
    Fetch 1m bars from Binance with **real** buy/sell volume (no API key).
    Uses public aggTrades: each trade has 'm' (buyer is maker) -> m=true = sell, m=false = buy.
    Returns (dataframe with open, high, low, close, buy_volume, sell_volume, bar_idx), symbol_used.
    """
    try:
        import urllib.request
        import json as _json
    except Exception:
        return pd.DataFrame(), symbol
    base = "https://api.binance.com/api/v3/aggTrades"
    all_trades: list = []
    end_time_ms: Optional[int] = None
    for _ in range(20):
        url = f"{base}?symbol={symbol}&limit=1000"
        if end_time_ms is not None:
            url += f"&endTime={end_time_ms}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                batch = _json.loads(resp.read().decode())
        except Exception as e:
            logger.warning("Binance aggTrades failed: %s", e)
            break
        if not batch:
            break
        all_trades.extend(batch)
        if len(batch) < 1000:
            break
        end_time_ms = min(int(t["T"]) for t in batch) - 1
        if len(all_trades) >= 10000:
            break
    if not all_trades:
        return pd.DataFrame(), symbol
    # Bucket by 1m (ms -> minute id)
    buckets: dict[int, list] = {}
    for t in all_trades:
        ts_ms = int(t["T"])
        minute_id = ts_ms // 60_000
        price = float(t["p"])
        qty = float(t["q"])
        is_sell = bool(t.get("m", True))
        if minute_id not in buckets:
            buckets[minute_id] = {"prices": [], "buy": 0.0, "sell": 0.0}
        buckets[minute_id]["prices"].append(price)
        if is_sell:
            buckets[minute_id]["sell"] += qty
        else:
            buckets[minute_id]["buy"] += qty
    # Build OHLCV per bar, sorted by time
    rows = []
    for mid in sorted(buckets.keys()):
        b = buckets[mid]
        prices = b["prices"]
        if not prices:
            continue
        rows.append({
            "open": prices[0],
            "high": max(prices),
            "low": min(prices),
            "close": prices[-1],
            "buy_volume": max(1.0, b["buy"]),
            "sell_volume": max(1.0, b["sell"]),
        })
    if not rows:
        return pd.DataFrame(), symbol
    df = pd.DataFrame(rows)
    df["volume"] = df["buy_volume"] + df["sell_volume"]
    df["bar_idx"] = range(len(df))
    return df, symbol


def fetch_nq_or_mnq_1m(
    symbol: str = "MNQ=F",
    interval: str = "1m",
    period: Optional[str] = "7d",
) -> tuple[pd.DataFrame, str]:
    """
    Fetch 1m bars for NQ/MNQ with fallbacks. Yahoo often fails on MNQ=F 1m (JSONDecodeError).
    Tries: (1) Yahoo Chart API with symbol, (2) yfinance with symbol, (3) NQ=F if symbol is MNQ=F.
    Returns (dataframe, symbol_used) so caller can log which ticker was used.
    """
    # 1) Chart API first (raw HTTP, often works when yfinance returns HTML/JSON error)
    df = fetch_nq_yahoo_chart_api(symbol=symbol, interval=interval, period=period)
    if not df.empty and len(df) >= 50:
        return df, symbol

    # 2) yfinance (may log ERROR; we still try)
    if HAS_YF:
        lvl = logging.getLogger("yfinance").level
        logging.getLogger("yfinance").setLevel(logging.CRITICAL)
        try:
            df = fetch_nq_yfinance(symbol=symbol, interval=interval, period=period)
        finally:
            logging.getLogger("yfinance").setLevel(lvl)
        if not df.empty and len(df) >= 50:
            return df, symbol

    # 3) For MNQ=F, try NQ=F (same underlying, Yahoo often has 1m for NQ)
    if symbol and "MNQ" in symbol.upper():
        df = fetch_nq_yahoo_chart_api(symbol="NQ=F", interval=interval, period=period)
        if not df.empty and len(df) >= 50:
            return df, "NQ=F"
        if HAS_YF:
            lvl = logging.getLogger("yfinance").level
            logging.getLogger("yfinance").setLevel(logging.CRITICAL)
            try:
                df = fetch_nq_yfinance(symbol="NQ=F", interval=interval, period=period)
            finally:
                logging.getLogger("yfinance").setLevel(lvl)
            if not df.empty and len(df) >= 50:
                return df, "NQ=F"

    return pd.DataFrame(), symbol


def fetch_and_save(
    symbol: str = "NQ=F",
    interval: str = "1h",
    period: str = "60d",
    start: Optional[str] = None,
    end: Optional[str] = None,
    out_path: Optional[str] = None,
) -> pd.DataFrame:
    """Fetch real NQ data and optionally save to CSV."""
    df = fetch_nq_yfinance(symbol=symbol, interval=interval, period=period, start=start, end=end)
    if df.empty:
        return df
    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_path, index=False)
        logger.info("Saved %d bars to %s", len(df), out_path)
    return df


def fetch_alpaca_1m(
    symbol: str = "QQQ",
    key_id: Optional[str] = None,
    secret_key: Optional[str] = None,
    lookback_minutes: int = 4320,
) -> tuple[pd.DataFrame, str]:
    """
    Fetch 1m bars with real buy/sell volume from Alpaca (Nasdaq-100 proxy via QQQ).
    Free with Alpaca paper account. Uses trades API to get taker side (tks) or infers from price vs open.
    Returns (dataframe with open, high, low, close, buy_volume, sell_volume, bar_idx), symbol_used.
    Requires ALPACA_KEY_ID and ALPACA_SECRET_KEY in config or env.
    """
    import urllib.request
    import urllib.error
    import json as _json
    from datetime import datetime, timezone, timedelta

    key_id = (key_id or "").strip() or __import__("os").environ.get("ALPACA_KEY_ID", "").strip()
    secret_key = (secret_key or "").strip() or __import__("os").environ.get("ALPACA_SECRET_KEY", "").strip()
    if not key_id or not secret_key:
        logger.warning("Alpaca: set ALPACA_KEY_ID and ALPACA_SECRET_KEY (free at alpaca.markets)")
        return pd.DataFrame(), symbol

    # Free tier may reject "too recent" data; end 2 minutes ago to be safe
    end = datetime.now(timezone.utc) - timedelta(minutes=2)
    start = end - timedelta(minutes=lookback_minutes)
    start_str = start.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_str = end.strftime("%Y-%m-%dT%H:%M:%SZ")
    base = "https://data.alpaca.markets/v2/stocks"
    # Use both header auth and Basic Auth (key_id:secret as user:pass) for compatibility
    import base64
    b64 = base64.b64encode(f"{key_id}:{secret_key}".encode()).decode()
    headers = {
        "APCA-API-KEY-ID": key_id,
        "APCA-API-SECRET-KEY": secret_key,
        "Authorization": f"Basic {b64}",
    }

    # 1) Get 1m bars for OHLC (free tier: limit-only works; start/end can 403 — paginate by end_time)
    bars_list: list = []
    page_end: Optional[str] = None
    for _ in range(30):
        if page_end is None:
            bars_url = f"{base}/{symbol}/bars?timeframe=1Min&limit=5000"
        else:
            bars_url = f"{base}/{symbol}/bars?timeframe=1Min&end={page_end}&limit=5000"
        try:
            req = urllib.request.Request(bars_url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                bars_data = _json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if not bars_list:
                logger.warning("Alpaca bars failed: %s %s", e.code, e.reason)
            break
        except Exception as e:
            if not bars_list:
                logger.warning("Alpaca bars failed: %s", e)
            break
        page_bars = bars_data.get("bars") or []
        if not page_bars:
            break
        bars_list = page_bars + bars_list
        if len(bars_list) >= lookback_minutes:
            break
        first_ts = page_bars[0].get("t") or page_bars[0].get("T")
        if not first_ts:
            break
        page_end = first_ts
    # Deduplicate by timestamp
    seen = set()
    unique = []
    for b in bars_list:
        t = b.get("t") or b.get("T")
        if t and t not in seen:
            seen.add(t)
            unique.append(b)
    bars_list = unique
    if not bars_list:
        return pd.DataFrame(), symbol
    # Use bars' time range for trades (free tier may 403 on "now")
    first_ts = bars_list[0].get("t") or bars_list[0].get("T")
    last_ts = bars_list[-1].get("t") or bars_list[-1].get("T")
    trades_start = first_ts if isinstance(first_ts, str) else start_str
    trades_end = last_ts if isinstance(last_ts, str) else end_str

    # 2) Get trades for the same window (for buy/sell volume)
    trades_url = f"{base}/{symbol}/trades?start={trades_start}&end={trades_end}&limit=50000"
    try:
        req = urllib.request.Request(trades_url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as resp:
            trades_data = _json.loads(resp.read().decode())
    except Exception as e:
        logger.warning("Alpaca trades failed: %s", e)
        trades_list = []
    else:
        trades_list = trades_data.get("trades") or []

    # Build minute -> OHLC from bars
    minute_ohlc: dict[int, dict] = {}
    for b in bars_list:
        t_str = b.get("t") or b.get("T")
        if not t_str:
            continue
        try:
            dt = datetime.fromisoformat(t_str.replace("Z", "+00:00"))
            minute_id = int(dt.timestamp()) // 60
        except Exception:
            continue
        minute_ohlc[minute_id] = {
            "open": float(b["o"]),
            "high": float(b["h"]),
            "low": float(b["l"]),
            "close": float(b["c"]),
            "buy_volume": 0.0,
            "sell_volume": 0.0,
        }

    # Aggregate trades into 1m buckets with buy/sell
    for t in trades_list:
        t_str = t.get("t") or t.get("T")
        if not t_str:
            continue
        try:
            dt = datetime.fromisoformat(t_str.replace("Z", "+00:00"))
            minute_id = int(dt.timestamp()) // 60
        except Exception:
            continue
        if minute_id not in minute_ohlc:
            continue
        price = float(t.get("p", 0))
        size = float(t.get("s", 0))
        tks = (t.get("tks") or t.get("taker_side") or "").upper()
        ohlc = minute_ohlc[minute_id]
        if tks in ("B", "BUY"):
            ohlc["buy_volume"] += size
        elif tks in ("S", "SELL"):
            ohlc["sell_volume"] += size
        else:
            # Infer: trade above bar open => buy
            if price >= ohlc["open"]:
                ohlc["buy_volume"] += size
            else:
                ohlc["sell_volume"] += size

    # Ensure non-zero volume per bar
    for mid, ohlc in minute_ohlc.items():
        if ohlc["buy_volume"] <= 0 and ohlc["sell_volume"] <= 0:
            vol = (ohlc["open"] + ohlc["close"]) / 2
            ohlc["buy_volume"] = max(1.0, vol / 2)
            ohlc["sell_volume"] = max(1.0, vol / 2)

    rows = [{"minute_id": mid, **ohlc} for mid, ohlc in sorted(minute_ohlc.items())]
    if not rows:
        return pd.DataFrame(), symbol
    df = pd.DataFrame(rows)
    df["volume"] = df["buy_volume"] + df["sell_volume"]
    df["bar_idx"] = range(len(df))
    df = df[["open", "high", "low", "close", "volume", "buy_volume", "sell_volume", "bar_idx"]]
    return df, symbol


def fetch_orderflow_bars(
    source: str = "yahoo",
    symbol: Optional[str] = None,
    alpaca_key_id: Optional[str] = None,
    alpaca_secret_key: Optional[str] = None,
    interval: str = "1m",
    period: str = "7d",
    lookback_minutes: int = 500,
) -> tuple[pd.DataFrame, str]:
    """
    Unified API: fetch 1m bars with order-flow style data (open, high, low, close, buy_volume, sell_volume)
    from free sources. Returns (dataframe, symbol_used).

    - source: "yahoo" (MNQ/NQ), "binance" (crypto), "alpaca" (QQQ/stocks)
    - symbol: for yahoo use "MNQ=F" or "NQ=F"; for binance "BTCUSDT"; for alpaca "QQQ"
    """
    source = (source or "yahoo").strip().lower()
    if source == "binance":
        sym = (symbol or "BTCUSDT").strip()
        return fetch_binance_1m(symbol=sym)
    if source == "alpaca":
        sym = (symbol or "QQQ").strip()
        return fetch_alpaca_1m(
            symbol=sym,
            key_id=alpaca_key_id,
            secret_key=alpaca_secret_key,
            lookback_minutes=lookback_minutes,
        )
    # yahoo (default): futures MNQ/NQ
    sym = (symbol or "MNQ=F").strip()
    return fetch_nq_or_mnq_1m(symbol=sym, interval=interval, period=period)
