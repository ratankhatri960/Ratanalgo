import streamlit as st
import pandas as pd
import requests
import time
import os
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# ================= 1. CONFIGURATION =================
st.set_page_config(layout="wide", page_title="Delta AI Pro Engine")
st.title("🤖 Delta Pro Auto-Execution Engine")

# Auto-refresh dashboard every 10 seconds
st_autorefresh(interval=10000, key="refresh")

# Strategy Parameters
TOTAL_CAPITAL = 1000
ALLOCATION = {"BTCUSD": 0.60, "ETHUSD": 0.40}
LEVERAGE = 25
CSV_FILE = "trading_history_v3.csv"

# Telegram Secrets
TELEGRAM_TOKEN = st.secrets.get("TELEGRAM_TOKEN", "")
CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "")
BASE_URL = "https://delta.exchange"

# ================= 2. CORE FUNCTIONS =================
def load_history():
    """CSV file se data load karne ke liye"""
    if os.path.exists(CSV_FILE):
        try:
            return pd.read_csv(CSV_FILE).to_dict('records')
        except:
            return []
    return []

def save_history(trades):
    """Data ko CSV mein save karne ke liye"""
    if trades:
        pd.DataFrame(trades).to_csv(CSV_FILE, index=False)

def send_telegram(msg):
    """Telegram alert notifications"""
    try:
        if not TELEGRAM_TOKEN or not CHAT_ID: return
        url = f"https://telegram.org{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=5)
    except:
        pass

def get_candles(symbol, tf="5m"):
    """Live market data fetch karne ke liye"""
    try:
        now = int(time.time())
        # Sirf last 1 hour ka data fetch kar rahe hain for speed
        r = requests.get(f"{BASE_URL}/v2/history/candles",
            params={"symbol": symbol, "resolution": tf, "start": now-3600, "end": now}, timeout=10)
        data = r.json()
        if "result" in data:
            df = pd.DataFrame(data["result"]).sort_values("time")
            for c in ["open","high","low","close","volume"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            return df.dropna()
    except Exception as e:
        st.error(f"Data Connection Error for {symbol}")
    return pd.DataFrame()

def detect_fvg(df):
    """Fair Value Gap Check"""
    if len(df) < 3: return False, False
    bull = df.iloc[-3]["high"] < df.iloc[-1]["low"]
    bear = df.iloc[-3]["low"] > df.iloc[-1].high
    return bull, bear

# ================= 3. SESSION STATE =================
if "trades" not in st.session_state:
    st.session_state.trades = load_history()

# ================= 4. MAIN ENGINE =================
market_watch_list = []

for symbol in ["BTCUSD", "ETHUSD"]:
    df = get_candles(symbol)
    
    if df.empty:
        st.warning(f"Connecting to {symbol} feed...")
        continue

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
    if curr_p > vwap and ema20 > ema50 and bull_fvg:
        signal = "BUY"
    elif curr_p < vwap and ema20 < ema50 and bear_fvg:
        signal = "SELL"

    market_watch_list.append({
        "SYMBOL": symbol,
        "PRICE": curr_p,
        "EMA20": ema20,
        "EMA50": ema50,
        "VWAP": vwap,
        "SIGNAL": signal
    })

    # Trade Execution Logic
    active_t = next((t for t in st.session_state.trades if t["status"] == "OPEN" and t["pair"] == symbol), None)

    if signal in ["BUY", "SELL"] and active_t is None:
        allocated_amt = TOTAL_CAPITAL * ALLOCATION[symbol]
        pos_size = (allocated_amt * LEVERAGE) / curr_p
        
        new_trade = {
            "pair": symbol, "side": signal, "entry": curr_p, "qty": round(pos_size, 4),
            "sl": round(curr_p * 0.98 if signal == "BUY" else curr_p * 1.02, 2),
            "target1": round(curr_p * 1.01 if signal == "BUY" else curr_p * 0.99, 2),
            "status": "OPEN", "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "exit_price": None, "partial_done": False
        }
        st.session_state.trades.append(new_trade)
        save_history(st.session_state.trades)
        send_telegram(f"🚀 AUTO {signal} | {symbol}\nEntry: {curr_p}\nSize: {round(pos_size, 4)}")

    # Trade Management (Exit & Partial)
    for t in st.session_state.trades:
        if t["status"] == "OPEN" and t["pair"] == symbol:
            # 1. Partial Booking
            if not t["partial_done"]:
                hit = (curr_p >= t["target1"]) if t["side"] == "BUY" else (curr_p <= t["target1"])
                if hit:
                    t["partial_done"] = True
                    t["qty"] = t["qty"] / 2
                    t["sl"] = t["entry"] # Trail SL to entry
                    save_history(st.session_state.trades)
                    send_telegram(f"💰 PARTIAL {symbol} | SL moved to Break-even")

            # 2. Final Exit (SL or Target)
            sl_hit = (curr_p <= t["sl"]) if t["side"] == "BUY" else (curr_p >= t["sl"])
            if sl_hit:
                t["status"] = "CLOSED"
                t["exit_price"] = curr_p
                save_history(st.session_state.trades)
                send_telegram(f"❌ CLOSED {symbol} @ {curr_p}")

# ================= 5. DASHBOARD UI =================

# Market Watch Table
st.subheader("📊 Live Market Watch")
if market_watch_list:
    st.table(pd.DataFrame(market_watch_list))
else:
    st.info("Searching for live data...")

st.divider()

# Trade History Dataframe
st.subheader("📋 Master Order Book & History")
if st.session_state.trades:
    # Reverse display to show latest first
    df_history = pd.DataFrame(st.session_state.trades).iloc[::-1]
    st.dataframe(df_history, use_container_width=True)
    
    # Download Link
    csv_file = pd.DataFrame(st.session_state.trades).to_csv(index=False)
    st.download_button("📥 Download History (CSV)", csv_file, "trades_data.csv", "text/csv")
else:
    st.info("No trade history available yet.")

st.sidebar.markdown("### ⚙️ Engine Settings")
st.sidebar.write(f"**Capital:** ${TOTAL_CAPITAL}")
st.sidebar.write(f"**Leverage:** {LEVERAGE}x")
st.sidebar.write(f"**Refresh:** 10 Seconds")

