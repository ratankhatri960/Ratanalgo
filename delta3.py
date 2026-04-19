import streamlit as st
import pandas as pd
import requests
import time
import os
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# ================= 1. CONFIG =================
st.set_page_config(layout="wide", page_title="Delta AI Pro: Date & Time Tracker")
st.title("🚀 Delta AI Pro: Volume Profile + Delta Flow (with History)")

CSV_FILE = "poc_delta_history_dated.csv"
st_autorefresh(interval=10000, key="refresh")

TOTAL_CAPITAL = 1000
BASE_URL = "https://delta.exchange"
SL_VAL_PCT = 0.005
T1_VAL_PCT = 0.005
COOLDOWN_MIN = 15

# ================= 2. STATE MANAGEMENT =================
if "trades" not in st.session_state:
    if os.path.exists(CSV_FILE):
        try: st.session_state.trades = pd.read_csv(CSV_FILE).to_dict('records')
        except: st.session_state.trades = []
    else: st.session_state.trades = []

if "last_candle" not in st.session_state: st.session_state.last_candle = {}
if "last_entry" not in st.session_state: st.session_state.last_entry = {}

# ================= 3. CORE FUNCTIONS =================
def save_data():
    if st.session_state.trades:
        pd.DataFrame(st.session_state.trades).to_csv(CSV_FILE, index=False)

def get_candles(symbol, tf="5m"):
    try:
        now = int(time.time())
        r = requests.get(f"{BASE_URL}/v2/history/candles", 
                         params={"symbol": symbol, "resolution": tf, "start": now-86400, "end": now}, timeout=10).json()
        df = pd.DataFrame(r["result"]).sort_values("time")
        for c in ["open","high","low","close","volume"]: df[c] = pd.to_numeric(df[c])
        return df.dropna()
    except: return pd.DataFrame()

def calculate_poc(df):
    if df.empty: return 0
    df['price_bin'] = df['close'].round(2)
    return df.groupby('price_bin')['volume'].sum().idxmax()

# ================= 4. ENGINE LOGIC =================
market_watch = []
for symbol in ["BTCUSD", "ETHUSD"]:
    df = get_candles(symbol, "5m")
    trend_df = get_candles(symbol, "15m")
    if df.empty or trend_df.empty: continue

    # Indicators
    df['vwap'] = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()
    df["delta"] = df["volume"].where(df["close"] > df["open"], -df["volume"])
    
    curr_p = float(df.iloc[-1]["close"])
    vwap_val = round(df.iloc[-1]["vwap"], 2)
    delta_flow = df["delta"].tail(5).sum()
    poc_val = calculate_poc(df.tail(20))
    
    # Trend Check (15m)
    trend_df["ema20"] = trend_df["close"].ewm(span=20).mean()
    trend_df["ema50"] = trend_df["close"].ewm(span=50).mean()
    bullish = trend_df.iloc[-1]["ema20"] > trend_df.iloc[-1]["ema50"]

    # --- SIGNAL ---
    signal = "HOLD"
    if bullish and curr_p > vwap_val and curr_p > poc_val and delta_flow > 0:
        signal = "LONG"
    elif not bullish and curr_p < vwap_val and curr_p < poc_val and delta_flow < 0:
        signal = "SHORT"

    market_watch.append({"Symbol": symbol, "Price": curr_p, "POC": poc_val, "Delta": delta_flow, "Signal": signal})

    # --- EXECUTION ---
    active = next((t for t in st.session_state.trades if t["pair"] == symbol and t["status"] == "OPEN"), None)
    cooldown_ok = (time.time() - st.session_state.last_entry.get(symbol, 0)) > (COOLDOWN_MIN * 60)
    
    if signal != "HOLD" and active is None and cooldown_ok and st.session_state.last_candle.get(symbol) != df.iloc[-1]['time']:
        sl = curr_p * (1 - SL_VAL_PCT) if signal == "LONG" else curr_p * (1 + SL_VAL_PCT)
        t1 = curr_p * (1 + T1_VAL_PCT) if signal == "LONG" else curr_p * (1 - T1_VAL_PCT)
        
        st.session_state.trades.append({
            "pair": symbol, "side": signal, "entry": curr_p, "sl": round(sl, 2), "target": round(t1, 2),
            "status": "OPEN", "pnl": 0.0, 
            "entry_t": datetime.now().strftime("%d/%m %H:%M:%S"), # Date + Time
            "exit_t": "-", "partial": False
        })
        st.session_state.last_candle[symbol] = df.iloc[-1]['time']
        st.session_state.last_entry[symbol] = time.time()
        save_data()

    # --- LIVE MGMT ---
    for t in st.session_state.trades:
        if t["status"] == "OPEN" and t["pair"] == symbol:
            move = (curr_p - t["entry"]) if t["side"] == "LONG" else (t["entry"] - curr_p)
            t["pnl"] = round(move * 10, 2)
            
            # T1 Hit
            if not t["partial"] and (curr_p >= t["target"] if t["side"] == "LONG" else curr_p <= t["target"]):
                t["partial"], t["sl"] = True, t["entry"]
                save_data()

            # Exit Check
            if (curr_p <= t["sl"] if t["side"] == "LONG" else curr_p >= t["sl"]):
                t["status"] = "CLOSED"
                t["exit_t"] = datetime.now().strftime("%d/%m %H:%M:%S") # Date + Time
                save_data()

# ================= 5. DASHBOARD UI (FIXED LIVE WITH INDICATORS) =================

st.subheader("📡 Live Market Intelligence")

# ऊपर की तरफ लाइव इंडिकेटर कार्ड्स (Indicators + Price)
t_col1, t_col2 = st.columns(2)

for i, mw in enumerate(market_watch):
    with (t_col1 if i == 0 else t_col2):
        # सिग्नल के हिसाब से बॉर्डर कलर
        b_color = "#2ecc71" if mw["Signal"] == "LONG" else "#e74c3c" if mw["Signal"] == "SHORT" else "#555"
        
        st.markdown(f"""
            <div style="padding:20px; border-radius:15px; border-left: 10px solid {b_color}; background-color:#1e1e1e; color:white;">
                <div style="display:flex; justify-content:between; align-items:center;">
                    <h2 style="margin:0;">{mw['Symbol']}</h2>
                    <span style="margin-left:auto; background:{b_color}; padding:5px 15px; border-radius:20px; font-size:14px;">{mw['Signal']}</span>
                </div>
                <hr style="border:0.5px solid #333;">
                <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px;">
                    <div>
                        <p style="color:#aaa; margin:0; font-size:12px;">LIVE PRICE</p>
                        <p style="font-size:22px; font-weight:bold; margin:0;">${mw['Price']}</p>
                    </div>
                    <div>
                        <p style="color:#aaa; margin:0; font-size:12px;">VWAP</p>
                        <p style="font-size:18px; margin:0;">{mw['VWAP']}</p>
                    </div>
                    <div>
                        <p style="color:#aaa; margin:0; font-size:12px;">POC (Volume)</p>
                        <p style="font-size:18px; margin:0; color:#f1c40f;">{mw['POC']}</p>
                    </div>
                    <div>
                        <p style="color:#aaa; margin:0; font-size:12px;">DELTA FLOW</p>
                        <p style="font-size:18px; margin:0; color:{'#2ecc71' if mw['Delta'] > 0 else '#e74c3c'};">{mw['Delta']}</p>
                    </div>
                </div>
                <p style="margin-top:10px; font-size:12px; color:#888;">Trend (15m): {"Bullish 📈" if mw['Signal'] == "LONG" or (mw['Price'] > mw['VWAP'] and mw['Delta'] > 0) else "Bearish 📉"}</p>
            </div>
        """, unsafe_allow_html=True)

st.divider()

# नीचे की तरफ ट्रेड मैनेजमेंट टेबल
st.subheader("📋 Active & Past Trades")

if st.session_state.trades:
    df_show = pd.DataFrame(st.session_state.trades).copy()
    
    # कॉलम नाम बदलना (आपके मांगे गए ऑर्डर में)
    df_show = df_show.rename(columns={
        "pair": "Symbol", "side": "Side", "entry": "Entry", "sl": "SL (Live)",
        "target": "Target", "pnl": "PnL", "entry_t": "Entry T", "exit_t": "Exit T"
    })
    
    def get_action(row):
        if row["status"] == "CLOSED": return "🔴 Closed"
        return "✅ T1 Hit (Safe)" if row["partial"] else "🟢 Running"

    df_show["Action"] = df_show.apply(get_action, axis=1)
    
    final_cols = ["Symbol", "Side", "Entry", "SL (Live)", "Target", "PnL", "Entry T", "Exit T", "Action"]
    
    # लाइव टेबल
    st.dataframe(df_show[final_cols].sort_index(ascending=False), use_container_width=True, hide_index=True)

    # डाउनलोड बटन
    csv_data = pd.DataFrame(st.session_state.trades).to_csv(index=False).encode('utf-8')
    st.download_button(label="📥 Download CSV", data=csv_data, file_name="trading_history.csv", mime="text/csv")
else:
    st.info("No trades yet. Monitoring POC, Delta, and VWAP for entry...")
