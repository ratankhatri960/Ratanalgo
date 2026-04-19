import streamlit as st
import pandas as pd
import time
import os
import json
from datetime import datetime, time as dt_time
from streamlit_autorefresh import st_autorefresh

# ================= CONFIG =================
st.set_page_config(layout="wide", page_title="MCX ORB Pro Engine FINAL")
st.title("🤖 MCX ORB Pro Engine (Stable Final Fix)")

st_autorefresh(interval=5000, key="refresh")

STATE_FILE = "mcx_state.json"

TOTAL_CAPITAL = 10000
RISK = 0.02

# ================= MARKET TIME (FIXED WITH DAY) =================
def is_market_open():
    now = datetime.now()
    current_time = now.time()
    current_day = now.weekday()  # Mon=0 Sun=6

    if current_day >= 5:  # Sat/Sun closed
        return False

    return dt_time(9, 0) <= current_time <= dt_time(23, 30)

# ================= STATE =================
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            return json.load(open(STATE_FILE))
        except:
            return {"positions": [], "orb": {}}
    return {"positions": [], "orb": {}}

def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except:
        pass

state = load_state()

# ================= PRICE (NO FAKE DATA) =================
def get_price(symbol):
    # ❌ No API yet → treat as no data
    return None

# ================= OPTION CHAIN =================
def get_chain(spot):
    if spot is None:
        return []
    return [{"strike": spot + i * 50} for i in range(-5, 6)]

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
            "finalized": False,
            "date": None
        }

    orb = state["orb"][symbol]
    now = datetime.now()
    current_time = now.time()
    today = now.strftime("%Y-%m-%d")

    # ✅ DAILY RESET
    if orb.get("date") != today:
       orb["high"] = None
       orb["low"] = None
       orb["buffer"] = []
       orb["active"] = False
       orb["finalized"] = False
       orb["date"] = today

    if price is None:
        return

    # ORB window
    if dt_time(9, 0) <= current_time <= dt_time(9, 15):
        orb["active"] = True

    # BUILD
    if orb["active"] and not orb["finalized"]:
        orb["buffer"].append(float(price))

        if len(orb["buffer"]) >= 3:
            orb["high"] = max(orb["buffer"])
            orb["low"] = min(orb["buffer"])

    # FREEZE
    if current_time > dt_time(9, 15) and not orb["finalized"]:
        if orb["buffer"]:
            orb["high"] = max(orb["buffer"])
            orb["low"] = min(orb["buffer"])
        orb["active"] = False
        orb["finalized"] = True
        orb["buffer"] = []

    # SAME VALUE FIX
    if orb["high"] is not None and orb["low"] is not None:
        if orb["high"] == orb["low"]:
            orb["high"] += 0.5
            orb["low"] -= 0.5

# ================= ORB BREAKOUT =================
def orb_breakout(symbol, price):
    if price is None:
        return None

    orb = state["orb"][symbol]
    now = datetime.now().time()

    if now <= dt_time(9, 15):
        return None

    if orb["high"] is None or orb["low"] is None:
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

    return (atm, "CE") if signal == "BUY" else (atm, "PE")

# ================= RISK =================
def qty(capital, risk, sl):
    try:
        return max(int((capital * risk) / sl), 1)
    except:
        return 1

# ================= MAIN =================
market_watch = []
symbols = ["CRUDEOIL", "NATURALGAS"]

for symbol in symbols:

    price = get_price(symbol)  # हमेशा None (no fake data)
    chain = get_chain(price)

    update_orb(symbol, price)
    orb = state["orb"].get(symbol, {})

    signal, _ = generate_signal(price)

    orb_signal = orb_breakout(symbol, price)
    if orb_signal:
        signal = orb_signal

    market_watch.append({
        "SYMBOL": symbol,
        "PRICE": "MARKET CLOSED",
        "SIGNAL": signal,
        "ORB HIGH": orb.get("high"),
        "ORB LOW": orb.get("low")
    })

    active = any(p["status"] == "OPEN" and p["symbol"] == symbol for p in state["positions"])

    if price is not None and signal not in ["HOLD", "MARKET CLOSED"] and not active:

        sl = price * (0.995 if signal == "BUY" else 1.005)

        strike, opt_type = select_strike(chain, price, signal)

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

# ================= TRAILING SL =================
for p in state["positions"]:
    if p["status"] == "OPEN":

        curr_price = get_price(p["symbol"])
        if curr_price is None:
            continue

        move = curr_price - p["entry"] if p["side"] == "BUY" else p["entry"] - curr_price

        if move > (p["entry"] * 0.002):

            gap = p["entry"] * 0.002

            if p["side"] == "BUY":
                new_sl = curr_price - gap
                if new_sl > p["sl"]:
                    p["sl"] = round(new_sl, 2)
            else:
                new_sl = curr_price + gap
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

    df_display = df.rename(columns={
        "sl": "Live SL",
        "strike": "Strike",
        "option": "Option"
    })

    st.dataframe(df_display.sort_index(ascending=False), use_container_width=True)
else:
    st.info("No trades yet")
