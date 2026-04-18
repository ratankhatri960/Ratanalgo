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
st.set_page_config(layout="wide", page_title="MCX ORB Pro Engine")
st.title("🤖 MCX ORB Pro: Clean Production System")

st_autorefresh(interval=5000, key="refresh")

STATE_FILE = "mcx_state.json"
BASE_URL = "https://api.india.delta.exchange"

TOTAL_CAPITAL = 10000
RISK = 0.02

SL_PCT = 0.005
T1_PCT = 0.01

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

# ================= LIVE PRICE (SIM / REPLACE WITH DHAN) =================
def get_price(symbol):
    base = {"CRUDEOIL": 6500, "NATURALGAS": 280}[symbol]
    return base + random.randint(-50, 50)

# ================= OPTION CHAIN =================
def get_chain(spot):
    return [
        {"strike": spot + i * 50, "ce_oi": random.randint(1000, 50000), "pe_oi": random.randint(1000, 50000)}
        for i in range(-10, 11)
    ]

# ================= INDICATORS =================
def generate_signal(price):
    ema20 = price * 1.001
    ema50 = price * 0.999
    vwap = price * 1.0001

    bull = ema20 > ema50 and price > vwap
    bear = ema20 < ema50 and price < vwap

    if bull:
        return "BUY", "UP"
    elif bear:
        return "SELL", "DOWN"
    return "HOLD", None

# ================= ORB FIXED ENGINE =================
def update_orb(symbol, price):
    if symbol not in state["orb"]:
        state["orb"][symbol] = {
            "high": price,
            "low": price,
            "active": False
        }

    orb = state["orb"][symbol]

    now = datetime.now().time()
    if dt_time(9, 0) <= now <= dt_time(9, 15):
        orb["active"] = True

    if orb["active"]:
        orb["high"] = max(orb["high"], price)
        orb["low"] = min(orb["low"], price)

# ================= DELTA =================
def calc_delta(spot, strike):
    return max(min((spot - strike) / spot * 5, 1), -1)

# ================= STRIKE SELECTION =================
def select_strike(chain, spot, signal, delta):
    atm = min(chain, key=lambda x: abs(x["strike"] - spot))["strike"]

    if signal == "BUY":
        if delta > 0.6:
            return atm + 50, "CE"
        elif delta > 0.3:
            return atm, "CE"
        else:
            return atm - 50, "CE"
    else:
        if delta < -0.6:
            return atm - 50, "PE"
        elif delta < -0.3:
            return atm, "PE"
        else:
            return atm + 50, "PE"

# ================= FAKE FILTER =================
def fake_filter(delta, ce_oi, pe_oi, direction):
    if direction == "UP" and (delta < 0.3 or ce_oi < pe_oi):
        return False
    if direction == "DOWN" and (delta > -0.3 or pe_oi < ce_oi):
        return False
    return True

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

    delta = calc_delta(price, chain[0]["strike"])

    ce_oi = sum(x["ce_oi"] for x in chain) / len(chain)
    pe_oi = sum(x["pe_oi"] for x in chain) / len(chain)

    strike, opt = select_strike(chain, price, signal, delta)

    valid = fake_filter(delta, ce_oi, pe_oi, direction)

    market_watch.append({
        "SYMBOL": symbol,
        "PRICE": price,
        "SIGNAL": signal,
        "ORB HIGH": orb["high"],
        "ORB LOW": orb["low"]
    })

    active = any(p["status"] == "OPEN" and p["symbol"] == symbol for p in state["positions"])

    if signal != "HOLD" and valid and not active:

        sl = price * (0.995 if signal == "BUY" else 1.005)
        tp = price * (1.01 if signal == "BUY" else 0.99)

        position = {
            "symbol": symbol,
            "side": signal,
            "entry": price,
            "strike": strike,
            "type": opt,
            "sl": sl,
            "tp": tp,
            "qty": qty(TOTAL_CAPITAL, RISK, abs(price - sl)),
            "status": "OPEN",
            "time": str(datetime.now())
        }

        state["positions"].append(position)
        save_state(state)

# ================= UI =================
st.subheader("📊 Live Market")
st.table(pd.DataFrame(market_watch))

st.divider()

st.subheader("📋 Trades")

if state["positions"]:
    df = pd.DataFrame(state["positions"])
    st.dataframe(df, use_container_width=True)
