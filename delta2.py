import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# ================= CONFIG & ALLOCATION =================
st.set_page_config(layout="wide", page_title="Delta AI Pro Engine")
st.title("🤖 Delta Pro Auto-Execution (10x Leverage)")

# Dashboard refresh rate (10 seconds)
st_autorefresh(interval=10000, key="refresh")

# Risk Settings
TOTAL_CAPITAL = 1000
ALLOCATION = {"BTCUSD": 0.60, "ETHUSD": 0.40}
LEVERAGE = 25

TELEGRAM_TOKEN = st.secrets.get("TELEGRAM_TOKEN", "")
CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "")
BASE_URL = "https://api.india.delta.exchange"

# ================= CORE FUNCTIONS =================
def send_telegram(msg):
    try:
        if not TELEGRAM_TOKEN or not CHAT_ID: return
        requests.post(f"https://telegram.org{TELEGRAM_TOKEN}/sendMessage", 
                      data={"chat_id": CHAT_ID, "text": msg}, timeout=5)
    except: pass

def get_candles(symbol, tf="5m"):
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
    if len(df) < 3: return False, False
    bull = df.iloc[-3]["high"] < df.iloc[-1]["low"]
    bear = df.iloc[-3]["low"] > df.iloc[-1].high
    return bull, bear

# ================= SESSION STATE =================
if "trades" not in st.session_state: st.session_state.trades = []

# ================= ENGINE & DATA PROCESSING =================
market_watch_data = []

for symbol in ["BTCUSD", "ETHUSD"]:
    df = get_candles(symbol)
    if df.empty: continue

    # Indicators Calculation
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

    # Add to Market Watch Table
    market_watch_data.append({
        "SYMBOL": symbol,
        "LIVE PRICE": curr_p,
        "EMA 20": ema20,
        "EMA 50": ema50,
        "VWAP": vwap,
        "SIGNAL": signal
    })

    # --- TRADING LOGIC (Auto 10x Leverage + Partial Booking) ---
    active_t = next((t for t in st.session_state.trades if t["status"] == "OPEN" and t["pair"] == symbol), None)

    if signal in ["BUY", "SELL"] and active_t is None:
        allocated_amt = TOTAL_CAPITAL * ALLOCATION[symbol]
        pos_size = (allocated_amt * LEVERAGE) / curr_p
        
        target_dist = curr_p * 0.01 # 1% Target for Partial
        
        new_trade = {
            "pair": symbol, "side": signal, "entry": curr_p, "qty": round(pos_size, 4),
            "sl": curr_p * 0.98 if signal == "BUY" else curr_p * 1.02,
            "target1": round(curr_p + target_dist if signal == "BUY" else curr_p - target_dist, 2),
            "partial_done": False, "status": "OPEN", "time": datetime.now().strftime("%H:%M")
        }
        st.session_state.trades.append(new_trade)
        send_telegram(f"🚀 AUTO {signal} | {symbol}\nSize: {round(pos_size, 4)} units (10x)\nEntry: {curr_p}")

    # Trade Management
    for t in st.session_state.trades:
        if t["status"] == "OPEN" and t["pair"] == symbol:
            if not t["partial_done"]:
                hit = (curr_p >= t["target1"]) if t["side"] == "BUY" else (curr_p <= t["target1"])
                if hit:
                    t["partial_done"] = True
                    t["qty"] = t["qty"] / 2
                    t["sl"] = t["entry"]
                    send_telegram(f"💰 PARTIAL BOOKED {symbol}\n50% sold. SL at Cost.")

            # Stop Loss / Exit Check
            sl_hit = (curr_p <= t["sl"]) if t["side"] == "BUY" else (curr_p >= t["sl"])
            if sl_hit:
                t["status"], t["exit"] = "CLOSED", curr_p
                send_telegram(f"❌ EXIT {symbol} @ {curr_p}")

# ================= DASHBOARD UI =================
st.subheader("📊 Live Market Watch")
if market_watch_data:
    st.table(pd.DataFrame(market_watch_data)) # Table for Live Data

st.divider()

st.subheader("📋 Master Order Book (Active & History)")
if st.session_state.trades:
    st.dataframe(pd.DataFrame(st.session_state.trades), use_container_width=True)
else:
    st.info("Searching for signals in BTC & ETH...")
