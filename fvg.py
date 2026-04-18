import streamlit as st
import pandas as pd
import requests
import os
import numpy as np
import math
from datetime import datetime

st.set_page_config(layout="wide", page_title="Institutional Smart Money Bot")
st.title("🔥 Institutional Options Bot (EMA + VWAP + FVG + Delta + OI)")

# ================= SESSION =================
session = requests.Session()
headers = {"User-Agent": "Mozilla/5.0"}
session.get("https://www.nseindia.com", headers=headers)

# ================= CONFIG =================
INDEX_LIST = ["NIFTY", "BANKNIFTY", "SENSEX"]
scanner_results = [] # Initialize outside to prevent NameError

# ================= SPOT (replace with broker API later) =================
def get_spot(symbol):
    return {
        "NIFTY": 22500,
        "BANKNIFTY": 48000,
        "SENSEX": 74500
    }[symbol]

# ================= OPTION CHAIN =================
def get_chain(symbol):
    try:
        url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
        r = session.get(url, headers=headers, timeout=10)
        return r.json()
    except:
        return None

# ================= DELTA (NO SCIPY) =================
def calc_delta(S, K, T=0.02, r=0.06, sigma=0.2, opt="CE"):
    d1 = (math.log(S/K) + (r + sigma**2/2)*T) / (sigma * math.sqrt(T))
    nd1 = 0.5 * (1 + math.erf(d1 / math.sqrt(2)))
    return nd1 if opt == "CE" else nd1 - 1

# ================= PARSE OPTION CHAIN =================
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

# ================= FAKE BREAKOUT FILTER =================
def fake_filter(delta, ce_oi, pe_oi, direction):

    if direction == "UP":
        if delta < 0.45:
            return False
        if ce_oi < pe_oi:
            return False

    if direction == "DOWN":
        if delta > -0.45:
            return False
        if pe_oi < ce_oi:
            return False

    return True

# ================= STRIKE SELECTION =================
def select_strike(df, spot, signal):
    atm = df.loc[df["dist"].idxmin()]["strike"]

    if signal == "BUY":
        strike = atm
        opt = "CE"
    else:
        strike = atm
        opt = "PE"

    return int(strike), opt

# ================= MAIN ENGINE =================
results = []

for symbol in INDEX_LIST:

    data = get_chain(symbol)
    if not data:
        continue

    spot = get_spot(symbol)
    df, atm = parse_chain(data, spot)

    # ================= EMA / VWAP / FVG (SIMPLIFIED MOCK LOGIC) =================
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

    # ================= SIGNAL =================
    signal = "NO TRADE"
    direction = None

    if trend_bull and price > VWAP and bull_fvg:
        signal = "BUY"
        direction = "UP"

    elif trend_bear and price < VWAP and bear_fvg:
        signal = "SELL"
        direction = "DOWN"

    # ================= STRIKE + DELTA =================
    strike, opt = select_strike(df, spot, signal)

    delta = calc_delta(spot, strike, opt=opt)

    ce_oi = atm["ce_oi"]
    pe_oi = atm["pe_oi"]

    # ================= FINAL FILTER =================
    valid = False

    if direction:
        valid = fake_filter(delta, ce_oi, pe_oi, direction)

    status = "❌ REJECTED"

    if valid and signal != "NO TRADE":
        status = "🔥 VALID TRADE"

    results.append({
        "Index": symbol,
        "Spot": spot,
        "Signal": signal,
        "Strike": strike,
        "Type": opt,
        "Delta": round(delta, 2),
        "CE OI": ce_oi,
        "PE OI": pe_oi,
        "Status": status
    })

# ================= 4. DASHBOARD UI =================

# --- SCANNER SECTION ---
st.subheader("📊 Institutional Option Scanner (ATM)")

# Safety Check: Agar scanner_results empty hai toh empty dataframe dikhao
if scanner_results:
    scan_df = pd.DataFrame(scanner_results)
    
    def style_status(v):
        if not isinstance(v, str): return ''
        return 'color: green; font-weight: bold' if 'VALID' in v else 'color: red'
    
    st.table(scan_df.style.applymap(style_status, subset=['Status']))
else:
    st.warning("⚠️ NSE Data not available. Retrying in next cycle...")
    # Ek empty table headers ke saath dikhane ke liye
    st.table(pd.DataFrame(columns=["Index", "Spot", "Signal", "Status", "Time"]))

st.divider()

# --- ORDER BOOK SECTION ---
st.subheader("📋 Active & Closed Option Trades")
if "trades" in st.session_state and st.session_state.trades:

    # Try to load from CSV, otherwise start with empty list
    if os.path.exists(CSV_FILE):
        try:
            st.session_state.trades = pd.read_csv(CSV_FILE).to_dict('records')
        except:
            st.session_state.trades = []
    else:
        st.session_state.trades = []

    # Custom Header
    cols = st.columns([1, 0.8, 1, 1, 1, 1, 1.5, 1.5, 1])
    h_labels = ["**Index**", "**Type**", "**Strike**", "**Entry LTP**", "**Live LTP**", "**PnL (Pts)**", "**Entry Date/T**", "**Exit Date/T**", "**Action**"]
    for col, lab in zip(cols, h_labels): col.write(lab)

    for i, t in enumerate(st.session_state.trades):
        row = st.columns([1, 0.8, 1, 1, 1, 1, 1.5, 1.5, 1])
        row.write(t["Index"])
        row.write(t["Type"])
        row.write(str(t["Strike"]))
        row.write(str(t["Entry_LTP"]))
        row.write(str(t["Current_LTP"]))
        
        pnl = t["PnL"]
        row.write(f":{'green' if pnl >= 0 else 'red'}[{pnl}]")
        
        row.write(t["Entry_Time"])
        row.write(t["Exit_Time"])

        if t["Status"] == "OPEN":
            if row.button("Manual Exit", key=f"ex_{i}"):
                t["Status"] = "CLOSED"
                t["Exit_Time"] = datetime.now().strftime("%d/%m %H:%M:%S")
                save_trades(st.session_state.trades)
                st.rerun()
        else:
            row.write("✅ Closed")
else:
    st.info("Searching for Institutional signals...")

# --- SIDEBAR TOOLS ---
st.sidebar.header("Settings")
if st.sidebar.button("🗑️ Clear Trade History"):
    if os.path.exists(CSV_FILE):
        os.remove(CSV_FILE)
    st.session_state.trades = []
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.write(f"Last API Refresh: {datetime.now().strftime('%H:%M:%S')}")
