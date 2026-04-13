import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime, time as dt_time
from streamlit_autorefresh import st_autorefresh

# ================= CONFIG & RISK =================
st.set_page_config(layout="wide", page_title="Delta Pro Auto-Bot")
st_autorefresh(interval=10000, key="refresh")

BASE_URL = "https://api.india.delta.exchange"
SYMBOLS = ["BTCUSD", "ETHUSD"]
TOTAL_CAPITAL = 1000  # Total $1000
ALLOCATION = {"BTCUSD": 0.60, "ETHUSD": 0.40} # 60% BTC, 40% ETH
LEVERAGE = 10

TELEGRAM_TOKEN = st.secrets.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "")

# ================= SESSION INIT =================
if "trades" not in st.session_state: st.session_state.trades = []
if "orb" not in st.session_state: st.session_state.orb = {}

# ================= UTILS =================
def send_telegram(msg):
    try:
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
        url = f"https://telegram.org{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=5)
    except: pass

def get_candles(symbol, tf="5m"):
    try:
        now = int(time.time())
        r = requests.get(f"{BASE_URL}/v2/history/candles",
            params={"symbol": symbol, "resolution": tf, "start": now-86400, "end": now}, timeout=10).json()
        if "result" not in r: return pd.DataFrame()
        df = pd.DataFrame(r["result"]).sort_values("time")
        for c in ["open","high","low","close","volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.dropna()
    except: return pd.DataFrame()

def ema(series, n):
    return series.ewm(span=n, adjust=False).mean()

# ================= ENGINE LOGIC =================
market_watch = []

for symbol in SYMBOLS:
    df = get_candles(symbol)
    if df.empty: continue

    # Indicators
    df["ema9"] = ema(df["close"], 9)
    df["ema21"] = ema(df["close"], 21)
    
    # ORB Calculation
    df["dt"] = pd.to_datetime(df["time"], unit="s") + pd.Timedelta(hours=5, minutes=30)
    df["t"] = df["dt"].dt.time
    orb_df = df[(df["t"] >= dt_time(23,30)) | (df["t"] <= dt_time(0,30))]
    
    orb_high = float(orb_df["high"].max()) if not orb_df.empty else 0
    orb_low = float(orb_df["low"].min()) if not orb_df.empty else 0
    st.session_state.orb[symbol] = {"high": orb_high, "low": orb_low}

    curr_p = float(df.iloc[-1]["close"])
    e9 = round(df["ema9"].iloc[-1], 2)
    e21 = round(df["ema21"].iloc[-1], 2)
    prev_e9, prev_e21 = df["ema9"].iloc[-2], df["ema21"].iloc[-2]

    # Signal Generation (EMA Crossover + ORB Filter)
    signal = "HOLD"
    if prev_e9 < prev_e21 and e9 > e21 and curr_p > orb_high: signal = "LONG"
    elif prev_e9 > prev_e21 and e9 < e21 and curr_p < orb_low: signal = "SHORT"

    market_watch.append({
        "SYMBOL": symbol, "PRICE": curr_p, "EMA 9": e9, "EMA 21": e21,
        "ORB HIGH": orb_high, "ORB LOW": orb_low, "SIGNAL": signal
    })

    # --- EXECUTION ---
    active_t = next((t for t in st.session_state.trades if t["status"] == "OPEN" and t["pair"] == symbol), None)

    if signal in ["LONG", "SHORT"] and active_t is None:
        amt = TOTAL_CAPITAL * ALLOCATION[symbol]
        qty = (amt * LEVERAGE) / curr_p
        
        target_move = curr_p * 0.01 # 1% Price move for 10% Profit (at 10x)
        
        new_trade = {
            "pair": symbol, "side": signal, "entry": curr_p, "qty": round(qty, 4),
            "sl": curr_p * 0.98 if signal == "LONG" else curr_p * 1.02,
            "target_partial": curr_p + target_move if signal == "LONG" else curr_p - target_move,
            "partial_done": False, "status": "OPEN", "time": datetime.now().strftime("%H:%M:%S")
        }
        st.session_state.trades.append(new_trade)
        send_telegram(f"🚀 AUTO {signal} | {symbol}\nQty: {round(qty,4)} (10x)\nEntry: {curr_p}")

    # --- MANAGEMENT (Partial Booking & Trailing) ---
    for t in st.session_state.trades:
        if t["status"] == "OPEN" and t["pair"] == symbol:
            # Partial Booking at 1% Move
            if not t["partial_done"]:
                hit = (curr_p >= t["target_partial"]) if t["side"] == "LONG" else (curr_p <= t["target_partial"])
                if hit:
                    t["partial_done"] = True
                    t["qty"] = t["qty"] / 2
                    t["sl"] = t["entry"] # Move SL to Break-even
                    send_telegram(f"💰 PARTIAL BOOKED {symbol}\n50% closed. SL moved to Entry.")

            # Stop Loss Check
            sl_hit = (curr_p <= t["sl"]) if t["side"] == "LONG" else (curr_p >= t["sl"])
            if sl_hit:
                t["status"], t["exit"] = "CLOSED", curr_p
                send_telegram(f"❌ EXIT {symbol} @ {curr_p}")

# ================= DASHBOARD UI =================
st.title("🤖 Delta Pro Auto-Algo (10x Leverage)")

st.subheader("📊 Live Market Watch")
st.table(pd.DataFrame(market_watch))

st.divider()

col1, col2 = st.columns(2)
with col1:
    st.subheader("📊 Active Positions")
    active_df = pd.DataFrame([t for t in st.session_state.trades if t["status"] == "OPEN"])
    st.dataframe(active_df, use_container_width=True) if not active_df.empty else st.info("No active trades")

with col2:
    st.subheader("📒 Trade History")
    history_df = pd.DataFrame([t for t in st.session_state.trades if t["status"] == "CLOSED"])
    st.dataframe(history_df, use_container_width=True) if not history_df.empty else st.info("History empty")
