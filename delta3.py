import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# ================= CONFIG & RISK =================
st.set_page_config(layout="wide", page_title="Delta AI Pro Bot")
st.title("🤖 Delta AI Pro: Volume & Delta Engine")

# Auto-refresh every 5 seconds
st_autorefresh(interval=5000, key="refresh")

# Global Settings
TOTAL_CAPITAL = 1000
ALLOCATION = {"BTCUSD": 0.60, "ETHUSD": 0.40}
LEVERAGE = 25
BASE_URL = "https://api.india.delta.exchange"

# Secrets for Telegram
TELEGRAM_TOKEN = st.secrets.get("TELEGRAM_TOKEN", "")
CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "")

# ================= FUNCTIONS =================
def send_telegram(msg):
    try:
        if not TELEGRAM_TOKEN or not CHAT_ID: return
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=5)
    except: pass

def get_candles(symbol, tf="5m"):
    try:
        now = int(time.time())
        r = requests.get(f"{BASE_URL}/v2/history/candles",
            params={"symbol": symbol, "resolution": tf, "start": now-86400, "end": now},
            timeout=10).json()
        if "result" not in r: return pd.DataFrame()
        df = pd.DataFrame(r["result"]).sort_values("time")
        for c in ["open","high","low","close","volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.dropna()
    except: return pd.DataFrame()

# ================= SESSION STATE =================
if "trades" not in st.session_state: st.session_state.trades = []

# ================= MAIN ENGINE =================
symbols = ["BTCUSD", "ETHUSD"]
market_data = []

for symbol in symbols:
    df = get_candles(symbol, "5m")
    trend_df = get_candles(symbol, "15m")
    
    if df.empty or trend_df.empty: continue

    # INDICATORS & DELTA
    df["vwap"] = (df["close"] * df["volume"]).cumsum() / df["volume"].cumsum()
    df["delta"] = df.apply(lambda x: x["volume"] if x["close"] > x["open"] else -x["volume"], axis=1)
    
    current_price = float(df.iloc[-1]["close"])
    total_delta = df["delta"].tail(5).sum()
    vwap_val = round(df["vwap"].iloc[-1], 2)
    
    # VOLUME PROFILE (POC)
    vol_prof = df.groupby(pd.cut(df["close"], bins=15))["volume"].sum()
    poc_range = vol_prof.idxmax()
    poc = round((poc_range.left + poc_range.right) / 2, 2)

    # 15M TREND
    trend_df["ema20"] = trend_df["close"].ewm(span=20).mean()
    trend_df["ema50"] = trend_df["close"].ewm(span=50).mean()
    bullish = trend_df.iloc[-1]["ema20"] > trend_df.iloc[-1]["ema50"]

    # SIGNAL
    signal = "HOLD"
    if bullish and current_price > vwap_val and total_delta > 0: signal = "LONG"
    elif not bullish and current_price < vwap_val and total_delta < 0: signal = "SHORT"

    market_data.append({
        "SYMBOL": symbol, "PRICE": current_price, "VWAP": vwap_val,
        "POC": poc, "DELTA (5m)": total_delta, "SIGNAL": signal
    })

    # AUTO TRADE EXECUTION
    active_t = next((t for t in st.session_state.trades if t["pair"] == symbol and t["status"] == "OPEN"), None)

    if signal in ["LONG", "SHORT"] and active_t is None:
        size_usd = TOTAL_CAPITAL * ALLOCATION[symbol] * LEVERAGE
        qty = round(size_usd / current_price, 4)
        
        # Target 1 is 10% Profit at 25x Leverage (0.4% Price Move)
        target_move = current_price * 0.004
        
        trade = {
            "pair": symbol, "side": signal, "entry": current_price, "qty": qty,
            "sl": current_price * 0.985 if signal == "LONG" else current_price * 1.015,
            "t1": current_price + target_move if signal == "LONG" else current_price - target_move,
            "partial": False, "status": "OPEN", "time": datetime.now().strftime("%H:%M")
        }
        st.session_state.trades.append(trade)
        send_telegram(f"🚀 AUTO {signal} | {symbol}\nQty: {qty} (25x)\nEntry: {current_price}")

    # PARTIAL BOOKING & TRAILING
    for t in st.session_state.trades:
        if t["status"] == "OPEN" and t["pair"] == symbol:
            if not t["partial"]:
                hit = (current_price >= t["t1"]) if t["side"] == "LONG" else (current_price <= t["t1"])
                if hit:
                    t["partial"] = True
                    t["qty"] = t["qty"] / 2
                    t["sl"] = t["entry"] # Move SL to Break-even
                    send_telegram(f"💰 PARTIAL BOOKED {symbol}\n50% closed. SL moved to Entry.")

            # Exit Conditions
            exit_hit = (current_price <= t["sl"]) if t["side"] == "LONG" else (current_price >= t["sl"])
            if exit_hit:
                t["status"], t["exit"] = "CLOSED", current_price
                send_telegram(f"❌ EXIT {symbol} @ {current_price}")

# ================= DASHBOARD UI =================
st.subheader("📊 Live Market Watch (Volume Profile + Delta Flow)")
st.table(pd.DataFrame(market_data))

st.divider()

col1, col2 = st.columns(2)
with col1:
    st.subheader("📋 Active Positions")
    st.dataframe(pd.DataFrame([t for t in st.session_state.trades if t["status"] == "OPEN"]), use_container_width=True)

with col2:
    st.subheader("📒 History")
    st.dataframe(pd.DataFrame([t for t in st.session_state.trades if t["status"] == "CLOSED"]), use_container_width=True)
