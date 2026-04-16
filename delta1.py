import streamlit as st
import pandas as pd
import requests
import time
import os
from datetime import datetime, time as dt_time
from streamlit_autorefresh import st_autorefresh

# ================= 1. CONFIG =================
st.set_page_config(layout="wide", page_title="Delta Midnight Pro")
st.title("🤖 Delta AI: Midnight ORB + EMA + VWAP")

st_autorefresh(interval=10000, key="refresh")

TOTAL_CAPITAL = 1000
LEVERAGE = 25
CSV_FILE = "midnight_pro_history.csv"
BASE_URL = "https://api.india.delta.exchange"

# ================= 2. DATA FUNCTIONS =================
def load_data():
    if os.path.exists(CSV_FILE):
        try: return pd.read_csv(CSV_FILE).to_dict('records')
        except: return []
    return []

def save_data(trades):
    if trades: pd.DataFrame(trades).to_csv(CSV_FILE, index=False)

def get_candles(symbol, tf="5m"):
    try:
        now = int(time.time())
        # Fetching 24h data to ensure we cover the midnight range
        r = requests.get(f"{BASE_URL}/v2/history/candles",
            params={"symbol": symbol, "resolution": tf, "start": now-100000, "end": now}, timeout=10).json()
        df = pd.DataFrame(r["result"]).sort_values("time")
        # Convert to IST
        df["time_ist"] = pd.to_datetime(df["time"], unit='s') + pd.Timedelta(hours=5, minutes=30)
        for c in ["open","high","low","close","volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.dropna()
    except: return pd.DataFrame()

# ================= 3. STATE =================
if "trades" not in st.session_state:
    st.session_state.trades = load_data()

# ================= 4. ENGINE LOGIC =================
market_watch = []

for symbol in ["BTCUSD", "ETHUSD"]:
    df = get_candles(symbol, "5m")
    if df.empty: continue

    # A. Indicators
    df["EMA20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["EMA50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["VWAP"] = (df["close"] * df["volume"]).cumsum() / df["volume"].cumsum()

    # B. Midnight Range (23:30 - 00:30 IST)
    range_df = df[((df['time_ist'].dt.time >= dt_time(23, 30)) | (df['time_ist'].dt.time <= dt_time(0, 30)))]
    
    orb_high = range_df["high"].max() if not range_df.empty else 0
    orb_low = range_df["low"].min() if not range_df.empty else 0

    # C. Current Data
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    curr_p = float(curr["close"])
    vwap_val = round(curr["VWAP"], 2)
    ema20, ema50 = curr["EMA20"], curr["EMA50"]

    # D. Signal Logic
    signal = "WAITING"
    entry_now = False

    # BULLISH: Price > ORB High AND Price > VWAP AND EMA20 > EMA50
    if orb_high > 0 and curr_p > orb_high and curr_p > vwap_val and ema20 > ema50:
        signal = "BULLISH BREAKOUT"
        if prev["close"] <= orb_high: entry_now = True
        
    # BEARISH: Price < ORB Low AND Price < VWAP AND EMA20 < EMA50
    elif orb_low > 0 and curr_p < orb_low and curr_p < vwap_val and ema20 < ema50:
        signal = "BEARISH BREAKOUT"
        if prev["close"] >= orb_low: entry_now = True

    market_watch.append({
        "SYMBOL": symbol, "PRICE": curr_p, 
        "ORB HIGH": orb_high, "ORB LOW": orb_low,
        "VWAP": vwap_val, "SIGNAL": signal
    })

    # E. Execution
    active_t = next((t for t in st.session_state.trades if t["status"] == "OPEN" and t["pair"] == symbol), None)

    if entry_now and active_t is None:
        side = "LONG" if signal == "BULLISH BREAKOUT" else "SHORT"
        new_trade = {
            "pair": symbol, "side": side, "entry": curr_p, 
            "qty": round((TOTAL_CAPITAL * 0.5 * LEVERAGE) / curr_p, 4),
            "sl": orb_low if side == "LONG" else orb_high, # SL at range boundary
            "target": round(curr_p * 1.01 if side == "LONG" else curr_p * 0.99, 2),
            "status": "OPEN", "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "exit": None
        }
        st.session_state.trades.append(new_trade)
        save_data(st.session_state.trades)

    # F. Management
    for t in st.session_state.trades:
        if t["status"] == "OPEN" and t["pair"] == symbol:
            if (t["side"] == "LONG" and curr_p >= t["target"]) or (t["side"] == "SHORT" and curr_p <= t["target"]):
                t["status"], t["exit"] = "CLOSED (TARGET)", curr_p
                save_data(st.session_state.trades)
            elif (t["side"] == "LONG" and curr_p <= t["sl"]) or (t["side"] == "SHORT" and curr_p >= t["sl"]):
                t["status"], t["exit"] = "CLOSED (SL)", curr_p
                save_data(st.session_state.trades)

# ================= 5. UI =================
st.subheader("📊 Midnight ORB + EMA + VWAP Live Feed")
st.table(pd.DataFrame(market_watch))

st.divider()

st.subheader("📋 Trade History & Order Book")
if st.session_state.trades:
    st.dataframe(pd.DataFrame(st.session_state.trades).iloc[::-1], use_container_width=True)
else:
    st.info("No trades executed yet. Waiting for breakout + indicator confirmation...")
