import streamlit as st
import pandas as pd
import requests
import time
import os
import json
import random
from datetime import datetime, time as dt_time
from streamlit_autorefresh import st_autorefresh

# ================= CONFIG =================
st.set_page_config(layout="wide", page_title="MCX ORB Pro Engine FIXED")
st.title("🤖 MCX ORB Pro Engine (Stable FIX VERSION)")

st_autorefresh(interval=5000, key="refresh")

STATE_FILE = "mcx_state.json"

TOTAL_CAPITAL = 10000
RISK = 0.02

# ================= STATE =================
def load_state():
    if os.path.exists(STATE_FILE):
        return json.load(open(STATE_FILE))
    return {
        "positions": [],
        "orb": {}
    }

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

state = load_state()

# ================= PRICE FEED =================
def get_price(symbol):
    base = {"CRUDEOIL": 6500, "NATURALGAS": 280}[symbol]
    return base + random.randint(-120, 120)

# ================= OPTION CHAIN =================
def get_chain(spot):
    return [
        {"strike": spot + i * 50, "ce_oi": random.randint(1000, 50000), "pe_oi": random.randint(1000, 50000)}
        for i in range(-10, 11)
    ]

# ================= SIGNAL =================
def generate_signal(price):
    ema20 = price * 1.001
    ema50 = price * 0.999
    vwap = price * 1.0001

    if ema20 > ema50 and price > vwap:
        return "BUY", "UP"
    elif ema20 < ema50 and price < vwap:
        return "SELL", "DOWN"
    return "HOLD", None

# ================= ORB FIX =================
def update_orb(symbol, price):

    if "orb" not in state:
        state["orb"] = {}

    if symbol not in state["orb"]:
        state["orb"][symbol] = {
            "high": price,
            "low": price,
            "active": False,
            "buffer": []
        }

    orb = state["orb"][symbol]
    now = datetime.now().time()

    # ORB TIME WINDOW
    if dt_time(9, 0) <= now <= dt_time(9, 15):
        orb["active"] = True

    # BUFFER BUILD
    if orb["active"]:
        orb["buffer"].append(price)

        if len(orb["buffer"]) > 100:
            orb["buffer"].pop(0)

        orb["high"] = max(orb["buffer"])
        orb["low"] = min(orb["buffer"])

    # ✅ FREEZE ORB AFTER 9:15 (ADDED)
    if now > dt_time(9, 15):
        orb["active"] = False

# ================= ORB BREAKOUT CHECK =================
def orb_breakout(symbol, price):
    orb = state["orb"][symbol]
    now = datetime.now().time()

    # ✅ ALLOW BREAKOUT ONLY AFTER ORB WINDOW (ADDED)
    if now <= dt_time(9, 15):
        return None

    if price > orb["high"]:
        return "BUY"
    elif price < orb["low"]:
        return "SELL"

    return None

# ================= STRIKE =================
def select_strike(chain, spot, signal):
    atm = min(chain, key=lambda x: abs(x["strike"] - spot))["strike"]

    if signal == "BUY":
        return atm, "CE"
    else:
        return atm, "PE"

# ================= RISK =================
def qty(capital, risk, sl):
    return max(int((capital * risk) / sl), 1)

# ================= DASHBOARD =================
market_watch = []

symbols = ["CRUDEOIL", "NATURALGAS"]

for symbol in symbols:

    price = get_price(symbol)
    chain = get_chain(price)

    update_orb(symbol, price)
    orb = state["orb"][symbol]

    signal, direction = generate_signal(price)

    # ORB BREAKOUT OVERRIDE
    orb_signal = orb_breakout(symbol, price)
    if orb_signal:
        signal = orb_signal

    market_watch.append({
        "SYMBOL": symbol,
        "PRICE": price,
        "SIGNAL": signal,
        "ORB HIGH": orb["high"],
        "ORB LOW": orb["low"]
    })

    active = any(p["status"] == "OPEN" and p["symbol"] == symbol for p in state["positions"])

    # ✅ COOLDOWN ADD (NO DELETE)
    last_trade = next((p for p in reversed(state["positions"]) if p["symbol"] == symbol), None)

    cooldown_ok = True
    if last_trade:
        last_time = datetime.fromisoformat(last_trade["time"])
        if (datetime.now() - last_time).seconds < 300:
            cooldown_ok = False

    if signal != "HOLD" and not active and cooldown_ok:

        sl = price * (0.995 if signal == "BUY" else 1.005)

        position = {
            "symbol": symbol,
            "side": signal,
            "entry": price,
            "sl": sl,
            "qty": qty(TOTAL_CAPITAL, RISK, abs(price - sl)),
            "status": "OPEN",
            "time": str(datetime.now())
        }

        state["positions"].append(position)
        save_state(state)

# ================= UI =================
st.subheader("📊 Live Market Watch")
st.table(pd.DataFrame(market_watch))

st.divider()

st.subheader("📋 Trades")

if state["positions"]:
    st.dataframe(pd.DataFrame(state["positions"]), use_container_width=True)

st.subheader("📋 Trades")

if state["positions"]:
    df = pd.DataFrame(state["positions"])
    st.dataframe(df, use_container_width=True)

st.subheader("📋 Trades")

if state["positions"]:
    df = pd.DataFrame(state["positions"])
    st.dataframe(df, use_container_width=True)
