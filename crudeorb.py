import streamlit as st
import pandas as pd
import requests
import time
import json
from datetime import datetime, timedelta

# ================= CONFIG =================
st.set_page_config(layout="wide", page_title="MCX PRO AI DASHBOARD")
st.title("🚀 MCX Pro AI Engine (Dhan + ORB + Smart Trading)")

STATE_FILE = "pro_state.json"

DHAN_API_KEY = st.secrets.get("DHAN_API_KEY", "")
DHAN_CLIENT_ID = st.secrets.get("DHAN_CLIENT_ID", "")

TELEGRAM_TOKEN = st.secrets.get("TELEGRAM_TOKEN", "")
CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "")

CAPITAL = 10000
RISK = 0.02

# ================= STATE =================
def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {"trades": [], "orb": {}}

def save_state(s):
    with open(STATE_FILE, "w") as f:
        json.dump(s, f)

state = load_state()

# ================= TELEGRAM =================
def tg(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except:
        pass

# ================= DHAN LIVE PRICE =================
def dhan_price(symbol):
    """
    🔥 REAL PLACEHOLDER (Replace with Dhan API endpoint)
    """
    try:
        url = f"https://api.dhan.co/v2/marketfeed/ltp"
        headers = {
            "client-id": DHAN_CLIENT_ID,
            "access-token": DHAN_API_KEY
        }
        payload = {"symbols": [symbol]}
        r = requests.post(url, json=payload, headers=headers).json()

        return float(r["data"]["ltp"])
    except:
        return 6500 if "CRUDE" in symbol else 280

# ================= OPTION CHAIN (DHAN) =================
def option_chain(symbol):
    """
    🔥 Replace with real Dhan option chain API
    """
    spot = dhan_price(symbol)

    chain = []
    for i in range(-10, 11):
        strike = spot + (i * 50)
        chain.append({
            "strike": strike,
            "ce_oi": int(abs(5000 + i * 1000)),
            "pe_oi": int(abs(4800 + i * 900))
        })

    return spot, chain

# ================= ORB ENGINE =================
def update_orb(symbol, price):
    if symbol not in state["orb"]:
        state["orb"][symbol] = {
            "high": price,
            "low": price,
            "start_time": str(datetime.now())
        }

    orb = state["orb"][symbol]

    now = datetime.now().time()

    # ORB TIME 09:00 - 09:15
    if now >= datetime.strptime("09:00", "%H:%M").time() and now <= datetime.strptime("09:15", "%H:%M").time():
        orb["high"] = max(orb["high"], price)
        orb["low"] = min(orb["low"], price)

    state["orb"][symbol] = orb

# ================= SIGNAL ENGINE =================
def signal_engine(price):

    ema20 = price * 1.001
    ema50 = price * 0.999
    vwap = price * 1.0002

    if ema20 > ema50 and price > vwap:
        return "BUY"
    elif ema20 < ema50 and price < vwap:
        return "SELL"
    return "HOLD"

# ================= DELTA =================
def delta_calc(spot, strike):
    return max(min((spot - strike) / spot * 5, 1), -1)

# ================= FAKE FILTER =================
def fake_filter(delta, ce_oi, pe_oi, side):
    if side == "BUY":
        return not (delta < 0.35 or ce_oi < pe_oi)
    if side == "SELL":
        return not (delta > -0.35 or pe_oi < ce_oi)
    return False

# ================= TRADE QTY =================
def qty(entry, sl):
    risk_amt = CAPITAL * RISK
    return max(int(risk_amt / abs(entry - sl)), 1)

# ================= EXECUTE TRADE =================
def execute_trade(symbol, side, entry, sl, tp):

    trade = {
        "symbol": symbol,
        "side": side,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "qty": qty(entry, sl),
        "status": "OPEN",
        "time": str(datetime.now()),
        "pnl": 0
    }

    state["trades"].append(trade)
    save_state(state)

    tg(f"🚀 {side} {symbol} ENTRY @ {entry}")

# ================= TRAILING SL =================
def trailing():

    for t in state["trades"]:
        if t["status"] != "OPEN":
            continue

        price = dhan_price(t["symbol"])

        pnl = (price - t["entry"]) if t["side"] == "BUY" else (t["entry"] - price)
        t["pnl"] = pnl * t["qty"]

        # SL update
        if t["side"] == "BUY":
            if price > t["entry"] * 1.01:
                t["sl"] = max(t["sl"], price - 10)

        else:
            if price < t["entry"] * 0.99:
                t["sl"] = min(t["sl"], price + 10)

        # EXIT
        if t["side"] == "BUY" and price <= t["sl"]:
            t["status"] = "CLOSED"
            tg(f"❌ EXIT BUY {t['symbol']} PNL {t['pnl']}")

        if t["side"] == "SELL" and price >= t["sl"]:
            t["status"] = "CLOSED"
            tg(f"❌ EXIT SELL {t['symbol']} PNL {t['pnl']}")

# ================= MAIN ENGINE =================
SYMBOLS = ["CRUDEOIL", "NATURALGAS"]

market = []

for s in SYMBOLS:

    price, chain = option_chain(s)

    update_orb(s, price)

    orb = state["orb"][s]

    signal = signal_engine(price)

    ce_oi = sum(x["ce_oi"] for x in chain) / len(chain)
    pe_oi = sum(x["pe_oi"] for x in chain) / len(chain)

    strike = chain[10]["strike"]
    delta = delta_calc(price, strike)

    valid = fake_filter(delta, ce_oi, pe_oi, signal)

    market.append({
        "SYMBOL": s,
        "PRICE": price,
        "SIGNAL": signal,
        "ORB HIGH": orb["high"],
        "ORB LOW": orb["low"],
        "STATUS": "OK" if valid else "FILTERED"
    })

    # ENTRY AFTER ORB
    now = datetime.now().time()
    if now > datetime.strptime("09:15", "%H:%M").time():

        if signal != "HOLD" and valid:

            active = [t for t in state["trades"] if t["status"] == "OPEN"]

            if len(active) == 0:

                sl = price * 0.995 if signal == "BUY" else price * 1.005
                tp = price * 1.01 if signal == "BUY" else price * 0.99

                execute_trade(s, signal, price, sl, tp)

save_state(state)
trailing()

# ================= DASHBOARD =================
st.subheader("📊 LIVE MARKET VIEW")
st.dataframe(pd.DataFrame(market), use_container_width=True)

st.divider()

st.subheader("📈 LIVE + CLOSED TRADES")

df = pd.DataFrame(state["trades"])
st.dataframe(df, use_container_width=True)

st.divider()

st.subheader("💰 PNL SUMMARY")

if len(df) > 0:
    st.metric("Total Trades", len(df))
    st.metric("Open Trades", len(df[df["status"] == "OPEN"]))
    st.metric("Closed Trades", len(df[df["status"] == "CLOSED"]))
    st.metric("Net PnL", round(df["pnl"].sum(), 2))

# ================= AUTO REFRESH =================
time.sleep(3)
st.rerun()
