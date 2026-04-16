import streamlit as st
import pandas as pd
import requests
import time
import os
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# ================= 1. CONFIG =================
st.set_page_config(layout="wide", page_title="Delta 1H Swing Pro")
st.title("🤖 Delta AI: 1 Hour Swing (OB + FVG)")

st_autorefresh(interval=15000, key="refresh") # 15s refresh for 1H TF

TOTAL_CAPITAL = 1000
LEVERAGE = 10  # Swing ke liye 10x is safer
CSV_FILE = "swing_history.csv"
BASE_URL = "https://delta.exchange"

# ================= 2. FUNCTIONS =================
def load_data():
    if os.path.exists(CSV_FILE):
        try: return pd.read_csv(CSV_FILE).to_dict('records')
        except: return []
    return []

def save_data(trades):
    if trades: pd.DataFrame(trades).to_csv(CSV_FILE, index=False)

def get_candles(symbol, tf="1h"): # Default set to 1H
    try:
        now = int(time.time())
        # Fetching more data to calculate 200 EMA
        r = requests.get(f"{BASE_URL}/v2/history/candles",
            params={"symbol": symbol, "resolution": tf, "start": now-(86400*15), "end": now}, timeout=10).json()
        df = pd.DataFrame(r["result"]).sort_values("time")
        for c in ["open","high","low","close","volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.dropna()
    except: return pd.DataFrame()

# ================= 3. STATE =================
if "trades" not in st.session_state:
    st.session_state.trades = load_data()

# ================= 4. SWING ENGINE (1H) =================
market_watch = []

for symbol in ["BTCUSD", "ETHUSD"]:
    df = get_candles(symbol, "1h")
    if df.empty or len(df) < 200: continue

    # A. Trend & Indicators
    df["EMA200"] = df["close"].ewm(span=200, adjust=False).mean()
    df["VWAP"] = (df["close"] * df["volume"]).cumsum() / df["volume"].cumsum()
    
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    old = df.iloc[-3]
    curr_p = float(curr["close"])

    # B. Order Block (OB) Identification
    # Bullish OB: Last down candle before a strong up move
    bull_ob = df.iloc[-5:-2]["low"].min() if df.iloc[-1]["close"] > df.iloc[-3]["high"] else 0
    # Bearish OB: Last up candle before a strong down move
    bear_ob = df.iloc[-5:-2]["high"].max() if df.iloc[-1]["close"] < df.iloc[-3]["low"] else 0

    # C. FVG Detection (1H Imbalance)
    bull_fvg = old["high"] < curr["low"]
    bear_fvg = old["low"] > curr["high"]

    # D. Signal Logic
    signal = "HOLD"
    entry_now = False
    
    # 1H Swing Long: Above EMA200 + Bull FVG + Price near OB
    if curr_p > curr["EMA200"] and bull_fvg:
        signal = "SWING LONG"
        if prev["close"] <= curr["VWAP"]: entry_now = True

    # 1H Swing Short: Below EMA200 + Bear FVG + Price near OB
    elif curr_p < curr["EMA200"] and bear_fvg:
        signal = "SWING SHORT"
        if prev["close"] >= curr["VWAP"]: entry_now = True

    market_watch.append({
        "SYMBOL": symbol, "PRICE": curr_p, 
        "EMA200": round(curr["EMA200"], 2), "SIGNAL": signal
    })

    # E. Execution
    active_t = next((t for t in st.session_state.trades if t["status"] == "OPEN" and t["pair"] == symbol), None)

    if entry_now and active_t is None:
        side = "BUY" if "LONG" in signal else "SELL"
        new_trade = {
            "pair": symbol, "side": side, "entry": curr_p, 
            "qty": round((TOTAL_CAPITAL * 0.5 * LEVERAGE) / curr_p, 4),
            "sl": round(curr_p * 0.97 if side == "BUY" else curr_p * 1.03, 2), # 3% Swing SL
            "target": round(curr_p * 1.05 if side == "BUY" else curr_p * 0.95, 2), # 5% Swing Target
            "status": "OPEN", "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "pnl": 0.0
        }
        st.session_state.trades.append(new_trade)
        save_data(st.session_state.trades)

    # F. P&L & Exit Management
    for t in st.session_state.trades:
        if t["status"] == "OPEN" and t["pair"] == symbol:
            move = (curr_p - t["entry"]) if t["side"] == "BUY" else (t["entry"] - curr_p)
            t["pnl"] = round(move * t["qty"], 2)

            if (t["side"] == "BUY" and curr_p >= t["target"]) or (t["side"] == "SELL" and curr_p <= t["target"]):
                t["status"] = "CLOSED (TARGET)"
                save_data(st.session_state.trades)
            elif (t["side"] == "BUY" and curr_p <= t["sl"]) or (t["side"] == "SELL" and curr_p >= t["sl"]):
                t["status"] = "CLOSED (SL)"
                save_data(st.session_state.trades)

# ================= 5. UI =================
st.subheader("📊 1H Swing Market Watch")
st.table(pd.DataFrame(market_watch))

st.divider()

st.subheader("📋 Order Book & Swing History")
if st.session_state.trades:
    df_h = pd.DataFrame(st.session_state.trades).iloc[::-1]
    st.metric("Total Swing P&L", f"${df_h['pnl'].sum()}", delta=f"{df_h['pnl'].sum()}")
    st.dataframe(df_h, use_container_width=True)
else:
    st.info("Searching for 1H Swing Setups...")
