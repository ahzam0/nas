#!/usr/bin/env python3
"""
Single-file Nasdaq-100 (MNQ) signal script. Copy this ENTIRE file and run anywhere (Python 3.6+).
  - PythonAnywhere: paste into a .py file, then Run.
  - Local: save as run_signal_anywhere.py and run:  python run_signal_anywhere.py
Uses only stdlib (urllib, json). No pip install. Fetches Yahoo 1m, runs order-flow logic, prints Signal/Entry/SL/TP1/TP2.
"""
from __future__ import print_function

import json
import time
import urllib.request

# ---------- Config (tune if you like) ----------
SYMBOL = "MNQ=F"
INTERVAL = "1m"
PERIOD_SEC = 7 * 86400  # 7 days
MIN_DELTA = 432
MIN_DELTA_MULT = 1.32
MIN_STRENGTH = 0.56
BIG_TRADE_EDGE = 3
BIG_TRADE_THRESHOLD = 30
RR_FIRST = 0.58
RR_SECOND = 1.42
ATR_STOP_MULT = 1.32
PIPS = 0.25

# ---------- Fetch Yahoo Chart API ----------
def fetch_yahoo_1m(symbol=SYMBOL, period_sec=PERIOD_SEC):
    t2 = int(time.time())
    t1 = t2 - period_sec
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        + symbol.replace("=", "%3D") + "?period1=" + str(t1) + "&period2=" + str(t2)
        + "&interval=" + INTERVAL + "&events=history"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
    except Exception as e:
        print("Fetch error:", e)
        return []
    try:
        res = data.get("chart", {}).get("result", [])
        if not res:
            return []
        r0 = res[0]
        ts = r0.get("timestamp", [])
        q = r0.get("indicators", {}).get("quote", [{}])[0]
        o = q.get("open") or []
        h = q.get("high") or []
        l_ = q.get("low") or []
        c = q.get("close") or []
        v = q.get("volume") or [0] * len(ts)
        n = min(len(ts), len(o), len(h), len(l_), len(c), len(v))
        if n < 50:
            return []
        bars = []
        for i in range(n):
            if o[i] is None or c[i] is None:
                continue
            vol = (v[i] or 0) if i < len(v) else 0
            vol = max(0, float(vol))
            # Approximate buy/sell from close vs open
            rng = (h[i] - l_[i]) if (h[i] and l_[i] and h[i] != l_[i]) else 0.25
            ratio = (c[i] - o[i]) / rng if rng else 0
            ratio = max(-1, min(1, ratio))
            buy_pct = 0.5 + 0.5 * ratio
            buy_vol = vol * buy_pct
            sell_vol = vol - buy_vol
            if buy_vol < 1:
                buy_vol = 1
            if sell_vol < 1:
                sell_vol = 1
            bars.append({
                "open": float(o[i]), "high": float(h[i]), "low": float(l_[i]), "close": float(c[i]),
                "buy_volume": buy_vol, "sell_volume": sell_vol,
            })
        return bars
    except Exception as e:
        print("Parse error:", e)
        return []


# ---------- Minimal order-flow state (no pandas) ----------
class SimpleAnalyzer:
    def __init__(self, pips=PIPS, big_thresh=BIG_TRADE_THRESHOLD):
        self.pips = pips
        self.big_thresh = big_thresh
        self.cvd = 0.0
        self.bars = []
        self.recent_big_buys = []
        self.recent_big_sells = []
        self.vol_at_price = {}

    def push_bar(self, o, h, l, c, buy_vol, sell_vol):
        self.cvd += (buy_vol - sell_vol)
        n_big_buy = 1 if buy_vol >= self.big_thresh * 1.2 else 0
        n_big_sell = 1 if sell_vol >= self.big_thresh * 1.2 else 0
        self.recent_big_buys.append(n_big_buy)
        self.recent_big_sells.append(n_big_sell)
        if len(self.recent_big_buys) > 30:
            self.recent_big_buys.pop(0)
            self.recent_big_sells.pop(0)
        price = round(c / self.pips) * self.pips
        self.vol_at_price[price] = self.vol_at_price.get(price, 0) + buy_vol + sell_vol
        self.bars.append({"open": o, "high": h, "low": l, "close": c, "buy_vol": buy_vol, "sell_vol": sell_vol, "delta": buy_vol - sell_vol})

    def get_big_counts(self):
        return sum(self.recent_big_buys or [0]), sum(self.recent_big_sells or [0])

    def get_cvd(self):
        return self.cvd

    def get_recent_bars(self, n=10):
        return self.bars[-n:] if self.bars else []

    def get_poc(self):
        if not self.vol_at_price:
            return 0.0
        return max(self.vol_at_price, key=self.vol_at_price.get)


# ---------- Signal logic ----------
def get_signal(analyzer, last_price, atr, min_delta=MIN_DELTA, min_mult=MIN_DELTA_MULT,
               min_strength=MIN_STRENGTH, big_edge=BIG_TRADE_EDGE, rr1=RR_FIRST, rr2=RR_SECOND, atr_mult=ATR_STOP_MULT):
    min_d_strong = min_delta * min_mult
    bars = analyzer.get_recent_bars(10)
    if not bars:
        return "NONE", 0.0, "no_bars", 20, 12, 36
    bar = bars[-1]
    cvd = analyzer.get_cvd()
    big_buys, big_sells = analyzer.get_big_counts()
    stop_ticks = max(10, int((atr / PIPS) * atr_mult))
    t1 = int(stop_ticks * rr1)
    t2 = int(stop_ticks * rr2)

    # LONG
    if cvd >= min_d_strong and bar["delta"] > 0 and big_buys >= big_sells + big_edge:
        strength = min(1.0, 0.4 * min(1.0, cvd / (min_d_strong * 2)) + 0.4 * min(1.0, (big_buys - big_sells) / 6) + 0.2)
        if strength >= min_strength:
            return "LONG", strength, "cvd_big_buys", stop_ticks, t1, t2
    # SHORT
    if cvd <= -min_d_strong and bar["delta"] < 0 and big_sells >= big_buys + big_edge:
        strength = min(1.0, 0.4 * min(1.0, abs(cvd) / (min_d_strong * 2)) + 0.4 * min(1.0, (big_sells - big_buys) / 6) + 0.2)
        if strength >= min_strength:
            return "SHORT", strength, "cvd_big_sells", stop_ticks, t1, t2
    return "NONE", 0.0, "no_setup", stop_ticks, t1, t2


# ---------- Main ----------
def main():
    print("Fetching", SYMBOL, INTERVAL, "data...")
    bars = fetch_yahoo_1m()
    if not bars:
        print("No bars. Try again or check symbol.")
        return
    print("Got", len(bars), "bars. Running signal...")
    analyzer = SimpleAnalyzer()
    atr = 15.0 * PIPS
    last_price = 0.0
    stop_ticks, t1_ticks, t2_ticks = 20, 12, 36
    sig = "NONE"
    strength = 0.0
    reason = "no_bars"
    for b in bars:
        o, h, l, c = b["open"], b["high"], b["low"], b["close"]
        bv, sv = b["buy_volume"], b["sell_volume"]
        analyzer.push_bar(o, h, l, c, bv, sv)
        last_price = c
        if (h - l) > 0:
            atr = (h - l) * 0.5 + atr * 0.5
        sig, strength, reason, stop_ticks, t1_ticks, t2_ticks = get_signal(analyzer, last_price, atr)

    # SL/TP prices
    if sig == "LONG":
        sl = last_price - stop_ticks * PIPS
        tp1 = last_price + t1_ticks * PIPS
        tp2 = last_price + t2_ticks * PIPS
    elif sig == "SHORT":
        sl = last_price + stop_ticks * PIPS
        tp1 = last_price - t1_ticks * PIPS
        tp2 = last_price - t2_ticks * PIPS
    else:
        sl = tp1 = tp2 = last_price

    print()
    print("--- Signal (Nasdaq-100 / MNQ) ---")
    print("  Signal:   ", sig)
    print("  Entry:    ", round(last_price, 2))
    print("  SL:       ", round(sl, 2))
    print("  TP1:      ", round(tp1, 2))
    print("  TP2:      ", round(tp2, 2))
    print("  Strength: ", round(strength, 2))
    print("  Reason:   ", reason)
    print("  Bars:     ", len(bars))
    print("  CVD:      ", round(analyzer.get_cvd(), 1))
    print("----------------------------")


if __name__ == "__main__":
    main()
