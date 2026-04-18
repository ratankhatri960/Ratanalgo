import streamlit as st
import pandas as pd
import requests
import time
import os
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# ================= 1. CONFIG & SETTINGS =================
st.set_page_config(layout="wide", page_title="Delta AI Pro Engine")
st.title("🤖 Delta AI Pro: Smart Trailing & P&L")

st_autorefresh(interval=5000, key="refresh")

TOTAL_CAPITAL = 1000
ALLOCATION = {"BTCUSD": 0.60, "ETHUSD": 0.40}
LEVERAGE = 25
CSV_FILE = "final_trade_history.csv"

SL_PCT = 0.005        
T1_PCT = 0.005        
SECURE_PCT = 0.00025  

# ✅ NEW (Risk + Cooldown)
RISK_PER_TRADE = 0.02
COOLDOWN_MIN = 15

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
        # ✅ FIXED URL
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=5)
    except: pass

def get_candles(symbol, tf="5m"):
    try:
        now = int(time.time())
        r = requests.get(f"{BASE_URL}/v2/history/candles",
            # ✅ MORE DATA FOR STABILITY
            params={"symbol": symbol, "resolution": tf, "start": now-86400, "end": now}, timeout=10)
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
    if df.empty or len(df) < 50: continue

    df["EMA20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["EMA50"] = df["close"].ewm(span=50, adjust=False).mean()

    # ✅ VWAP FIX (SESSION BASED)
    df['date'] = pd.to_datetime(df['time'], unit='s').dt.date
    df['cum_vol'] = df.groupby('date')['volume'].cumsum()
    df['cum_vol_price'] = (df['close'] * df['volume']).groupby(df['date']).cumsum()
    df['VWAP'] = df['cum_vol_price'] / df['cum_vol']
    
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    curr_p = float(curr["close"])
    vwap_val = round(curr["VWAP"], 2)
    
    # ✅ FVG FIX
    bull_fvg = df.iloc[-3]["high"] < df.iloc[-1]["low"]
    bear_fvg = df.iloc[-3]["low"] > df.iloc[-1]["high"]

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

    market_watch.append({"SYMBOL": symbol, "PRICE": curr_p, "VWAP": vwap_val, "SIGNAL": signal})

    active_t = next((t for t in st.session_state.trades if t["status"] == "OPEN" and t["pair"] == symbol), None)

    # ================= EXECUTION =================
    if is_fresh_setup and active_t is None:

        # ✅ COOLDOWN ADD
        last_trade = next((t for t in reversed(st.session_state.trades) if t["pair"] == symbol), None)
        if last_trade:
            try:
                last_time = datetime.strptime(last_trade["time"], "%Y-%m-%d %H:%M:%S")
                diff = (datetime.now() - last_time).seconds / 60
                if diff < COOLDOWN_MIN:
                    continue
            except:
                pass

        # ✅ RISK BASED QTY
        risk_amount = TOTAL_CAPITAL * RISK_PER_TRADE
        sl_distance = curr_p * SL_PCT
        qty = round(risk_amount / sl_distance, 4)

        new_trade = {
            "pair": symbol, "side": signal, "entry": curr_p, "qty": qty,
            "sl": round(curr_p * (1 - SL_PCT) if signal == "BUY" else curr_p * (1 + SL_PCT), 2),
            "target1": round(curr_p * (1 + T1_PCT) if signal == "BUY" else curr_p * (1 - T1_PCT), 2),
            "status": "OPEN", "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "exit": None, "partial_done": False, "pnl": 0.0
        }
        st.session_state.trades.append(new_trade)
        save_data(st.session_state.trades)
        send_telegram(f"🚀 {signal} {symbol} Entry: {curr_p}")

    # ================= MANAGEMENT =================
    for t in st.session_state.trades:
        if t["status"] == "OPEN" and t["pair"] == symbol:
            pnl_move = (curr_p - t["entry"]) if t["side"] == "BUY" else (t["entry"] - curr_p)
            t["pnl"] = round(pnl_move * t["qty"], 2)

            # T1
            if not t["partial_done"]:
                hit_t1 = (curr_p >= t["target1"]) if t["side"] == "BUY" else (curr_p <= t["target1"])
                if hit_t1:
                    t["partial_done"] = True
                    t["qty"] = t["qty"] / 2
                    secure_price = t["entry"] * (1 + SECURE_PCT) if t["side"] == "BUY" else t["entry"] * (1 - SECURE_PCT)
                    t["sl"] = round(secure_price, 2)
                    save_data(st.session_state.trades)
                    send_telegram(f"💰 T1 HIT {symbol} | SL Trailed")

            # ✅ REAL TRAILING SL
            if t["partial_done"]:
                if t["side"] == "BUY":
                    new_sl = df.iloc[-2]["low"]
                    if new_sl > t["sl"]:
                        t["sl"] = round(new_sl, 2)
                else:
                    new_sl = df.iloc[-2]["high"]
                    if new_sl < t["sl"]:
                        t["sl"] = round(new_sl, 2)

            # ✅ CANDLE BASED SL HIT
            if t["side"] == "BUY":
                hit_sl = df.iloc[-1]["low"] <= t["sl"]
            else:
                hit_sl = df.iloc[-1]["high"] >= t["sl"]

            if hit_sl:
                t["status"], t["exit"] = "CLOSED", curr_p
                save_data(st.session_state.trades)
                send_telegram(f"❌ EXIT {symbol} @ {curr_p} | P&L: ${t['pnl']}")

# ================= 5. UI =================
st.subheader("📊 Live Market Watch")
st.table(pd.DataFrame(market_watch))
st.divider()

st.subheader("📋 Master Order Book (Live P&L)")
if st.session_state.trades:
    df_h = pd.DataFrame(st.session_state.trades).iloc[::-1]
    total_pnl = round(df_h[df_h['status'] != 'OPEN']['pnl'].sum() + df_h[df_h['status'] == 'OPEN']['pnl'].sum(), 2)
    st.metric("Net P&L (USD)", f"${total_pnl}", delta=total_pnl)
    st.dataframe(df_h, use_container_width=True)
else:
    st.info("Searching for fresh setups...")
