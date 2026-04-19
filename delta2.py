import streamlit as st
import pandas as pd
import requests
import time
import os
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# ================= 1. CONFIG =================
st.set_page_config(layout="wide", page_title="Delta AI Pro")
st.title("🤖 Delta AI Pro: FVG Momentum + POC Volume")

CSV_FILE = "fvg_poc_trade_history.csv"
st_autorefresh(interval=8000, key="refresh") 

TOTAL_CAPITAL = 1000
RISK_PER_TRADE = 0.02
SL_PCT = 0.005
T1_PCT = 0.005
COOLDOWN_MIN = 15
BASE_URL = "https://api.india.delta.exchange"

# ================= 2. DATA FUNCTIONS =================
def load_history():
    if os.path.exists(CSV_FILE):
        try:
            return pd.read_csv(CSV_FILE).to_dict('records')
        except: return []
    return []

if "trades" not in st.session_state:
    st.session_state.trades = load_history()

if "last_candle" not in st.session_state: st.session_state.last_candle = {}

def save_history():
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

# ================= 3. ENGINE LOGIC =================
market_watch = []
for symbol in ["BTCUSD", "ETHUSD"]:
    df = get_candles(symbol, "5m")
    trend_df = get_candles(symbol, "15m")
    if df.empty or len(df) < 50: continue

    # Indicators
    df['vwap'] = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()
    df["delta"] = df["volume"].where(df["close"] > df["open"], -df["volume"])
    
    # POC Logic
    df['price_bin'] = df['close'].round(2)
    poc_val = df.tail(20).groupby('price_bin')['volume'].sum().idxmax()
    
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    curr_p = float(curr["close"])
    vwap_val = round(curr['vwap'], 2)
    delta_val = int(df["delta"].tail(5).sum())

    # FVG Logic
    bull_fvg = df.iloc[-3]["high"] < df.iloc[-1]["low"]
    bear_fvg = df.iloc[-3]["low"] > df.iloc[-1]["high"]

    # 15m Trend
    trend_df["ema20"] = trend_df["close"].ewm(span=20).mean()
    trend_df["ema50"] = trend_df["close"].ewm(span=50).mean()
    bullish_trend = trend_df.iloc[-1]["ema20"] > trend_df.iloc[-1]["ema50"]

    signal = "HOLD"
    if bullish_trend and curr_p > vwap_val and curr_p > poc_val and bull_fvg and delta_val > 0:
        signal = "LONG"
    elif not bullish_trend and curr_p < vwap_val and curr_p < poc_val and bear_fvg and delta_val < 0:
        signal = "SHORT"

    market_watch.append({"Symbol": symbol, "Price": curr_p, "VWAP": vwap_val, "POC": poc_val, "Delta": delta_val, "Signal": signal})

    active = next((t for t in st.session_state.trades if t.get("status") == "OPEN" and t.get("pair") == symbol), None)
    
    if signal != "HOLD" and active is None and st.session_state.last_candle.get(symbol) != curr['time']:
        sl = curr_p * (1 - SL_PCT) if signal == "LONG" else curr_p * (1 + SL_PCT)
        t1 = curr_p * (1 + T1_PCT) if signal == "LONG" else curr_p * (1 - T1_PCT)
        qty = round((TOTAL_CAPITAL * RISK_PER_TRADE) / (curr_p * SL_PCT), 4)

        st.session_state.trades.append({
            "pair": symbol, "side": signal, "entry": curr_p, "qty": qty, "sl": round(sl, 2), "target": round(t1, 2),
            "status": "OPEN", "pnl": 0.0, "entry_t": datetime.now().strftime("%d/%m %H:%M:%S"),
            "exit_t": "-", "partial": False
        })
        st.session_state.last_candle[symbol] = curr['time']
        save_history()

    # MANAGEMENT
    for t in st.session_state.trades:
        if t.get("status") == "OPEN" and t.get("pair") == symbol:
            move = (curr_p - t["entry"]) if t["side"] == "LONG" else (t["entry"] - curr_p)
            t["pnl"] = round(move * t.get("qty", 0), 2)
            
            if not t.get("partial") and (curr_p >= t["target"] if t["side"] == "LONG" else curr_p <= t["target"]):
                t["partial"], t["sl"] = True, t["entry"]
                save_history()

            if (curr_p <= t["sl"] if t["side"] == "LONG" else curr_p >= t["sl"]):
                t["status"], t["exit_t"] = "CLOSED", datetime.now().strftime("%d/%m %H:%M:%S")
                save_history()

# ================= 4. DASHBOARD UI =================
st.subheader("📡 Live Market Intelligence")
t_col1, t_col2 = st.columns(2)
for i, mw in enumerate(market_watch):
    with (t_col1 if i == 0 else t_col2):
        color = "#2ecc71" if mw["Signal"] == "LONG" else "#e74c3c" if mw["Signal"] == "SHORT" else "#555"
        st.markdown(f"""
            <div style="padding:15px; border-radius:10px; border-left: 8px solid {color}; background-color:#1e1e1e;">
                <h2 style="margin:0;">{mw['Symbol']} <small style="font-size:12px; color:{color};">{mw['Signal']}</small></h2>
                <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px; margin-top:10px;">
                    <div><p style="color:#888;margin:0;font-size:12px;">PRICE</p><b>${mw['Price']}</b></div>
                    <div><p style="color:#888;margin:0;font-size:12px;">VWAP</p><b>{mw['VWAP']}</b></div>
                    <div><p style="color:#888;margin:0;font-size:12px;">POC</p><b style="color:#f1c40f;">{mw['POC']}</b></div>
                    <div><p style="color:#888;margin:0;font-size:12px;">DELTA</p><b style="color:#ffffff;">{mw['Delta']}</b></div>
                </div>
            </div>
        """, unsafe_allow_html=True)

st.divider()
st.subheader("📋 Trade Management Dashboard")
if st.session_state.trades:
    df_raw = pd.DataFrame(st.session_state.trades)
    
    # कॉलम रिनेम करने से पहले चेक करें कि कॉलम मौजूद हैं या नहीं
    mapping = {
        "pair": "Symbol", "side": "Side", "entry": "Entry", "sl": "SL (Live)",
        "target": "Target", "pnl": "PnL", "entry_t": "Entry T", "exit_t": "Exit T"
    }
    
    # केवल वही कॉलम चुनें जो डेटाफ्रेम में उपलब्ध हों
    existing_cols = [c for c in mapping.keys() if c in df_raw.columns]
    df_filtered = df_raw[existing_cols].rename(columns=mapping)
    
    # Action कॉलम जोड़ें
    if "status" in df_raw.columns:
        df_filtered["Action"] = df_raw.apply(lambda r: "🔴 Closed" if r.get("status")=="CLOSED" else ("✅ T1 Hit" if r.get("partial") else "🟢 Running"), axis=1)
    
    # डिस्प्ले आर्डर पक्का करें
    final_order = ["Symbol", "Side", "Entry", "SL (Live)", "Target", "PnL", "Entry T", "Exit T", "Action"]
    display_cols = [c for c in final_order if c in df_filtered.columns]
    
    st.dataframe(df_filtered[display_cols].sort_index(ascending=False), use_container_width=True, hide_index=True)
else:
    st.info("No trades found.")
