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

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive"
}

def init_session():
    try:
        session.get("https://www.nseindia.com", headers=headers, timeout=5)
    except:
        pass

init_session()

# ================= CONFIG =================
INDEX_LIST = ["NIFTY", "BANKNIFTY", "SENSEX"]
scanner_results = []

# ================= REAL SPOT =================
def get_spot(symbol):
    try:
        url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
        r = session.get(url, headers=headers, timeout=5).json()
        return r["records"]["underlyingValue"]
    except:
        return None

# ================= OPTION CHAIN =================
def get_chain(symbol):
    url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"

    for i in range(5):
        try:
            r = session.get(url, headers=headers, timeout=10)

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
    try:
        d1 = (math.log(S/K) + (r + sigma**2/2)*T) / (sigma * math.sqrt(T))
        nd1 = 0.5 * (1 + math.erf(d1 / math.sqrt(2)))
        return nd1 if opt == "CE" else nd1 - 1
    except:
        return 0

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

    if df.empty:
        return df, None

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

    if signal == "BUY":
        return int(atm), "CE"
    else:
        return int(atm), "PE"

# ================= ENGINE =================
results = []

for symbol in INDEX_LIST:

    data = get_chain(symbol)

    if not data:
        st.warning(f"{symbol} data not fetched ❌")
        continue
    else:
        st.success(f"{symbol} data received ✅")

    spot = get_spot(symbol)

    if spot is None:
        st.warning(f"{symbol} spot not available ❌")
        continue

    df, atm = parse_chain(data, spot)

    if df.empty or atm is None:
        continue

    # ================= INDICATORS =================
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

    strike, opt = select_strike(df, spot, signal)

    delta = calc_delta(spot, strike, opt=opt)

    ce_oi = atm["ce_oi"]
    pe_oi = atm["pe_oi"]

    valid = False
    if direction:
        valid = fake_filter(delta, ce_oi, pe_oi, direction)

    status = "❌ REJECTED"
    if valid and signal != "NO TRADE":
        status = "🔥 VALID TRADE"

    scanner_results.append({
        "Index": symbol,
        "Spot": round(spot, 2),
        "Signal": signal,
        "Strike": strike,
        "Type": opt,
        "Delta": round(delta, 2),
        "CE OI": ce_oi,
        "PE OI": pe_oi,
        "Status": status,
        "Time": datetime.now().strftime("%H:%M:%S")
    })

# ================= UI =================
st.subheader("📊 Institutional Option Scanner (ATM)")

if scanner_results:
    scan_df = pd.DataFrame(scanner_results)

    # SAFE STATUS FORMAT (NO STYLE ERROR)
    scan_df["Status"] = scan_df["Status"].apply(
        lambda x: "🟢 VALID" if "VALID" in str(x) else "🔴 REJECTED"
    )

    st.dataframe(scan_df, use_container_width=True)

else:
    st.warning("⚠️ NSE Data not available. Retrying...")

st.divider()

st.subheader("📋 Active & Closed Option Trades")

if "trades" in st.session_state and st.session_state.trades:
    df = pd.DataFrame(st.session_state.trades)
    st.dataframe(df, use_container_width=True)
else:
    st.info("Searching for Institutional signals...")

st.sidebar.header("Settings")

if st.sidebar.button("🗑️ Clear Trade History"):
    st.session_state.trades = []
    st.rerun()

st.sidebar.write(f"Last API Refresh: {datetime.now().strftime('%H:%M:%S')}")
