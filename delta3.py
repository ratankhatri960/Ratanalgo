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
BASE_URL = "https://api.india.delta.exchange"
SL_VAL_PCT = 0.005
T1_VAL_PCT = 0.005
COOLDOWN_MIN = 15

# ✅ LEVERAGE (ONLY ADDITION)
LEVERAGE = 10

# ================= 2. STATE MANAGEMENT =================
if "trades" not in st.session_state:
    if os.path.exists(CSV_FILE):
        try:
            st.session_state.trades = pd.read_csv(CSV_FILE).to_dict('records')
        except:
            st.session_state.trades = []
    else:
        st.session_state.trades = []

if "last_candle" not in st.session_state:
    st.session_state.last_candle = {}

if "last_entry" not in st.session_state:
    st.session_state.last_entry = {}

# ================= 3. CORE FUNCTIONS =================
def save_data():
    if st.session_state.trades:
        pd.DataFrame(st.session_state.trades).to_csv(CSV_FILE, index=False)

def get_candles(symbol, tf="5m"):
    try:
        now = int(time.time())
        r = requests.get(
            f"{BASE_URL}/v2/history/candles",
            params={"symbol": symbol, "resolution": tf, "start": now-86400, "end": now},
            timeout=10
        ).json()
        df = pd.DataFrame(r["result"]).sort_values("time")
        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = pd.to_numeric(df[c])
        return df.dropna()
    except:
        return pd.DataFrame()

def calculate_poc(df):
    if df.empty:
        return 0
    df['price_bin'] = df['close'].round(2)
    return df.groupby('price_bin')['volume'].sum().idxmax()

# ================= 4. ENGINE LOGIC =================
market_watch = []

for symbol in ["BTCUSD", "ETHUSD"]:
    df = get_candles(symbol, "5m")
    trend_df = get_candles(symbol, "15m")

    if df.empty or trend_df.empty:
        continue

    # Indicators
    df['vwap'] = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()
    df["delta"] = df["volume"].where(df["close"] > df["open"], -df["volume"])

    curr_p = float(df.iloc[-1]["close"])
    vwap_val = round(df.iloc[-1]["vwap"], 2)
    delta_flow = df["delta"].tail(5).sum()
    poc_val = calculate_poc(df.tail(20))

    # Trend Check
    trend_df["ema20"] = trend_df["close"].ewm(span=20).mean()
    trend_df["ema50"] = trend_df["close"].ewm(span=50).mean()
    bullish = trend_df.iloc[-1]["ema20"] > trend_df.iloc[-1]["ema50"]

    # Signal
    signal = "HOLD"
    if bullish and curr_p > vwap_val and curr_p > poc_val and delta_flow > 0:
        signal = "LONG"
    elif not bullish and curr_p < vwap_val and curr_p < poc_val and delta_flow < 0:
        signal = "SHORT"

    market_watch.append({
        "Symbol": symbol,
        "Price": curr_p,
        "POC": poc_val,
        "Delta": delta_flow,
        "Signal": signal
    })

    # Execution
    active = next((t for t in st.session_state.trades if t["pair"] == symbol and t["status"] == "OPEN"), None)
    cooldown_ok = (time.time() - st.session_state.last_entry.get(symbol, 0)) > (COOLDOWN_MIN * 60)

    if signal != "HOLD" and active is None and cooldown_ok and st.session_state.last_candle.get(symbol) != df.iloc[-1]['time']:
        sl = curr_p * (1 - SL_VAL_PCT) if signal == "LONG" else curr_p * (1 + SL_VAL_PCT)
        t1 = curr_p * (1 + T1_VAL_PCT) if signal == "LONG" else curr_p * (1 - T1_VAL_PCT)

        st.session_state.trades.append({
            "pair": symbol,
            "side": signal,
            "entry": curr_p,
            "sl": round(sl, 2),
            "target": round(t1, 2),
            "status": "OPEN",
            "pnl": 0.0,
            "entry_t": datetime.now().strftime("%d/%m %H:%M:%S"),
            "exit_t": "-",
            "partial": False
        })

        st.session_state.last_candle[symbol] = df.iloc[-1]['time']
        st.session_state.last_entry[symbol] = time.time()
        save_data()

    # Live Management
    for t in st.session_state.trades:
        if t["status"] == "OPEN" and t["pair"] == symbol:
            move = (curr_p - t["entry"]) if t["side"] == "LONG" else (t["entry"] - curr_p)

            # ✅ LEVERAGE APPLIED
            t["pnl"] = round(move * LEVERAGE, 2)

            # Target Hit
            if not t["partial"] and (curr_p >= t["target"] if t["side"] == "LONG" else curr_p <= t["target"]):
                t["partial"] = True
                t["sl"] = t["entry"]
                save_data()

            # Exit
            if (curr_p <= t["sl"] if t["side"] == "LONG" else curr_p >= t["sl"]):
                t["status"] = "CLOSED"
                t["exit_t"] = datetime.now().strftime("%d/%m %H:%M:%S")
                save_data()

# ================= 5. DASHBOARD UI (FIXED & TESTED) =================

st.subheader("📡 Live Market Intelligence")

# अगर मार्केट वॉच खाली है तो मैसेज दिखाएं
if not market_watch:
    st.warning("Fetching live data from Delta Exchange... Please wait.")
else:
    # दो कॉलम बनाएँ BTC और ETH के लिए
    t_col1, t_col2 = st.columns(2)

    for i, mw in enumerate(market_watch):
        with (t_col1 if i == 0 else t_col2):
            # सिग्नल के हिसाब से कलर तय करें
            b_color = "#2ecc71" if mw["Signal"] == "LONG" else "#e74c3c" if mw["Signal"] == "SHORT" else "#f1c40f"
            
            # HTML कार्ड डिस्प्ले
            st.markdown(f"""
                <div style="padding:20px; border-radius:15px; border-left: 10px solid {b_color}; background-color:#1e1e1e; color:white; margin-bottom:10px; box-shadow: 2px 2px 10px rgba(0,0,0,0.5);">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <h2 style="margin:0; color:white;">{mw['Symbol']}</h2>
                        <span style="background:{b_color}; color:black; padding:4px 12px; border-radius:20px; font-weight:bold; font-size:14px;">{mw['Signal']}</span>
                    </div>
                    <hr style="border:0.5px solid #333; margin:15px 0;">
                    <div style="display:grid; grid-template-columns: 1fr 1fr; gap:15px;">
                        <div>
                            <p style="color:#888; margin:0; font-size:12px; letter-spacing:1px;">PRICE</p>
                            <p style="font-size:24px; font-weight:bold; margin:0; color:white;">${mw['Price']:,}</p>
                        </div>
                        <div>
                            <p style="color:#888; margin:0; font-size:12px; letter-spacing:1px;">VWAP</p>
                            <p style="font-size:20px; margin:0; color:#ddd;">{mw.get('vwap', mw.get('VWAP', 'N/A'))}</p>
                        </div>
                        <div>
                            <p style="color:#888; margin:0; font-size:12px; letter-spacing:1px;">POC (MAX VOL)</p>
                            <p style="font-size:20px; margin:0; color:#f1c40f;">{mw['POC']}</p>
                        </div>
                        <div>
                            <p style="color:#888; margin:0; font-size:12px; letter-spacing:1px;">DELTA FLOW</p>
                            <p style="font-size:20px; margin:0; font-weight:bold; color:{'#2ecc71' if mw['Delta'] > 0 else '#e74c3c'};">
                                {'+' if mw['Delta'] > 0 else ''}{int(mw['Delta'])}
                            </p>
                        </div>
                    </div>
                </div>
            """, unsafe_allow_html=True)

st.divider()

# --- नीचे का ट्रेड मैनेजमेंट सेक्शन ---
st.subheader("📋 Active & Past Trades")

if st.session_state.trades:
    # डेटा को फ्रेश लोड करें
    df_show = pd.DataFrame(st.session_state.trades).copy()
    
    # कॉलम रिनेम (आपके आर्डर के हिसाब से)
    df_show = df_show.rename(columns={
        "pair": "Symbol", "side": "Side", "entry": "Entry", "sl": "SL (Live)",
        "target": "Target", "pnl": "PnL", "entry_t": "Entry T", "exit_t": "Exit T"
    })
    
    # Action Status
    df_show["Action"] = df_show.apply(lambda r: "🔴 Closed" if r["status"] == "CLOSED" else ("✅ T1 Hit" if r["partial"] else "🟢 Running"), axis=1)
    
    final_cols = ["Symbol", "Side", "Entry", "SL (Live)", "Target", "PnL", "Entry T", "Exit T", "Action"]
    
    # टेबल डिस्प्ले
    st.dataframe(df_show[final_cols].sort_index(ascending=False), use_container_width=True, hide_index=True)

    # डाउनलोड
    csv = df_show.to_csv(index=False).encode('utf-8')
    st.download_button("📥 Export History", csv, "trades.csv", "text/csv")
else:
    st.info("Searching for trades based on POC and Delta Flow...")
