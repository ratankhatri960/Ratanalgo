import streamlit as st
import pandas as pd
import requests
import time
import os
from datetime import datetime, time as dt_time
from streamlit_autorefresh import st_autorefresh

# ================= 1. CONFIG =================
st.set_page_config(layout="wide", page_title="Delta Midnight Pro")
st.title("🤖 Midnight ORB: Candle Closing Logic")

st_autorefresh(interval=5000, key="refresh") 

TOTAL_CAPITAL = 1000
LEVERAGE = 25
CSV_FILE = "midnight_closing_history.csv"
BASE_URL = "https://api.india.delta.exchange"

# --- TARGET & SL SETTINGS ---
SL_PCT = 0.005        
T1_PCT = 0.005        
SECURE_PCT = 0.00025  

# ================= 2. FUNCTIONS =================
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
        r = requests.get(f"{BASE_URL}/v2/history/candles",
            params={"symbol": symbol, "resolution": tf, "start": now-108000, "end": now}, timeout=10).json()
        if "result" not in r: return pd.DataFrame()
        df = pd.DataFrame(r["result"]).sort_values("time")
        df["time_ist"] = pd.to_datetime(df["time"], unit='s') + pd.Timedelta(hours=5, minutes=30)
        for c in ["open","high","low","close","volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.dropna()
    except: return pd.DataFrame()

# ================= 3. STATE =================
if "trades" not in st.session_state:
    st.session_state.trades = load_data()

# ================= 4. ENGINE =================
market_watch = []

for symbol in ["BTCUSD", "ETHUSD"]:
    df = get_candles(symbol, "5m")
    if df.empty or len(df) < 2: continue

    # --- Indicators ---
df["EMA20"] = df["close"].ewm(span=20, adjust=False).mean()
df["EMA50"] = df["close"].ewm(span=50, adjust=False).mean()

# --- VWAP Calculation ---
df['date'] = df['time_ist'].dt.date
df['cum_vol'] = df.groupby('date')['volume'].cumsum()
df['cum_vol_price'] = (df['close'] * df['volume']).groupby(df['date']).cumsum()
df['VWAP'] = df['cum_vol_price'] / df['cum_vol']

# --- Midnight Range (23:30 - 00:30 IST) ---
today = df['time_ist'].dt.date.iloc[-1]

# Filter for the specific time window
range_df = df[
    (df['time_ist'].dt.date == today) & 
    ((df['time_ist'].dt.time >= dt_time(23, 30)) | 
     (df['time_ist'].dt.time <= dt_time(0, 30)))
]

# Calculate ORB High/Low
orb_high = range_df["high"].max() if not range_df.empty else 0
orb_low = range_df["low"].min() if not range_df.empty else 0

curr = df.iloc[-1]   # Running Candle (Live)
last = df.iloc[-2]   # Completed Candle (To check closing)
    
curr_p = float(curr["close"])
last_close = float(last["close"])
vwap_val = round(curr["VWAP"], 2)
    
# SIGNAL CHECK (Based on LAST candle closing)
signal = "WAITING"
if orb_high > 0 and last_close > orb_high and curr_p > vwap_val and curr["EMA20"] > curr["EMA50"]:
    signal = "BULLISH BREAKOUT"
elif orb_low > 0 and last_close < orb_low and curr_p < vwap_val and curr["EMA20"] < curr["EMA50"]:
    signal = "BEARISH BREAKOUT"

    market_watch.append({
        "SYMBOL": symbol, "PRICE": curr_p, 
        "LAST CLOSE": last_close, "ORB HIGH": orb_high, 
        "ORB LOW": orb_low, "SIGNAL": signal
    })

    # EXECUTION
    active_t = next((t for t in st.session_state.trades if t["status"] == "OPEN" and t["pair"] == symbol), None)

    if signal != "WAITING" and active_t is None:
        side = "LONG" if signal == "BULLISH BREAKOUT" else "SHORT"
        qty = round((TOTAL_CAPITAL * 0.5 * LEVERAGE) / curr_p, 4)
        
        new_trade = {
            "pair": symbol, "side": side, "entry": curr_p, "qty": qty,
            "sl": round(curr_p * (1 - SL_PCT) if side == "LONG" else curr_p * (1 + SL_PCT), 2),
            "target1": round(curr_p * (1 + T1_PCT) if side == "LONG" else curr_p * (1 - T1_PCT), 2),
            "partial_done": False, "status": "OPEN", "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "pnl": 0.0
        }
        st.session_state.trades.append(new_trade)
        save_data(st.session_state.trades)

    # MANAGEMENT
    for t in st.session_state.trades:
        if t["status"] == "OPEN" and t["pair"] == symbol:
            pnl_move = (curr_p - t["entry"]) if t["side"] == "LONG" else (t["entry"] - curr_p)
            t["pnl"] = round(pnl_move * t["qty"], 2)

            if not t["partial_done"]:
                hit_t1 = (curr_p >= t["target1"]) if t["side"] == "LONG" else (curr_p <= t["target1"])
                if hit_t1:
                    t["partial_done"] = True
                    t["qty"] = t["qty"] / 2 
                    secure_price = t["entry"] * (1 + SECURE_PCT) if t["side"] == "LONG" else t["entry"] * (1 - SECURE_PCT)
                    t["sl"] = round(secure_price, 2)
                    save_data(st.session_state.trades)

            hit_exit = (curr_p <= t["sl"]) if t["side"] == "LONG" else (curr_p >= t["sl"])
            if hit_exit:
                t["status"], t["exit"] = "CLOSED", curr_p
                save_data(st.session_state.trades)

# ================= 5. UI =================
st.subheader("📊 Midnight ORB Live Watch (Closing Basis)")
st.table(pd.DataFrame(market_watch))
st.divider()
st.subheader("📋 Order Book")
if st.session_state.trades:
    st.dataframe(pd.DataFrame(st.session_state.trades).iloc[::-1], use_container_width=True)
