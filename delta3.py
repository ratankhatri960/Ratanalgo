import streamlit as st
import pandas as pd
import requests
import time
import os
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# ================= 1. CONFIG =================
st.set_page_config(layout="wide", page_title="Delta AI Pro: Date & Time Tracker")
st.title("🚀 Delta AI Pro: Volume Profile + Delta Flow (with History)")

CSV_FILE = "poc_delta_history_dated.csv"
st_autorefresh(interval=10000, key="refresh")

TOTAL_CAPITAL = 1000
BASE_URL = "https://delta.exchange"
SL_VAL_PCT = 0.005
T1_VAL_PCT = 0.005
COOLDOWN_MIN = 15

# ================= 2. STATE MANAGEMENT =================
if "trades" not in st.session_state:
    if os.path.exists(CSV_FILE):
        try: st.session_state.trades = pd.read_csv(CSV_FILE).to_dict('records')
        except: st.session_state.trades = []
    else: st.session_state.trades = []

if "last_candle" not in st.session_state: st.session_state.last_candle = {}
if "last_entry" not in st.session_state: st.session_state.last_entry = {}

# ================= 3. CORE FUNCTIONS =================
def save_data():
    if st.session_state.trades:
        pd.DataFrame(st.session_state.trades).to_csv(CSV_FILE, index=False)

def get_candles(symbol, tf="5m"):
    try:
        now = int(time.time())
        r = requests.get(f"{BASE_URL}/v2/history/candles", 
                         params={"symbol": symbol, "resolution": tf, "start": now-86400, "end": now}, timeout=10).json()
        df = pd.DataFrame(r["result"]).sort_values("time")
        for c in ["open","high","low","close","volume"]: df[c] = pd.to_numeric(df[c])
        return df.dropna()
    except: return pd.DataFrame()

def calculate_poc(df):
    if df.empty: return 0
    df['price_bin'] = df['close'].round(2)
    return df.groupby('price_bin')['volume'].sum().idxmax()

# ================= 4. ENGINE LOGIC =================
market_watch = []
for symbol in ["BTCUSD", "ETHUSD"]:
    df = get_candles(symbol, "5m")
    trend_df = get_candles(symbol, "15m")
    if df.empty or trend_df.empty: continue

    # Indicators
    df['vwap'] = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()
    df["delta"] = df["volume"].where(df["close"] > df["open"], -df["volume"])
    
    curr_p = float(df.iloc[-1]["close"])
    vwap_val = round(df.iloc[-1]["vwap"], 2)
    delta_flow = df["delta"].tail(5).sum()
    poc_val = calculate_poc(df.tail(20))
    
    # Trend Check (15m)
    trend_df["ema20"] = trend_df["close"].ewm(span=20).mean()
    trend_df["ema50"] = trend_df["close"].ewm(span=50).mean()
    bullish = trend_df.iloc[-1]["ema20"] > trend_df.iloc[-1]["ema50"]

    # --- SIGNAL ---
    signal = "HOLD"
    if bullish and curr_p > vwap_val and curr_p > poc_val and delta_flow > 0:
        signal = "LONG"
    elif not bullish and curr_p < vwap_val and curr_p < poc_val and delta_flow < 0:
        signal = "SHORT"

    market_watch.append({"Symbol": symbol, "Price": curr_p, "POC": poc_val, "Delta": delta_flow, "Signal": signal})

    # --- EXECUTION ---
    active = next((t for t in st.session_state.trades if t["pair"] == symbol and t["status"] == "OPEN"), None)
    cooldown_ok = (time.time() - st.session_state.last_entry.get(symbol, 0)) > (COOLDOWN_MIN * 60)
    
    if signal != "HOLD" and active is None and cooldown_ok and st.session_state.last_candle.get(symbol) != df.iloc[-1]['time']:
        sl = curr_p * (1 - SL_VAL_PCT) if signal == "LONG" else curr_p * (1 + SL_VAL_PCT)
        t1 = curr_p * (1 + T1_VAL_PCT) if signal == "LONG" else curr_p * (1 - T1_VAL_PCT)
        
        st.session_state.trades.append({
            "pair": symbol, "side": signal, "entry": curr_p, "sl": round(sl, 2), "target": round(t1, 2),
            "status": "OPEN", "pnl": 0.0, 
            "entry_t": datetime.now().strftime("%d/%m %H:%M:%S"), # Date + Time
            "exit_t": "-", "partial": False
        })
        st.session_state.last_candle[symbol] = df.iloc[-1]['time']
        st.session_state.last_entry[symbol] = time.time()
        save_data()

    # --- LIVE MGMT ---
    for t in st.session_state.trades:
        if t["status"] == "OPEN" and t["pair"] == symbol:
            move = (curr_p - t["entry"]) if t["side"] == "LONG" else (t["entry"] - curr_p)
            t["pnl"] = round(move * 10, 2)
            
            # T1 Hit
            if not t["partial"] and (curr_p >= t["target"] if t["side"] == "LONG" else curr_p <= t["target"]):
                t["partial"], t["sl"] = True, t["entry"]
                save_data()

            # Exit Check
            if (curr_p <= t["sl"] if t["side"] == "LONG" else curr_p >= t["sl"]):
                t["status"] = "CLOSED"
                t["exit_t"] = datetime.now().strftime("%d/%m %H:%M:%S") # Date + Time
                save_data()

# ================= 5. DASHBOARD UI =================
st.subheader("🔥 Live Sentiment Scan")
st.table(pd.DataFrame(market_watch))

st.subheader("📋 Trade History & Management")
if st.session_state.trades:
    df_show = pd.DataFrame(st.session_state.trades).rename(columns={
        "pair": "Symbol", "side": "Side", "entry": "Entry", "sl": "SL (Live)",
        "target": "Target", "pnl": "PnL", "entry_t": "Entry T", "exit_t": "Exit T"
    })
    
    def get_action(row):
        if row["status"] == "CLOSED": return "🔴 Closed"
        return "✅ T1 Hit (Safe)" if row["partial"] else "🟢 Running"

    df_show["Action"] = df_show.apply(get_action, axis=1)
    
    # Display columns in the requested order
    cols = ["Symbol", "Side", "Entry", "SL (Live)", "Target", "PnL", "Entry T", "Exit T", "Action"]
    st.dataframe(df_show[cols].sort_index(ascending=False), use_container_width=True)
    else:
    st.info("Scanning market for the next high-probability setup...")

    # FIXED DOWNLOAD BUTTON POSITION #
    csv_data = pd.DataFrame(st.session_state.trades).to_csv(index=False).encode('utf-8')
    st.download_button(label="📥 Download Trade History", data=csv_data, file_name="trading_log.csv", mime="text/csv")
else:
    st.info("Scanning market for signals...")
