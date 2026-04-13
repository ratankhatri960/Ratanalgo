import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime, time as dt_time
from streamlit_autorefresh import st_autorefresh

# ================= CONFIG & RISK =================
st.set_page_config(layout="wide", page_title="Delta Pro Auto-Bot")
st_autorefresh(interval=10000, key="refresh") # 10 sec refresh

BASE_URL = "https://api.india.delta.exchange"
SYMBOLS = ["BTCUSD", "ETHUSD"]
TOTAL_CAPITAL = 1000  
ALLOCATION = {"BTCUSD": 0.60, "ETHUSD": 0.40} 
LEVERAGE = 10

TELEGRAM_TOKEN = st.secrets.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "")

# ================= SESSION INIT =================
if "trades" not in st.session_state: st.session_state.trades = []
if "orb" not in st.session_state: st.session_state.orb = {}

# ================= FUNCTIONS =================
def send_telegram(msg):
    try:
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
        url = f"https://telegram.org{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=5)
    except: pass

def get_candles(symbol, tf="5m"):
    try:
        now = int(time.time())
        # Delta India API: History Candles
        r = requests.get(f"{BASE_URL}/v2/history/candles",
            params={"symbol": symbol, "resolution": tf, "start": now-86400, "end": now}, timeout=10).json()
        
        if "result" not in r or not r["result"]:
            return pd.DataFrame()
            
        df = pd.DataFrame(r["result"]).sort_values("time")
        for c in ["open","high","low","close","volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.dropna()
    except Exception as e:
        return pd.DataFrame()

def ema(series, n):
    return series.ewm(span=n, adjust=False).mean()

# ================= ENGINE LOGIC =================
st.title("🤖 Delta Pro Auto-Algo (10x Leverage)")

market_watch = []

for symbol in SYMBOLS:
    df = get_candles(symbol)
    
    if df.empty:
        # Agar data nahi aa raha toh table mein 'N/A' dikhayega
        market_watch.append({"SYMBOL": symbol, "PRICE": "Waiting...", "EMA 9": "N/A", "EMA 21": "N/A", "SIGNAL": "No Connection"})
        continue

    # 1. INDICATORS
    df["ema9"] = ema(df["close"], 9)
    df["ema21"] = ema(df["close"], 21)
    
    # 2. ORB (Opening Range Breakout)
    df["dt"] = pd.to_datetime(df["time"], unit="s") + pd.Timedelta(hours=5, minutes=30)
    df["t"] = df["dt"].dt.time
    orb_df = df[(df["t"] >= dt_time(23,30)) | (df["t"] <= dt_time(0,30))]
    
    oh = float(orb_df["high"].max()) if not orb_df.empty else 0
    ol = float(orb_df["low"].min()) if not orb_df.empty else 0
    st.session_state.orb[symbol] = {"high": oh, "low": ol}

    # 3. CURRENT VALUES
    curr_p = float(df.iloc[-1]["close"])
    e9 = round(df["ema9"].iloc[-1], 2)
    e21 = round(df["ema21"].iloc[-1], 2)
    prev_e9, prev_e21 = df["ema9"].iloc[-2], df["ema21"].iloc[-2]

    # 4. SIGNAL
    signal = "HOLD"
    if prev_e9 < prev_e21 and e9 > e21 and curr_p > oh: signal = "LONG"
    elif prev_e9 > prev_e21 and e9 < e21 and curr_p < ol: signal = "SHORT"

    market_watch.append({
        "SYMBOL": symbol, "PRICE": curr_p, "EMA 9": e9, "EMA 21": e21,
        "ORB HIGH": oh, "ORB LOW": ol, "SIGNAL": signal
    })

    # 5. TRADING EXECUTION
    active_t = next((t for t in st.session_state.trades if t["status"] == "OPEN" and t["pair"] == symbol), None)

    if signal in ["LONG", "SHORT"] and active_t is None:
        qty = (TOTAL_CAPITAL * ALLOCATION[symbol] * LEVERAGE) / curr_p
        t_dist = curr_p * 0.01 # 1% Target
        
        st.session_state.trades.append({
            "pair": symbol, "side": signal, "entry": curr_p, "qty": round(qty, 4),
            "sl": curr_p * 0.98 if signal == "LONG" else curr_p * 1.02,
            "t1": curr_p + t_dist if signal == "LONG" else curr_p - t_dist,
            "partial_done": False, "status": "OPEN", "time": datetime.now().strftime("%H:%M")
        })
        send_telegram(f"🚀 AUTO {signal} | {symbol} @ {curr_p}")

    # 6. MANAGEMENT
    for t in st.session_state.trades:
        if t["status"] == "OPEN" and t["pair"] == symbol:
            if not t["partial_done"]:
                hit = (curr_p >= t["t1"]) if t["side"] == "LONG" else (curr_p <= t["t1"])
                if hit:
                    t["partial_done"], t["qty"], t["sl"] = True, t["qty"]/2, t["entry"]
                    send_telegram(f"💰 PARTIAL BOOKED {symbol}")

            if (curr_p <= t["sl"] if t["side"] == "LONG" else curr_p >= t["sl"]):
                t["status"], t["exit"] = "CLOSED", curr_p
                send_telegram(f"❌ EXIT {symbol} @ {curr_p}")

# ================= DASHBOARD UI =================
st.subheader("📊 Live Market Watch")
if market_watch:
    st.table(pd.DataFrame(market_watch))
else:
    st.warning("Connecting to Delta API...")

st.divider()

c1, c2 = st.columns(2)
with c1:
    st.subheader("📊 Active Trades")
    active_df = pd.DataFrame([t for t in st.session_state.trades if t["status"] == "OPEN"])
    st.dataframe(active_df, use_container_width=True)

with c2:
    st.subheader("📒 History")
    hist_df = pd.DataFrame([t for t in st.session_state.trades if t["status"] == "CLOSED"])
    st.dataframe(hist_df, use_container_width=True)
