import streamlit as st
import pandas as pd
import requests
import time
import os
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# ================= 1. CONFIG & ALLOCATION =================
st.set_page_config(layout="wide", page_title="Delta AI Pro Engine")
st.title("🤖 Delta Pro Auto-Execution (History Enabled)")

# Auto refresh every 10 seconds
st_autorefresh(interval=10000, key="refresh")

# Risk & Strategy Settings
TOTAL_CAPITAL = 1000
ALLOCATION = {"BTCUSD": 0.60, "ETHUSD": 0.40}
LEVERAGE = 25
CSV_FILE = "trade_history_v2.csv"

# Secrets (Make sure these are in your .streamlit/secrets.toml)
TELEGRAM_TOKEN = st.secrets.get("TELEGRAM_TOKEN", "")
CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "")
BASE_URL = "https://delta.exchange"

# ================= 2. CORE FUNCTIONS =================
def load_data():
    """CSV se purani trades load karne ke liye"""
    if os.path.exists(CSV_FILE):
        try:
            return pd.read_csv(CSV_FILE).to_dict('records')
        except:
            return []
    return []

def save_data(trades):
    """Trades ko CSV mein permanent save karne ke liye"""
    if trades:
        pd.DataFrame(trades).to_csv(CSV_FILE, index=False)

def send_telegram(msg):
    """Telegram alert function"""
    try:
        if not TELEGRAM_TOKEN or not CHAT_ID: return
        url = f"https://telegram.org{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=5)
    except: pass

def get_candles(symbol, tf="5m"):
    """Market data fetch karne ke liye"""
    try:
        now = int(time.time())
        r = requests.get(f"{BASE_URL}/v2/history/candles",
            params={"symbol": symbol, "resolution": tf, "start": now-86400, "end": now}, timeout=10).json()
        df = pd.DataFrame(r["result"]).sort_values("time")
        for c in ["open","high","low","close","volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.dropna()
    except: return pd.DataFrame()

def detect_fvg(df):
    """Fair Value Gap Detection"""
    if len(df) < 3: return False, False
    bull = df.iloc[-3]["high"] < df.iloc[-1]["low"]
    bear = df.iloc[-3]["low"] > df.iloc[-1].high
    return bull, bear

# ================= 3. SESSION STATE =================
if "trades" not in st.session_state:
    st.session_state.trades = load_data()

# ================= 4. ENGINE & DATA PROCESSING =================
market_watch_data = []

for symbol in ["BTCUSD", "ETHUSD"]:
    df = get_candles(symbol)
    if df.empty: continue

    # Indicators
    df["EMA20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["EMA50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["VWAP"] = (df["close"] * df["volume"]).cumsum() / df["volume"].cumsum()
    
    curr_p = float(df.iloc[-1]["close"])
    ema20 = round(df["EMA20"].iloc[-1], 2)
    ema50 = round(df["EMA50"].iloc[-1], 2)
    vwap = round(df["VWAP"].iloc[-1], 2)
    bull_fvg, bear_fvg = detect_fvg(df)

    # Signal Logic
    signal = "HOLD"
    if curr_p > vwap and ema20 > ema50 and bull_fvg: signal = "BUY"
    elif curr_p < vwap and ema20 < ema50 and bear_fvg: signal = "SELL"

    market_watch_data.append({
        "SYMBOL": symbol, "LIVE PRICE": curr_p, 
        "EMA 20": ema20, "EMA 50": ema50, 
        "VWAP": vwap, "SIGNAL": signal
    })

    # --- TRADING LOGIC ---
    active_t = next((t for t in st.session_state.trades if t["status"] == "OPEN" and t["pair"] == symbol), None)

    if signal in ["BUY", "SELL"] and active_t is None:
        allocated_amt = TOTAL_CAPITAL * ALLOCATION[symbol]
        pos_size = (allocated_amt * LEVERAGE) / curr_p
        target_dist = curr_p * 0.01 
        
        new_trade = {
            "pair": symbol, "side": signal, "entry": curr_p, "qty": round(pos_size, 4),
            "sl": round(curr_p * 0.98 if signal == "BUY" else curr_p * 1.02, 2),
            "target1": round(curr_p + target_dist if signal == "BUY" else curr_p - target_dist, 2),
            "partial_done": False, "status": "OPEN", 
            "time": datetime.now().strftime("%Y-%m-%d %H:%M"), "exit_price": None
        }
        st.session_state.trades.append(new_trade)
        save_data(st.session_state.trades)
        send_telegram(f"🚀 NEW {signal} | {symbol}\nPrice: {curr_p}\nSize: {round(pos_size, 4)}")

    # --- TRADE MANAGEMENT (EXIT & PARTIAL) ---
    for t in st.session_state.trades:
        if t["status"] == "OPEN" and t["pair"] == symbol:
            # Check Partial Target
            if not t["partial_done"]:
                hit = (curr_p >= t["target1"]) if t["side"] == "BUY" else (curr_p <= t["target1"])
                if hit:
                    t["partial_done"] = True
                    t["qty"] = t["qty"] / 2
                    t["sl"] = t["entry"] # SL to Break Even
                    save_data(st.session_state.trades)
                    send_telegram(f"💰 PARTIAL BOOKED {symbol}\nSL moved to Entry.")

            # Check Stop Loss
            sl_hit = (curr_p <= t["sl"]) if t["side"] == "BUY" else (curr_p >= t["sl"])
            if sl_hit:
                t["status"] = "CLOSED"
                t["exit_price"] = curr_p
                save_data(st.session_state.trades)
                send_telegram(f"❌ CLOSED {symbol} @ {curr_p}")

# ================= 5. DASHBOARD UI =================
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("📊 Live Market Watch")
    if market_watch_data:
        st.table(pd.DataFrame(market_watch_data))

with col2:
    st.subheader("⚙️ System Status")
    st.success("Engine is Running...")
    st.info(f"Capital: ${TOTAL_CAPITAL} | Leverage: {LEVERAGE}x")

st.divider()

st.subheader("📋 Master Order Book (History)")
if st.session_state.trades:
    # Reverse display: Latest trades first
    df_history = pd.DataFrame(st.session_state.trades).iloc[::-1]
    st.dataframe(df_history, use_container_width=True)
    
    # Download Button
    csv_data = pd.DataFrame(st.session_state.trades).to_csv(index=False)
    st.download_button("📥 Export History", csv_data, "trade_history.csv", "text/csv")
else:
    st.info("No trades in history. Waiting for signals...")
