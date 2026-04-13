import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
import time
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# ================= CONFIG =================
st.set_page_config(layout="wide", page_title="Delta Pro FVG Bot")
st.title("🚀 Delta Pro Dashboard (FVG + EMA)")

# Auto-refresh every 10 seconds
st_autorefresh(interval=10000, key="refresh")

# SECRETS (From Streamlit Cloud Settings)
TELEGRAM_TOKEN = st.secrets.get("TELEGRAM_TOKEN", "")
CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "")
BASE_URL = "https://api.india.delta.exchange"

# ================= FUNCTIONS =================
def send_telegram(msg):
    try:
        if not TELEGRAM_TOKEN or not CHAT_ID: return
        url = f"https://telegram.org{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=5)
    except: pass

def get_candles(symbol, tf="5m"):
    try:
        now = int(time.time())
        r = requests.get(
            f"{BASE_URL}/v2/history/candles",
            params={"symbol": symbol, "resolution": tf, "start": now-86400, "end": now},
            timeout=10
        ).json()
        if "result" not in r: return pd.DataFrame()
        df = pd.DataFrame(r["result"]).sort_values("time")
        for c in ["open","high","low","close","volume"]:
            if c in df.columns: df[c] = pd.to_numeric(df[c], errors="coerce")
        if "time" in df.columns: df["time"] = pd.to_datetime(df["time"], unit="s")
        return df.dropna()
    except: return pd.DataFrame()

def detect_fvg(df):
    bullish_fvg, bearish_fvg = False, False
    if len(df) < 3: return bullish_fvg, bearish_fvg
    if df.iloc[-3]["high"] < df.iloc[-1]["low"]: bullish_fvg = True
    if df.iloc[-3]["low"] > df.iloc[-1]["high"]: bearish_fvg = True
    return bullish_fvg, bearish_fvg

# ================= SESSION STATE =================
if "trades" not in st.session_state: st.session_state.trades = []
if "last_signal" not in st.session_state: st.session_state.last_signal = None

# ================= UI =================
symbol = st.selectbox("Select Pair", ["BTCUSD", "ETHUSD"])

# ================= MAIN LOGIC =================
df = get_candles(symbol)

if not df.empty:
    # 1. INDICATORS
    df["EMA20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["EMA50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["VWAP"] = (df["close"] * df["volume"]).cumsum() / df["volume"].cumsum()
    
    current_price = float(df.iloc[-1]["close"])
    ema20 = df["EMA20"].iloc[-1]
    ema50 = df["EMA50"].iloc[-1]
    vwap = df["VWAP"].iloc[-1]
    bull_fvg, bear_fvg = detect_fvg(df)

    # 2. SIGNAL GENERATOR
    signal = "HOLD"
    if current_price > vwap and ema20 > ema50 and bull_fvg: signal = "BUY"
    elif current_price < vwap and ema20 < ema50 and bear_fvg: signal = "SELL"

    # 3. ACTIVE TRADE CHECK
    active_trade = next((t for t in st.session_state.trades if t["status"] == "OPEN"), None)

    # 4. NEW ENTRY
    if signal in ["BUY", "SELL"] and active_trade is None:
        trade = {
            "pair": symbol, "signal": signal, "entry": current_price,
            "sl": current_price - 200 if signal == "BUY" else current_price + 200,
            "target": current_price + 400 if signal == "BUY" else current_price - 400,
            "status": "OPEN", "time": datetime.now().strftime("%H:%M")
        }
        st.session_state.trades.append(trade)
        if st.session_state.last_signal != signal:
            send_telegram(f"🚀 NEW SIGNAL\nPair: {symbol}\nSignal: {signal}\nEntry: {current_price}")
            st.session_state.last_signal = signal

    # 5. MANAGE TRADES (Trailing/Exit)
    for t in st.session_state.trades:
        if t["status"] == "OPEN":
            if t["signal"] == "BUY":
                if current_price <= t["sl"] or current_price >= t["target"]:
                    t["status"], t["exit"] = ("SL HIT" if current_price <= t["sl"] else "TARGET HIT"), current_price
                    send_telegram(f"✅ Closed BUY {symbol} @ {current_price}")
            else:
                if current_price >= t["sl"] or current_price <= t["target"]:
                    t["status"], t["exit"] = ("SL HIT" if current_price >= t["sl"] else "TARGET HIT"), current_price
                    send_telegram(f"✅ Closed SELL {symbol} @ {current_price}")

    # 6. CHART
    fig = go.Figure(data=[go.Candlestick(x=df["time"], open=df["open"], high=df["high"], low=df["low"], close=df["close"], name="Candles")])
    fig.add_trace(go.Scatter(x=df["time"], y=df["EMA20"], mode="lines", name="EMA20", line=dict(color='yellow')))
    fig.add_trace(go.Scatter(x=df["time"], y=df["EMA50"], mode="lines", name="EMA50", line=dict(color='blue')))
    fig.add_trace(go.Scatter(x=df["time"], y=df["VWAP"], mode="lines", name="VWAP", line=dict(color='white')))
    st.plotly_chart(fig, use_container_width=True)

    # 7. ANALYTICS
    wins = len([t for t in st.session_state.trades if t["status"] == "TARGET HIT"])
    losses = len([t for t in st.session_state.trades if t["status"] == "SL HIT"])
    st.subheader("📊 Performance")
    c1, c2, c3 = st.columns(3)
    c1.metric("Wins", wins)
    c2.metric("Losses", losses)
    c3.metric("Win Rate", f"{round(wins/(wins+losses)*100, 2) if (wins+losses)>0 else 0}%")

    st.subheader("📊 Trade History")
    st.dataframe(pd.DataFrame(st.session_state.trades) if st.session_state.trades else "No trades yet.")

else:
    st.warning("Waiting for Delta India API Data...")
