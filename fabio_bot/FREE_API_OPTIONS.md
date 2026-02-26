# Free API / Broker Options (Instead of Paid Tradovate API)

If Tradovate is charging for API access, you can use one of these **free or low-cost** options to run the Fabio bot with Bookmap.

---

## Option 1: Interactive Brokers (IB) – Free API with Bookmap **(recommended)**

**Interactive Brokers** offers a **free TWS API** – no separate API fee. You only need an IB account. Bookmap can connect to IB for both **data** and **execution**, so the same add-on works: orders go through Bookmap → IB instead of Bookmap → Tradovate.

### What you need

- **IBKR Pro account** (not Lite – Lite does not support API).
- **TWS (Trader Workstation)** or **IB Gateway** installed and running on your PC.
- **Bookmap** with an **Interactive Brokers – TWS** connection (no extra Bookmap fee for using IB).

### Steps

1. **Open an IBKR Pro account** at [interactivebrokers.com](https://www.interactivebrokers.com).  
   - API access is included; there is no separate “API subscription” fee.
2. **Install TWS or IB Gateway** and log in.
3. **Enable API in TWS:**  
   **Edit → Global Configuration → API → Settings**  
   - Enable **“Enable ActiveX and Socket Clients”**.  
   - Note the port: **7496** (live) or **7497** (paper).  
   - Allow **Trusted IPs** (e.g. `127.0.0.1`) if required.
4. **In Bookmap:**  
   **Connections → Configure → Add Connection**  
   - Choose **“Interactive Brokers – TWS”**.  
   - Host: **localhost**, Port: **7497** (paper) or **7496** (live).  
   - Connect.
5. **Use the same Fabio add-on** – load `main.py` in Bookmap and enable it on NQ/MNQ.  
   - Orders will go to your **IB** account instead of Tradovate.  
   - No code change needed; Bookmap routes to the broker you’re connected to.

### Notes

- **Futures data:** IB may provide top-of-book for many futures; depth can be more limited than a dedicated order-flow feed. For full depth/MBO, you can later add a data-only connection (e.g. dxFeed) in Bookmap and keep IB for execution.
- **Market data:** IB may charge for some market data subscriptions depending on your account; check their site for current fees.
- **Paper first:** Use port **7497** (paper) to test before going live (7496).

---

## Option 2: Tradovate Demo (Free for a limited time)

- Tradovate offers a **free demo/simulation** account (e.g. 2-week trial, $50k sim balance).
- You can use **demo** API endpoints (`https://demo.tradovateapi.com`) with that demo account for **paper trading** only – often without a separate API fee during the trial.
- If Tradovate is asking for money, it is likely for:
  - **Live** trading/API, or  
  - A **paid subscription** after the trial.  
- For **free paper trading only**, confirm with Tradovate whether the demo account + demo API remains free and for how long.

---

## Option 3: Other brokers Bookmap supports

Bookmap can connect to several brokers. If a broker offers **free API** with your account:

- Add that broker in Bookmap under **Connections → Configure**.
- Connect it and use the same Fabio add-on; execution will go through that broker instead of Tradovate.

Check the **Bookmap** site or **Connections** dialog for the current list (e.g. Rithmic, AMP, etc.). Some have one-time or monthly fees; compare with IB’s free API.

---

## Summary

| Option              | API cost     | Use with Fabio bot                          |
|---------------------|-------------|---------------------------------------------|
| **Interactive Brokers** | Free TWS API | Bookmap → Add “Interactive Brokers – TWS” → same add-on, orders to IB |
| **Tradovate demo**  | Often free for demo | Bookmap → Tradovate (demo) for paper only   |
| **Other Bookmap brokers** | Varies      | Add in Bookmap; same add-on, orders to that broker |

For a **free API** path: use **Interactive Brokers** with Bookmap and connect **IB – TWS** instead of Tradovate. Your config can stay the same; only the connection in Bookmap changes.
