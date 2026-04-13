import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime, time as dt_time

# ================= CONFIG =================
st.set_page_config(layout="wide", page_title="Delta Algo Pro")
BASE_URL = "https://api.india.delta.exchange"
SYMBOLS = ["BTCUSD", "ETHUSD"]

# GITHUB SAFETY: Secrets use kar rahe hain
TELEGRAM_TOKEN = st.secrets.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "")

LEVERAGE = 10
BALANCE = 10000

# ================= SESSION INIT =================
if "active_trades" not in st.session_state: st.session_state.active_trades = []
if "closed_trades" not in st.session_state: st.session_state.closed_trades = []
if "orb" not in st.session_state: st.session_state.orb = {}

# ================= TELEGRAM =================
def send_telegram(msg):
    try:
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
        url = f"https://telegram.org{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=5)
    except: pass

# ================= DATA FETCHING =================
def get_candles(symbol, tf="5m"):
    try:
        now = int(time.time())
        r = requests.get(
            f"{BASE_URL}/v2/history/candles",
            params={"symbol": symbol, "resolution": tf, "start": now-86400, "end": now},
            timeout=5
        ).json()
        if "result" not in r: return pd.DataFrame()
        df = pd.DataFrame(r["result"]).sort_values("time")
        for c in ["open","high","low","close"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.dropna()
    except: return pd.DataFrame()

def get_price(symbol, df):
    try:
        r = requests.get(f"{BASE_URL}/v2/tickers/{symbol}", timeout=5).json()
        return float(r["result"]["close"])
    except:
        return float(df.iloc[-1]["close"]) if not df.empty else 0

# ================= INDICATORS & UTILS =================
def ema(series, n):
    return series.ewm(span=n, adjust=False).mean()

def calc_qty(price):
    risk = BALANCE * 0.1
    return round((risk * LEVERAGE) / price, 4)

def trade_exists(symbol, strategy_name):
    return any(t["symbol"] == symbol and strategy_name in t["strategy"] for t in st.session_state.active_trades)

# ================= ORB LOGIC =================
def update_orb(symbol, df):
    if df.empty: return
    df["dt"] = pd.to_datetime(df["time"], unit="s") + pd.Timedelta(hours=5, minutes=30)
    df["t"] = df["dt"].dt.time
    # Opening Range: 11:30 PM to 12:30 AM (Example range)
    orb_df = df[(df["t"] >= dt_time(23,30)) | (df["t"] <= dt_time(0,30))]
    if not orb_df.empty:
        st.session_state.orb[symbol] = {
            "high": float(orb_df["high"].max()),
            "low": float(orb_df["low"].min())
        }

# ================= TRADE MANAGEMENT =================
def close_trade(trade, price):
    trade["exit_price"] = price
    trade["exit_time"] = datetime.now().strftime("%H:%M:%S")
    trade["real_pnl"] = trade["running_pnl"]
    trade["status"] = "CLOSED"
    st.session_state.closed_trades.append(trade)
    st.session_state.active_trades.remove(trade)
    send_telegram(f"✅ Closed {trade['symbol']} | PnL: {trade['real_pnl']}")

def manage_trades():
    for trade in st.session_state.active_trades[:]:
        symbol = trade["symbol"]
        df = get_candles(symbol, "5m")
        price = get_price(symbol, df)
        
        trade["running_pnl"] = round(price - trade["entry_price"] if trade["side"] == "BUY" else trade["entry_price"] - price, 2)
        
        # Trailing & SL Logic
        if trade["side"] == "BUY":
            if price <= trade["sl"] or price >= trade["target"]: close_trade(trade, price)
        else:
            if price >= trade["sl"] or price <= trade["target"]: close_trade(trade, price)

# ================= STRATEGIES =================
def check_signals(symbol, df):
    if len(df) < 21: return
    
    # --- EMA Strategy ---
    df["ema9"] = ema(df["close"], 9)
    df["ema21"] = ema(df["close"], 21)
    prev, curr = df.iloc[-2], df.iloc[-1]
    price = curr["close"]

    if not trade_exists(symbol, "EMA"):
        if prev["ema9"] < prev["ema21"] and curr["ema9"] > curr["ema21"]:
            st.session_state.active_trades.append({
                "symbol": symbol, "side": "BUY", "entry_price": price,
                "entry_time": datetime.now().strftime("%H:%M:%S"), "qty": calc_qty(price),
                "strategy": "EMA BUY", "sl": price - 100, "target": price + 200,
                "running_pnl": 0, "status": "OPEN"
            })
            send_telegram(f"📈 EMA BUY {symbol} @ {price}")
        elif prev["ema9"] > prev["ema21"] and curr["ema9"] < curr["ema21"]:
            st.session_state.active_trades.append({
                "symbol": symbol, "side": "SELL", "entry_price": price,
                "entry_time": datetime.now().strftime("%H:%M:%S"), "qty": calc_qty(price),
                "strategy": "EMA SELL", "sl": price + 100, "target": price - 200,
                "running_pnl": 0, "status": "OPEN"
            })
            send_telegram(f"📉 EMA SELL {symbol} @ {price}")

    # --- ORB Strategy ---
    orb = st.session_state.orb.get(symbol)
    if orb and not trade_exists(symbol, "ORB"):
        if prev["close"] <= orb["high"] and curr["close"] > orb["high"]:
            st.session_state.active_trades.append({
                "symbol": symbol, "side": "BUY", "entry_price": price,
                "entry_time": datetime.now().strftime("%H:%M:%S"), "qty": calc_qty(price),
                "strategy": "ORB BUY", "sl": orb["low"], "target": price + 200,
                "running_pnl": 0, "status": "OPEN"
            })
            send_telegram(f"🚀 ORB BUY {symbol}")
        elif prev["close"] >= orb["low"] and curr["close"] < orb["low"]:
            st.session_state.active_trades.append({
                "symbol": symbol, "side": "SELL", "entry_price": price,
                "entry_time": datetime.now().strftime("%H:%M:%S"), "qty": calc_qty(price),
                "strategy": "ORB SELL", "sl": orb["high"], "target": price - 200,
                "running_pnl": 0, "status": "OPEN"
            })
            send_telegram(f"🚀 ORB SELL {symbol}")

# ================= DASHBOARD UI =================
st.title("🛡️ Universal Delta India Algo")

for sym in SYMBOLS:
    df_data = get_candles(sym)
    if not df_data.empty:
        update_orb(sym, df_data)
        check_signals(sym, df_data)

manage_trades()

# Display Tables
col1, col2 = st.columns(2)
with col1:
    st.subheader("📊 Active Trades")
    st.title("🛡️ Universal Delta India Algo")

for sym in SYMBOLS:
    df_data = get_candles(sym)
    if not df_data.empty:
        update_orb(sym, df_data)
        check_signals(sym, df_data)

manage_trades()

# Display Tables (Sahi Indentation ke saath)
col1, col2 = st.columns(2)

with col1:
    st.subheader("📊 Active Trades")
    if st.session_state.active_trades:
        st.dataframe(pd.DataFrame(st.session_state.active_trades), use_container_width=True)
    else:
        st.info("No active trades right now.")

with col2:
    st.subheader("📒 Closed History")
    if st.session_state.closed_trades:
        st.dataframe(pd.DataFrame(st.session_state.closed_trades), use_container_width=True)
    else:
        st.info("History is empty.")

# Auto-Refresh
time.sleep(10)
st.rerun()
