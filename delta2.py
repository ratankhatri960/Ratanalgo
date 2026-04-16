import streamlit as st
import pandas as pd
import requests
import time
import os
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# ================= 1. CONFIG & SETTINGS =================
st.set_page_config(layout="wide", page_title="Delta AI Pro Engine")
st.title("🤖 Delta Pro: Fresh Setup & Persistent History")

# Dashboard refresh every 10 seconds
st_autorefresh(interval=10000, key="refresh")

# Risk Settings
TOTAL_CAPITAL = 1000
ALLOCATION = {"BTCUSD": 0.60, "ETHUSD": 0.40}
LEVERAGE = 25
CSV_FILE = "final_trade_history.csv"

# Credentials
TELEGRAM_TOKEN = st.secrets.get("TELEGRAM_TOKEN", "")
CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "")
BASE_URL = "https://api.india.delta.exchange"

# ================= 2. DATA FUNCTIONS =================
def load_data():
    """CSV se purani aur active trades load karna"""
    if os.path.exists(CSV_FILE):
        try:
            df = pd.read_csv(CSV_FILE)
            return df.to_dict('records')
        except:
            return []
    return []

def save_data(trades):
    """Har action par CSV file update karna"""
    if trades:
        pd.DataFrame(trades).to_csv(CSV_FILE, index=False)

def send_telegram(msg):
    """Corrected Telegram URL"""
    try:
        if not TELEGRAM_TOKEN or not CHAT_ID: return
        url = f"https://telegram.org{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=5)
    except: pass

def get_candles(symbol, tf="5m"):
    """Live Market Data Fetching"""
    try:
        now = int(time.time())
        r = requests.get(f"{BASE_URL}/v2/history/candles",
            params={"symbol": symbol, "resolution": tf, "start": now-7200, "end": now}, timeout=10)
        data = r.json()
        if "result" in data:
            df = pd.DataFrame(data["result"]).sort_values("time")
            for c in ["open","high","low","close","volume"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            return df.dropna()
    except:
        return pd.DataFrame()

# ================= 3. SESSION STATE =================
if "trades" not in st.session_state:
    st.session_state.trades = load_data()

# ================= 4. CORE ENGINE =================
market_watch = []

for symbol in ["BTCUSD", "ETHUSD"]:
    df = get_candles(symbol)
    if df.empty or len(df) < 5:
        continue

    # Indicators
    df["EMA20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["EMA50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["VWAP"] = (df["close"] * df["volume"]).cumsum() / df["volume"].cumsum()
    
    curr = df.iloc[-1]   # Current Candle
    prev = df.iloc[-2]   # Previous Candle
    curr_p = float(curr["close"])
    
    # FVG Detection
    bull_fvg = df.iloc[-3]["high"] < df.iloc[-1]["low"]
    bear_fvg = df.iloc[-3]["low"] > df.iloc[-1].high

    # SIGNAL LOGIC
    is_bull = curr_p > curr["VWAP"] and curr["EMA20"] > curr["EMA50"] and bull_fvg
    is_bear = curr_p < curr["VWAP"] and curr["EMA20"] < curr["EMA50"] and bear_fvg
    
    # ⚡ FRESH SETUP CHECK (Pichli candle par setup nahi tha, abhi bana hai)
    was_bull = prev["close"] > prev["VWAP"] and prev["EMA20"] > prev["EMA50"]
    was_bear = prev["close"] < prev["VWAP"] and prev["EMA20"] < prev["EMA50"]

    signal = "HOLD"
    is_fresh_setup = False

    if is_bull:
        signal = "BUY"
        if not was_bull: is_fresh_setup = True
    elif is_bear:
        signal = "SELL"
        if not was_bear: is_fresh_setup = True

    market_watch.append({
        "SYMBOL": symbol, "PRICE": curr_p, 
        "EMA20": round(curr["EMA20"], 2), "SIGNAL": signal,
        "STATUS": "⚡ TRIGGERED" if is_fresh_setup else "HOLD"
    })

    # --- EXECUTION (Only on Fresh Setup) ---
    active_t = next((t for t in st.session_state.trades if t["status"] == "OPEN" and t["pair"] == symbol), None)

    if is_fresh_setup and active_t is None:
        new_trade = {
            "pair": symbol, "side": signal, "entry": curr_p, 
            "qty": round((TOTAL_CAPITAL * ALLOCATION[symbol] * LEVERAGE) / curr_p, 4),
            "sl": round(curr_p * 0.25 if signal == "BUY" else curr_p * 0.25, 2),
            "target1": round(curr_p * 1.025 if signal == "BUY" else curr_p * 0.25, 2),
            "status": "OPEN", "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "exit": None, "partial_done": False
        }
        st.session_state.trades.append(new_trade)
        save_data(st.session_state.trades)
        send_telegram(f"⚡ FRESH {signal} ENTRY | {symbol} @ {curr_p}")

    # --- TRADE MANAGEMENT ---
    for t in st.session_state.trades:
        if t["status"] == "OPEN" and t["pair"] == symbol:
            # 1. Partial Booking (Target 1)
            if not t["partial_done"]:
                hit_t1 = (curr_p >= t["target1"]) if t["side"] == "BUY" else (curr_p <= t["target1"])
                if hit_t1:
                    t["partial_done"], t["qty"], t["sl"] = True, t["qty"]/2, t["entry"]
                    save_data(st.session_state.trades)
                    send_telegram(f"💰 PARTIAL DONE {symbol} | SL to Cost")

            # 2. Stop Loss or Exit
            hit_sl = (curr_p <= t["sl"]) if t["side"] == "BUY" else (curr_p >= t["sl"])
            if hit_sl:
                t["status"], t["exit"] = "CLOSED", curr_p
                save_data(st.session_state.trades)
                send_telegram(f"❌ CLOSED {symbol} @ {curr_p}")

# ================= 5. UI DASHBOARD =================
st.subheader("📊 Live Market Watch")
if market_watch:
    st.table(pd.DataFrame(market_watch))
else:
    st.info("Market data connect ho raha hai...")

st.divider()

st.subheader("📋 Master Order Book (Persistent History)")
if st.session_state.trades:
    # Reverse display: Nayi trades pehle
    df_h = pd.DataFrame(st.session_state.trades)
    st.dataframe(df_h.iloc[::-1], use_container_width=True)
    
    # Download History Button
    csv = df_h.to_csv(index=False).encode('utf-8')
    st.download_button("📥 Download Trade Log", csv, "trading_history.csv", "text/csv")
else:
    st.info("Waiting for first fresh setup...")

st.sidebar.markdown(f"### 🚀 System Status: Active")
st.sidebar.write(f"**Capital:** ${TOTAL_CAPITAL}")
st.sidebar.write(f"**Leverage:** {LEVERAGE}x")

