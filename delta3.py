import streamlit as st
import pandas as pd
import requests
import time
import os
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# ================= 1. CONFIG & RISK =================
st.set_page_config(layout="wide", page_title="Delta AI Pro Bot")
st.title("🤖 Delta AI Pro: Volume & Delta (Persistent)")

st_autorefresh(interval=5000, key="refresh")

TOTAL_CAPITAL = 1000
ALLOCATION = {"BTCUSD": 0.60, "ETHUSD": 0.40}
LEVERAGE = 25
BASE_URL = "https://api.india.delta.exchange"
CSV_FILE = "volume_delta_history.csv"

TELEGRAM_TOKEN = st.secrets.get("TELEGRAM_TOKEN", "")
CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "")

# ================= 2. PERSISTENCE FUNCTIONS =================
def load_history():
    if os.path.exists(CSV_FILE):
        try: return pd.read_csv(CSV_FILE).to_dict('records')
        except: return []
    return []

def save_history(trades):
    if trades: pd.DataFrame(trades).to_csv(CSV_FILE, index=False)

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

# ================= 3. SESSION STATE =================
if "trades" not in st.session_state:
    st.session_state.trades = load_history()

# ================= 4. MAIN ENGINE =================
market_data = []

for symbol in ["BTCUSD", "ETHUSD"]:
    df = get_candles(symbol, "5m")
    trend_df = get_candles(symbol, "15m")
    if df.empty or trend_df.empty: continue

    # INDICATORS
    df["vwap"] = (df["close"] * df["volume"]).cumsum() / df["volume"].cumsum()
    df["delta"] = df.apply(lambda x: x["volume"] if x["close"] > x["open"] else -x["volume"], axis=1)
    
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    current_price = float(curr["close"])
    total_delta = df["delta"].tail(5).sum()
    vwap_val = round(curr["vwap"], 2)
    
    # 15M TREND
    trend_df["ema20"] = trend_df["close"].ewm(span=20).mean()
    trend_df["ema50"] = trend_df["close"].ewm(span=50).mean()
    bullish = trend_df.iloc[-1]["ema20"] > trend_df.iloc[-1]["ema50"]

    # SIGNAL LOGIC
    signal = "HOLD"
    if bullish and current_price > vwap_val and total_delta > 0: signal = "LONG"
    elif not bullish and current_price < vwap_val and total_delta < 0: signal = "SHORT"

    # ⚡ FRESH SETUP CHECK (Pichli candle par signal nahi tha, abhi trigger hua hai)
    prev_total_delta = df["delta"].iloc[-6:-1].sum()
    prev_bullish = trend_df.iloc[-2]["ema20"] > trend_df.iloc[-2]["ema50"]
    
    was_signaled = False
    if prev_bullish and prev["close"] > prev["vwap"] and prev_total_delta > 0: was_signaled = True
    elif not prev_bullish and prev["close"] < prev["vwap"] and prev_total_delta < 0: was_signaled = True

    is_fresh_trigger = (signal in ["LONG", "SHORT"]) and (not was_signaled)

    market_data.append({
        "SYMBOL": symbol, "PRICE": current_price, "VWAP": vwap_val,
        "DELTA": total_delta, "SIGNAL": signal, "STATUS": "🔥 TRIGGER" if is_fresh_trigger else "WAITING"
    })

    # AUTO EXECUTION
    active_t = next((t for t in st.session_state.trades if t["pair"] == symbol and t["status"] == "OPEN"), None)

    if is_fresh_trigger and active_t is None:
        size_usd = TOTAL_CAPITAL * ALLOCATION[symbol] * LEVERAGE
        qty = round(size_usd / current_price, 4)
        target_move = current_price * 0.004
        
        trade = {
            "pair": symbol, "side": signal, "entry": current_price, "qty": qty,
            "sl": round(current_price * 0.985 if signal == "LONG" else current_price * 1.015, 2),
            "t1": round(current_price + target_move if signal == "LONG" else current_price - target_move, 2),
            "partial": False, "status": "OPEN", "time": datetime.now().strftime("%Y-%m-%d %H:%M")
        }
        st.session_state.trades.append(trade)
        save_history(st.session_state.trades)
        send_telegram(f"🚀 {signal} {symbol} | Entry: {current_price}")

    # MANAGEMENT
    for t in st.session_state.trades:
        if t["status"] == "OPEN" and t["pair"] == symbol:
            # Partial
            if not t["partial"]:
                hit = (current_price >= t["t1"]) if t["side"] == "LONG" else (current_price <= t["t1"])
                if hit:
                    t["partial"], t["qty"], t["sl"] = True, t["qty"]/2, t["entry"]
                    save_history(st.session_state.trades)
                    send_telegram(f"💰 PARTIAL {symbol} | SL to Cost")

            # Exit
            exit_hit = (current_price <= t["sl"]) if t["side"] == "LONG" else (current_price >= t["sl"])
            if exit_hit:
                t["status"], t["exit_price"] = "CLOSED", current_price
                save_history(st.session_state.trades)
                send_telegram(f"❌ EXIT {symbol} @ {current_price}")

# ================= 5. DASHBOARD UI =================
st.subheader("📊 Live Market Watch")
st.table(pd.DataFrame(market_data))

st.divider()

col1, col2 = st.columns(2)
with col1:
    st.subheader("📋 Active Positions")
    active_df = pd.DataFrame([t for t in st.session_state.trades if t["status"] == "OPEN"])
    st.dataframe(active_df, use_container_width=True)

with col2:
    st.subheader("📒 Trade History (Saved to CSV)")
    history_df = pd.DataFrame([t for t in st.session_state.trades if t["status"] == "CLOSED"])
    st.dataframe(history_df.iloc[::-1], use_container_width=True) # Latest first
