import streamlit as st
import pandas as pd
import requests
import os
import numpy as np
import math
import time
from datetime import datetime

st.set_page_config(layout="wide", page_title="Institutional Smart Money Bot")
st.title("🔥 Institutional Options Bot (EMA + VWAP + FVG + Delta + OI)")

# ================= SESSION =================
session = requests.Session()
headers = {"User-Agent": "Mozilla/5.0"}

def init_session():
    try:
        session.get("https://www.nseindia.com", headers=headers, timeout=5)
    except:
        pass

init_session()

# ================= CONFIG =================
INDEX_LIST = ["NIFTY", "BANKNIFTY", "SENSEX"]
scanner_results = []
CSV_FILE = "option_trades.csv"

# ================= STATE =================
if "trades" not in st.session_state:
    if os.path.exists(CSV_FILE):
        try:
            st.session_state.trades = pd.read_csv(CSV_FILE).to_dict('records')
        except:
            st.session_state.trades = []
    else:
        st.session_state.trades = []

def save_trades(data):
    pd.DataFrame(data).to_csv(CSV_FILE, index=False)

# ================= SPOT =================
def get_spot(symbol):
    return {
        "NIFTY": 22500,
        "BANKNIFTY": 48000,
        "SENSEX": 74500
    }[symbol]

# ================= OPTION CHAIN =================
def get_chain(symbol):
    url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"

    for _ in range(3):
        try:
            r = session.get(url, headers=headers, timeout=5)
            if r.status_code == 200:
                return r.json()
            else:
                init_session()
                time.sleep(1)
        except:
            init_session()
            time.sleep(1)

    return None

# ================= DELTA =================
def calc_delta(S, K, T=0.02, r=0.06, sigma=0.2, opt="CE"):
    d1 = (math.log(S/K) + (r + sigma**2/2)*T) / (sigma * math.sqrt(T))
    nd1 = 0.5 * (1 + math.erf(d1 / math.sqrt(2)))
    return nd1 if opt == "CE" else nd1 - 1

# ================= PARSE =================
def parse_chain(data, spot):
    rows = []

    for d in data["records"]["data"]:
        if "strikePrice" not in d:
            continue

        ce = d.get("CE", {})
        pe = d.get("PE", {})

        rows.append({
            "strike": d["strikePrice"],
            "ce_oi": ce.get("openInterest", 0),
            "pe_oi": pe.get("openInterest", 0),
        })

    df = pd.DataFrame(rows)
    df["dist"] = abs(df["strike"] - spot)
    atm = df.loc[df["dist"].idxmin()]

    return df, atm

# ================= FILTER =================
def fake_filter(delta, ce_oi, pe_oi, direction):

    if direction == "UP":
        if delta < 0.45 or ce_oi < pe_oi:
            return False

    if direction == "DOWN":
        if delta > -0.45 or pe_oi < ce_oi:
            return False

    return True

# ================= STRIKE =================
def select_strike(df, spot, signal):
    atm = df.loc[df["dist"].idxmin()]["strike"]
    return int(atm), ("CE" if signal == "BUY" else "PE")

# ================= ENGINE =================
for symbol in INDEX_LIST:

    data = get_chain(symbol)
    if not data:
        continue

    spot = get_spot(symbol)
    df, atm = parse_chain(data, spot)

    # MOCK LOGIC
    EMA20 = spot * 1.001
    EMA50 = spot * 0.999
    VWAP = spot * 1.0005

    prev_high = spot * 0.999
    next_low = spot * 1.001

    bull_fvg = prev_high < next_low
    bear_fvg = prev_high > next_low

    trend_bull = EMA20 > EMA50
    trend_bear = EMA20 < EMA50

    price = spot

    signal = "NO TRADE"
    direction = None

    if trend_bull and price > VWAP and bull_fvg:
        signal = "BUY"
        direction = "UP"

    elif trend_bear and price < VWAP and bear_fvg:
        signal = "SELL"
        direction = "DOWN"

    strike, opt = select_strike(df, spot, signal)
    delta = calc_delta(spot, strike, opt=opt)

    ce_oi = atm["ce_oi"]
    pe_oi = atm["pe_oi"]

    valid = fake_filter(delta, ce_oi, pe_oi, direction) if direction else False

    status = "❌ REJECTED"
    if valid and signal != "NO TRADE":
        status = "🔥 VALID TRADE"

        # ===== AUTO PAPER TRADE =====
        active = any(t["Index"] == symbol and t["Status"] == "OPEN" for t in st.session_state.trades)

        if not active:
            st.session_state.trades.append({
                "Index": symbol,
                "Type": opt,
                "Strike": strike,
                "Entry_LTP": spot,
                "Current_LTP": spot,
                "PnL": 0,
                "Entry_Time": datetime.now().strftime("%d/%m %H:%M:%S"),
                "Exit_Time": "-",
                "Status": "OPEN"
            })
            save_trades(st.session_state.trades)

    scanner_results.append({
        "Index": symbol,
        "Spot": spot,
        "Signal": signal,
        "Status": status,
        "Time": datetime.now().strftime("%H:%M:%S")
    })

# ================= LIVE PNL UPDATE =================
for t in st.session_state.trades:
    if t["Status"] == "OPEN":
        spot = get_spot(t["Index"])
        t["Current_LTP"] = spot

        move = (spot - t["Entry_LTP"]) if t["Type"] == "CE" else (t["Entry_LTP"] - spot)
        t["PnL"] = round(move, 2)

save_trades(st.session_state.trades)

# ================= UI =================
st.subheader("📊 Institutional Option Scanner (ATM)")

scan_df = pd.DataFrame(scanner_results)

def style_status(v):
    return 'color: green; font-weight: bold' if 'VALID' in str(v) else 'color: red'

st.table(scan_df.style.applymap(style_status, subset=['Status']))

st.divider()

st.subheader("📋 Active & Closed Option Trades")

if st.session_state.trades:

    df = pd.DataFrame(st.session_state.trades)

    st.dataframe(df.sort_index(ascending=False), use_container_width=True)

else:
    st.info("Searching for Institutional signals...")

# ================= SIDEBAR =================
st.sidebar.header("Settings")

if st.sidebar.button("🗑️ Clear Trade History"):
    if os.path.exists(CSV_FILE):
        os.remove(CSV_FILE)
    st.session_state.trades = []
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.write(f"Last API Refresh: {datetime.now().strftime('%H:%M:%S')}")
