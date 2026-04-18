import streamlit as st
import pandas as pd
import requests
import time
import os
from datetime import datetime, time as dt_time, timedelta
from streamlit_autorefresh import st_autorefresh

# ================= 1. CONFIG =================
st.set_page_config(layout="wide", page_title="Delta Midnight Pro")
st.title("🤖 Midnight ORB: Fresh Breakout Logic")

st_autorefresh(interval=5000, key="refresh") 

TOTAL_CAPITAL = 1000
LEVERAGE = 25
CSV_FILE = "midnight_closing_history.csv"
BASE_URL = "https://api.india.delta.exchange"

SL_PCT = 0.005        
T1_PCT = 0.005        
SECURE_PCT = 0.00025  
RISK_PER_TRADE = 0.02   
COOLDOWN_MIN = 15       

# ================= 2. FUNCTIONS =================
def load_data():
    if os.path.exists(CSV_FILE):
        try: return pd.read_csv(CSV_FILE).to_dict('records')
        except: return []
    return []

def save_data(trades):
    if trades: pd.DataFrame(trades).to_csv(CSV_FILE, index=False)

def get_candles(symbol, tf="5m"):
    try:
        now = int(time.time())
        r = requests.get(f"{BASE_URL}/v2/history/candles",
            params={"symbol": symbol, "resolution": tf, "start": now-108000, "end": now}, timeout=10).json()
        if "result" not in r: return pd.DataFrame()
        df = pd.DataFrame(r["result"]).sort_values("time")
        df["time_ist"] = pd.to_datetime(df["time"], unit='s') + pd.Timedelta(hours=5, minutes=30)
        for c in ["open","high","low","close","volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.dropna()
    except: return pd.DataFrame()

# ================= 3. STATE =================
if "trades" not in st.session_state:
    st.session_state.trades = load_data()

# ================= 4. ENGINE =================
market_watch = []

for symbol in ["BTCUSD", "ETHUSD"]:
    df = get_candles(symbol, "5m")
    if df.empty or len(df) < 50: continue

    # Indicators
    df["EMA20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["EMA50"] = df["close"].ewm(span=50, adjust=False).mean()
    df['date'] = df['time_ist'].dt.date
    df['cum_vol'] = df.groupby('date')['volume'].cumsum()
    df['cum_vol_price'] = (df['close'] * df['volume']).groupby(df['date']).cumsum()
    df['VWAP'] = df['cum_vol_price'] / df['cum_vol']

    # --- Midnight Range Logic ---
        # ================= MIDNIGHT ORB FIX (STABLE VERSION) =================
    last_time = df['time_ist'].iloc[-1]
    current_date = last_time.date()
    yesterday = current_date - timedelta(days=1)

    # Filter data for the 23:30 - 00:30 window
    # Hum pichle 24 ghante mein jo bhi latest 23:30-00:30 window mili hai usko dhundhenge
    range_df = df[
        ((df['time_ist'].dt.date == yesterday) & (df['time_ist'].dt.time >= dt_time(23,30))) |
        ((df['time_ist'].dt.date == current_date) & (df['time_ist'].dt.time <= dt_time(0,30)))
    ]

    # Agar current date me abhi tak 23:30 nahi baje hain, toh pichle din ka range use karein
    if range_df.empty:
        day_before_yesterday = yesterday - timedelta(days=1)
        range_df = df[
            ((df['time_ist'].dt.date == day_before_yesterday) & (df['time_ist'].dt.time >= dt_time(23,30))) |
            ((df['time_ist'].dt.date == yesterday) & (df['time_ist'].dt.time <= dt_time(0,30)))
        ]

    orb_high = round(range_df["high"].max(), 2) if not range_df.empty else 0
    orb_low = round(range_df["low"].min(), 2) if not range_df.empty else 0

    curr = df.iloc[-1]   
    last = df.iloc[-2]   
    prev_last = df.iloc[-3] # To check fresh breakout
    
    curr_p = float(curr["close"])
    last_close = float(last["close"])
    vwap_val = round(curr["VWAP"], 2)
    
    # ================= FRESH BREAKOUT CHECK =================
    # Signal tabhi aayega jab pichli candle range ke andar thi aur ab bahar close hui hai
    signal = "WAITING"
    
    is_fresh_bullish = (last_close > orb_high) and (last.open <= orb_high)
    is_fresh_bearish = (last_close < orb_low) and (last.open >= orb_low)

    if orb_high > 0 and is_fresh_bullish and curr_p > vwap_val and curr["EMA20"] > curr["EMA50"]:
        signal = "BULLISH BREAKOUT"
    elif orb_low > 0 and is_fresh_bearish and curr_p < vwap_val and curr["EMA20"] < curr["EMA50"]:
        signal = "BEARISH BREAKOUT"

    # ================= COOLDOWN CHECK =================
    on_cooldown = False
    last_trade_closed = next((t for t in reversed(st.session_state.trades) if t["pair"] == symbol and t["status"] == "CLOSED"), None)
    
    if last_trade_closed:
        try:
            # We use exit_time or current time logic
            exit_dt = datetime.strptime(last_trade_closed["exit_time"], "%H:%M:%S")
            now_dt = datetime.now()
            # Convert to same day for comparison
            exit_dt = now_dt.replace(hour=exit_dt.hour, minute=exit_dt.minute, second=exit_dt.second)
            diff = (now_dt - exit_dt).total_seconds() / 60
            if diff < COOLDOWN_MIN:
                on_cooldown = True
        except: pass

    market_watch.append({
        "SYMBOL": symbol, "PRICE": curr_p, "SIGNAL": signal, 
        "STATUS": "COOLDOWN" if on_cooldown else "READY",
        "ORB H/L": f"{orb_high}/{orb_low}"
    })

    # EXECUTION
    active_t = next((t for t in st.session_state.trades if t["status"] == "OPEN" and t["pair"] == symbol), None)

    if signal != "WAITING" and active_t is None and not on_cooldown:
        side = "LONG" if signal == "BULLISH BREAKOUT" else "SHORT"
        
        # Risk Based Qty
        risk_amount = TOTAL_CAPITAL * RISK_PER_TRADE
        sl_distance = curr_p * SL_PCT
        qty = round(risk_amount / sl_distance, 4)

        new_trade = {
            "pair": symbol, "side": side, "entry": curr_p, "qty": qty,
            "sl": round(curr_p * (1 - SL_PCT) if side == "LONG" else curr_p * (1 + SL_PCT), 2),
            "target1": round(curr_p * (1 + T1_PCT) if side == "LONG" else curr_p * (1 - T1_PCT), 2),
            "partial_done": False, "status": "OPEN", 
            "entry_time": datetime.now().strftime("%H:%M:%S"),
            "exit_time": "-", "pnl": 0.0
        }
        st.session_state.trades.append(new_trade)
        save_data(st.session_state.trades)

    # MANAGEMENT
    for t in st.session_state.trades:
        if t["status"] == "OPEN" and t["pair"] == symbol:
            pnl_move = (curr_p - t["entry"]) if t["side"] == "LONG" else (t["entry"] - curr_p)
            t["pnl"] = round(pnl_move * t["qty"], 2)

            if not t["partial_done"]:
                hit_t1 = (curr_p >= t["target1"]) if t["side"] == "LONG" else (curr_p <= t["target1"])
                if hit_t1:
                    t["partial_done"] = True
                    t["qty"] = t["qty"] / 2 
                    t["sl"] = round(t["entry"] * (1 + SECURE_PCT) if t["side"] == "LONG" else t["entry"] * (1 - SECURE_PCT), 2)
                    save_data(st.session_state.trades)

            # Trailing SL after Partial
            if t["partial_done"]:
                new_sl = df.iloc[-2]["low"] if t["side"] == "LONG" else df.iloc[-2]["high"]
                if t["side"] == "LONG" and new_sl > t["sl"]: t["sl"] = round(new_sl, 2)
                elif t["side"] == "SHORT" and new_sl < t["sl"]: t["sl"] = round(new_sl, 2)

            # EXIT CHECK
            hit_exit = (curr_p <= t["sl"]) if t["side"] == "LONG" else (curr_p >= t["sl"])
            if hit_exit:
                t["status"], t["exit_price"] = "CLOSED", curr_p
                t["exit_time"] = datetime.now().strftime("%H:%M:%S")
                save_data(st.session_state.trades)

# ================= 5. UI =================
st.subheader("📊 Live Market Watch")
st.table(pd.DataFrame(market_watch))

st.subheader("📋 Active Trades")
for i, t in enumerate(st.session_state.trades):
    if t["status"] == "OPEN":
        c = st.columns([1, 1, 1, 1, 1, 1])
        c[0].write(f"**{t['pair']}** ({t['side']})")
        c[1].write(f"Entry: {t['entry']}")
        c[2].write(f"SL: {t['sl']}")
        c[3].write(f"PnL: {t['pnl']}")
        c[4].write(f"Time: {t['entry_time']}")
        if c[5].button(f"Manual Exit", key=f"exit_{i}"):
            t["status"], t["exit_time"] = "CLOSED", datetime.now().strftime("%H:%M:%S")
            save_data(st.session_state.trades)
            st.rerun()

st.divider()
st.subheader("📜 Trade History")
if st.session_state.trades:
    st.dataframe(pd.DataFrame(st.session_state.trades).iloc[::-1], use_container_width=True)
