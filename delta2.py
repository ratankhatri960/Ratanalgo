import streamlit as st
import pandas as pd
import requests
import time
import os
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# ================= 1. CONFIG =================
st.set_page_config(layout="wide", page_title="Delta AI: FVG + POC Engine")
st.title("🤖 Delta AI Pro: FVG Momentum + POC Volume")

CSV_FILE = "fvg_poc_trade_history.csv"
st_autorefresh(interval=8000, key="refresh") # 8 sec refresh

TOTAL_CAPITAL = 1000
RISK_PER_TRADE = 0.02
SL_PCT = 0.005
T1_PCT = 0.005
COOLDOWN_MIN = 15
BASE_URL = "https://delta.exchange"

# ================= 2. STATE & DATA =================
if "trades" not in st.session_state:
    if os.path.exists(CSV_FILE):
        try: st.session_state.trades = pd.read_csv(CSV_FILE).to_dict('records')
        except: st.session_state.trades = []
    else: st.session_state.trades = []

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
    df['poc'] = df.tail(20).groupby(df['close'].round(2))['volume'].sum().idxmax()
    
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    curr_p = float(curr["close"])
    vwap_val = round(curr['vwap'], 2)
    poc_val = curr['poc']
    delta_val = int(df["delta"].tail(5).sum())

    # FVG Logic
    bull_fvg = df.iloc[-3]["high"] < df.iloc[-1]["low"]
    bear_fvg = df.iloc[-3]["low"] > df.iloc[-1]["high"]

    # 15m Trend
    trend_df["ema20"] = trend_df["close"].ewm(span=20).mean()
    trend_df["ema50"] = trend_df["close"].ewm(span=50).mean()
    bullish_trend = trend_df.iloc[-1]["ema20"] > trend_df.iloc[-1]["ema50"]

    # --- SIGNAL (FVG + POC + TREND) ---
    signal = "HOLD"
    if bullish_trend and curr_p > vwap_val and curr_p > poc_val and bull_fvg and delta_val > 0:
        signal = "LONG"
    elif not bullish_trend and curr_p < vwap_val and curr_p < poc_val and bear_fvg and delta_val < 0:
        signal = "SHORT"

    market_watch.append({"Symbol": symbol, "Price": curr_p, "VWAP": vwap_val, "POC": poc_val, "Delta": delta_val, "Signal": signal})

    # ENTRY EXECUTION
    active = next((t for t in st.session_state.trades if t["pair"] == symbol and t["status"] == "OPEN"), None)
    
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

    # MANAGEMENT (Trailing SL)
    for t in st.session_state.trades:
        if t["status"] == "OPEN" and t["pair"] == symbol:
            move = (curr_p - t["entry"]) if t["side"] == "LONG" else (t["entry"] - curr_p)
            t["pnl"] = round(move * t["qty"], 2)
            
            # T1 Hit: Move SL to Breakeven
            if not t["partial"] and (curr_p >= t["target"] if t["side"] == "LONG" else curr_p <= t["target"]):
                t["partial"], t["sl"] = True, t["entry"]
                save_history()

            # Active Trailing (Prev Candle High/Low)
            if t["partial"]:
                trail_price = prev["low"] if t["side"] == "LONG" else prev["high"]
                if t["side"] == "LONG" and trail_price > t["sl"]: t["sl"] = round(trail_price, 2)
                elif t["side"] == "SHORT" and trail_price < t["sl"]: t["sl"] = round(trail_price, 2)

            # Exit Hit
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
                    <div><p style="color:#888;margin:0;font-size:12px;">DELTA</p><b style="color:{color};">{mw['Delta']}</b></div>
                </div>
            </div>
        """, unsafe_allow_html=True)

st.divider()
st.subheader("📋 Trade Management Dashboard")
if st.session_state.trades:
    df_disp = pd.DataFrame(st.session_state.trades).copy()
    df_disp = df_disp.rename(columns={
        "pair": "Symbol", "side": "Side", "entry": "Entry", "sl": "SL (Live)",
        "target": "Target", "pnl": "PnL", "entry_t": "Entry T", "exit_t": "Exit T"
    })
    df_disp["Action"] = df_disp.apply(lambda r: "🔴 Closed" if r["status"]=="CLOSED" else ("✅ T1 Hit" if r["partial"] else "🟢 Running"), axis=1)
    
    cols = ["Symbol", "Side", "Entry", "SL (Live)", "Target", "PnL", "Entry T", "Exit T", "Action"]
    st.dataframe(df_show := df_disp[cols].sort_index(ascending=False), use_container_width=True, hide_index=True)
    st.download_button("📥 Download Trade History", df_show.to_csv(index=False).encode('utf-8'), "trades.csv", "text/csv")
else:
    st.info("Searching for FVG + POC Momentum...")


