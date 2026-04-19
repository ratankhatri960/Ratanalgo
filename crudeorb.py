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
st.set_page_config(layout="wide", page_title="MCX ORB Pro Engine FINAL")
st.title("🤖 MCX ORB Pro Engine (Final Stable Version)")

st_autorefresh(interval=5000, key="refresh")

STATE_FILE = "mcx_state.json"

TOTAL_CAPITAL = 10000
RISK = 0.02

# ================= MARKET TIME =================
def is_market_open():
    now = datetime.now().time()
    return dt_time(9, 0) <= now <= dt_time(23, 30)

# ================= STATE =================
def load_state():
    if os.path.exists(STATE_FILE):
        return json.load(open(STATE_FILE))
    return {"positions": [], "orb": {}}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

state = load_state()

# ================= PRICE FEED =================
def get_price(symbol):
    if not is_market_open():
        return None
    base = {"CRUDEOIL": 6500, "NATURALGAS": 280}[symbol]
    return base + random.randint(-50, 50)

# ================= OPTION CHAIN =================
def get_chain(spot):
    if spot is None:
        return []
    return [
        {"strike": spot + i * 50, "ce_oi": random.randint(1000, 50000), "pe_oi": random.randint(1000, 50000)}
        for i in range(-10, 11)
    ]

# ================= SIGNAL =================
def generate_signal(price):
    if price is None:
        return "MARKET CLOSED", None

    ema20 = price * 1.001
    ema50 = price * 0.999
    vwap = price * 1.0001

    if ema20 > ema50 and price > vwap:
        return "BUY", "UP"
    elif ema20 < ema50 and price < vwap:
        return "SELL", "DOWN"
    return "HOLD", None

# ================= ORB =================
def update_orb(symbol, price):

    if symbol not in state["orb"]:
        state["orb"][symbol] = {
            "high": None,
            "low": None,
            "buffer": [],
            "active": False,
            "finalized": False
        }

    orb = state["orb"][symbol]
    now = datetime.now().time()

    if price is None:
        return

    if dt_time(9, 0) <= now <= dt_time(9, 15):
        orb["active"] = True

    if orb["active"] and not orb["finalized"]:
        orb["buffer"].append(price)
        orb["high"] = max(orb["buffer"])
        orb["low"] = min(orb["buffer"])

    if now > dt_time(9, 15) and not orb["finalized"]:
        if orb["buffer"]:
            orb["high"] = max(orb["buffer"])
            orb["low"] = min(orb["buffer"])
        orb["active"] = False
        orb["finalized"] = True
        orb["buffer"] = []

    if orb["high"] is None:
        orb["high"] = price
    if orb["low"] is None:
        orb["low"] = price

# ================= ORB BREAKOUT =================
def orb_breakout(symbol, price):
    if price is None:
        return None

    orb = state["orb"][symbol]
    now = datetime.now().time()

    if now <= dt_time(9, 15):
        return None

    if price > orb["high"]:
        return "BUY"
    elif price < orb["low"]:
        return "SELL"

    return None

# ================= STRIKE =================
def select_strike(chain, spot, signal):
    if not chain:
        return None, None

    atm = min(chain, key=lambda x: abs(x["strike"] - spot))["strike"]

    if signal == "BUY":
        return atm, "CE"
    else:
        return atm, "PE"

# ================= RISK =================
def qty(capital, risk, sl):
    return max(int((capital * risk) / sl), 1)

# ================= MAIN =================
market_watch = []
symbols = ["CRUDEOIL", "NATURALGAS"]

for symbol in symbols:

    price = get_price(symbol)
    chain = get_chain(price)

    update_orb(symbol, price)
    orb = state["orb"].get(symbol, {})

    signal, direction = generate_signal(price)

    orb_signal = orb_breakout(symbol, price)
    if orb_signal:
        signal = orb_signal

    strike, opt_type = select_strike(chain, price, signal)

    market_watch.append({
        "SYMBOL": symbol,
        "PRICE": price if price else "MARKET CLOSED",
        "SIGNAL": signal,
        "ORB HIGH": orb.get("high"),
        "ORB LOW": orb.get("low"),
        "STRIKE": strike,
        "TYPE": opt_type
    })

    active = any(p["status"] == "OPEN" and p["symbol"] == symbol for p in state["positions"])

    last_trade = next((p for p in reversed(state["positions"]) if p["symbol"] == symbol), None)
    cooldown_ok = True
    if last_trade:
        last_time = datetime.fromisoformat(last_trade["time"])
        if (datetime.now() - last_time).seconds < 300:
            cooldown_ok = False

    if price is not None and signal not in ["HOLD", "MARKET CLOSED"] and not active and cooldown_ok:

        sl = price * (0.995 if signal == "BUY" else 1.005)

        position = {
            "symbol": symbol,
            "side": signal,
            "entry": price,
            "sl": sl,
            "qty": qty(TOTAL_CAPITAL, RISK, abs(price - sl)),
            "status": "OPEN",
            "time": str(datetime.now()),
            "strike": strike,
            "option": opt_type
        }

        state["positions"].append(position)
        save_state(state)

# ================= TRAILING SL ENGINE (ADDED) =================
for p in state["positions"]:
    if p["status"] == "OPEN":

        curr_price = get_price(p["symbol"])
        if curr_price is None:
            continue

        move = curr_price - p["entry"] if p["side"] == "BUY" else p["entry"] - curr_price

        if move > (p["entry"] * 0.002):

            trail_gap = p["entry"] * 0.002

            if p["side"] == "BUY":
                new_sl = curr_price - trail_gap
                if new_sl > p["sl"]:
                    p["sl"] = round(new_sl, 2)

            elif p["side"] == "SELL":
                new_sl = curr_price + trail_gap
                if new_sl < p["sl"]:
                    p["sl"] = round(new_sl, 2)

save_state(state)

# ================= UI =================
st.subheader("📊 Live Market Watch")
st.table(pd.DataFrame(market_watch))

st.divider()

st.subheader("📋 Trades")

if state["positions"]:
    df = pd.DataFrame(state["positions"])

    # ✅ LIVE SL DISPLAY
    df_display = df.rename(columns={"sl": "Live SL"})

    st.dataframe(df_display.sort_index(ascending=False), use_container_width=True)
else:
    st.info("No trades yet")
