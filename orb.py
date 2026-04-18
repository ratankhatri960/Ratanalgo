import streamlit as st
import requests
import pandas as pd
import numpy as np
from datetime import datetime
from scipy.stats import norm
import time

st.set_page_config(page_title="Smart Options Scanner", layout="wide")
st.title("🔥 NSE Smart Money Options Scanner (ORB + Delta + OI)")

# ================= SESSION =================
session = requests.Session()

headers = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "en-US,en;q=0.9",
}

session.get("https://www.nseindia.com", headers=headers)

# ================= CONFIG =================
INDEX_MAP = {
    "NIFTY": "NIFTY",
    "BANKNIFTY": "BANKNIFTY",
    "SENSEX": "SENSEX"
}
scanner_results = [] # Initialize outside to prevent NameError

# ================= NSE DATA =================
def get_option_chain(symbol):
    try:
        url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
        r = session.get(url, headers=headers, timeout=10)
        return r.json()
    except:
        return None


# ================= DELTA MODEL =================
def calc_delta(S, K, T=0.02, r=0.06, sigma=0.2, opt_type="CE"):
    d1 = (np.log(S/K) + (r + sigma**2/2)*T) / (sigma*np.sqrt(T))
    if opt_type == "CE":
        return norm.cdf(d1)
    else:
        return norm.cdf(d1) - 1


# ================= PARSE CHAIN =================
def parse_chain(data, spot):
    rows = []

    for d in data["records"]["data"]:
        if "strikePrice" not in d:
            continue

        strike = d["strikePrice"]
        ce = d.get("CE", {})
        pe = d.get("PE", {})

        rows.append({
            "strike": strike,
            "ce_oi": ce.get("openInterest", 0),
            "pe_oi": pe.get("openInterest", 0),
            "ce_vol": ce.get("totalTradedVolume", 0),
            "pe_vol": pe.get("totalTradedVolume", 0),
        })

    df = pd.DataFrame(rows)

    df["distance"] = abs(df["strike"] - spot)
    atm = df.loc[df["distance"].idxmin()]

    return df, atm


# ================= AUTO STRIKE =================
def select_strike(df, spot, signal, expiry=False):

    atm = df.loc[df["distance"].idxmin()]["strike"]

    if signal == "BULLISH":
        if expiry:
            strike = atm - 100
        else:
            strike = atm
        opt = "CE"

    elif signal == "BEARISH":
        if expiry:
            strike = atm + 100
        else:
            strike = atm
        opt = "PE"

    return int(strike), opt


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


# ================= INDEX PRICE (approx placeholder) =================
def get_spot(symbol):
    # NOTE: Replace with broker API for real accuracy
    fake_prices = {
        "NIFTY": 22500,
        "BANKNIFTY": 48000,
        "SENSEX": 74500
    }
    return fake_prices[symbol]


# ================= UI =================
col1, col2 = st.columns(2)

results = []

for symbol in INDEX_MAP.keys():

    data = get_option_chain(symbol)
    if not data:
        continue

    spot = get_spot(symbol)
    df, atm = parse_chain(data, spot)

    # bullish/bearish detection (simple ORB placeholder logic)
    direction = "UP" if np.random.rand() > 0.5 else "DOWN"

    strike, opt_type = select_strike(df, spot, "BULLISH" if direction=="UP" else "BEARISH")

    delta = calc_delta(spot, strike, opt_type=opt_type)

    ce_oi = atm["ce_oi"]
    pe_oi = atm["pe_oi"]

    valid = fake_filter(delta, ce_oi, pe_oi, direction)

    signal = "NO TRADE"

    if valid:
        signal = f"{symbol} BUY {strike} {opt_type}"

    results.append({
        "Index": symbol,
        "Spot": spot,
        "Signal": signal,
        "Strike": strike,
        "Type": opt_type,
        "Delta": round(delta, 2),
        "CE OI": ce_oi,
        "PE OI": pe_oi
    })

df_out = pd.DataFrame(results)

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
