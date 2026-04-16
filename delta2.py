import streamlit as st
import pandas as pd
import requests
import time
import os
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# ================= 1. CONFIG & SETTINGS =================
st.set_page_config(layout="wide", page_title="Delta AI Pro Engine")
st.title("🤖 Delta Pro: Fresh Setup + Live P&L")

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
    if os.path.exists(CSV_FILE):
        try:
            df = pd.read_csv(CSV_FILE)
            return df.to_dict('records')
        except: return []
    return []

def save_data(trades):
    if trades:
        pd.DataFrame(trades).to_csv(CSV_FILE, index=False)

def send_telegram(msg):
    try:
        if not TELEGRAM_TOKEN or not CHAT_ID: return
        # Fix: Proper Telegram URL
        url = f"https://telegram.org{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=5)
    except: pass

def get_candles(symbol, tf="5m"):
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
    except: return pd.DataFrame()

# ================= 3. SESSION STATE =================
if "trades" not in st.session_state:
    st.session_state.trades = load_data()

# ================= 4. CORE ENGINE =================
market_watch = []

for symbol in ["BTCUSD", "ETHUSD"]:
    df = get_candles(symbol)
    if df.empty or len(df) < 5: continue

    # Indicators
    df["EMA20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["EMA50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["VWAP"] = (df["close"] * df["volume"]).cumsum() / df["volume"].cumsum()
    
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    curr_p = float(curr["close"])
    vwap_val = round(curr["VWAP"], 2)
    
    # FVG Detection
    bull_fvg = df.iloc[-3]["high"] < df.iloc[-1]["low"]
    bear_fvg = df.iloc[-3]["low"] > df.iloc[-1].high

    # SIGNAL LOGIC
    is_bull = curr_p > vwap_val and curr["EMA20"] > curr["EMA50"] and bull_fvg
    is_bear = curr_p < vwap_val and curr["EMA20"] < curr["EMA50"] and bear_fvg
    
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
        "SYMBOL": symbol, "PRICE": curr_p, "VWAP": vwap_val,
        "EMA20": round(curr["EMA20"], 2), "SIGNAL": signal,
        "STATUS": "⚡ TRIGGERED" if is_fresh_setup else "WAITING"
    })

    # --- EXECUTION ---
    active_t = next((t for t in st.session_state.trades if t["status"] == "OPEN" and t["pair"] == symbol), None)

    if is_fresh_setup and active_t is None:
        new_trade = {
            "pair": symbol, "side": signal, "entry": curr_p, 
            "qty": round((TOTAL_CAPITAL * ALLOCATION[symbol] * LEVERAGE) / curr_p, 4),
            "sl": round(curr_p * 0.995 if signal == "BUY" else curr_p * 1.005, 2), # 1.5% SL
            "target1": round(curr_p * 1.005 if signal == "BUY" else curr_p * 0.995, 2), # 1% Target
            "status": "OPEN", "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "exit": None, "partial_done": False, "pnl": 0.0
        }
        st.session_state.trades.append(new_trade)
        save_data(st.session_state.trades)
        send_telegram(f"🚀 {signal} {symbol} @ {curr_p}")

    # --- TRADE MANAGEMENT & LIVE P&L ---
    for t in st.session_state.trades:
        if t["status"] == "OPEN" and t["pair"] == symbol:
            # Live P&L Calculation
            pnl_move = (curr_p - t["entry"]) if t["side"] == "BUY" else (t["entry"] - curr_p)
            t["pnl"] = round(pnl_move * t["qty"], 2)

            # Partial Booking
            if not t["partial_done"]:
                hit_t1 = (curr_p >= t["target1"]) if t["side"] == "BUY" else (curr_p <= t["target1"])
                if hit_t1:
                    t["partial_done"], t["qty"], t["sl"] = True, t["qty"]/2, t["entry"]
                    save_data(st.session_state.trades)
                    send_telegram(f"💰 PARTIAL {symbol} | SL to Cost")

            # Exit
            hit_sl = (curr_p <= t["sl"]) if t["side"] == "BUY" else (curr_p >= t["sl"])
            if hit_sl:
                t["status"], t["exit"] = "CLOSED", curr_p
                save_data(st.session_state.trades)
                send_telegram(f"❌ EXIT {symbol} @ {curr_p}")

# ================= 5. UI DASHBOARD =================
st.subheader("📊 Live Market Watch")
st.table(pd.DataFrame(market_watch))

st.divider()

st.subheader("📋 Master Order Book (With Live P&L)")
if st.session_state.trades:
    df_h = pd.DataFrame(st.session_state.trades).iloc[::-1]
    
    # Display Metrics
    total_pnl = round(sum(t['pnl'] for t in st.session_state.trades), 2)
    st.metric("Total P&L (USD)", f"${total_pnl}", delta=total_pnl)
    
    st.dataframe(df_h, use_container_width=True)
    st.download_button("📥 Download Trade Log", df_h.to_csv(index=False), "trading_history.csv", "text/csv")
else:
    st.info("Searching for fresh setups...")

