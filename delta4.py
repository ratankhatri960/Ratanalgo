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

st_autorefresh(interval=15000, key="refresh")

TOTAL_CAPITAL = 1000
LEVERAGE = 10
CSV_FILE = "swing_history.csv"
BASE_URL = "https://api.india.delta.exchange"

# ✅ NEW ADDITIONS
RISK_PER_TRADE = 0.02
COOLDOWN_HOURS = 2

# ================= 2. FUNCTIONS =================
def load_data():
    if os.path.exists(CSV_FILE):
        try: return pd.read_csv(CSV_FILE).to_dict('records')
        except: return []
    return []

def save_data(trades):
    if trades: pd.DataFrame(trades).to_csv(CSV_FILE, index=False)

def get_candles(symbol, tf="1h"):
    try:
        now = int(time.time())
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

# ================= 4. SWING ENGINE =================
market_watch = []

for symbol in ["BTCUSD", "ETHUSD"]:
    df = get_candles(symbol, "1h")
    if df.empty or len(df) < 200: continue

    # ================= FIXED VWAP =================
    df['date'] = pd.to_datetime(df['time'], unit='s').dt.date
    df['cum_vol'] = df.groupby('date')['volume'].cumsum()
    df['cum_vol_price'] = (df['close'] * df['volume']).groupby(df['date']).cumsum()
    df['VWAP'] = df['cum_vol_price'] / df['cum_vol']

    # ================= EXISTING =================
    df["EMA200"] = df["close"].ewm(span=200, adjust=False).mean()
    
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    old = df.iloc[-3]
    curr_p = float(curr["close"])

    # OB
    bull_ob = df.iloc[-5:-2]["low"].min() if df.iloc[-1]["close"] > df.iloc[-3]["high"] else 0
    bear_ob = df.iloc[-5:-2]["high"].max() if df.iloc[-1]["close"] < df.iloc[-3]["low"] else 0

    # ✅ OB proximity
    near_bull_ob = abs(curr_p - bull_ob)/curr_p < 0.01 if bull_ob else False
    near_bear_ob = abs(curr_p - bear_ob)/curr_p < 0.01 if bear_ob else False

    # FVG
    bull_fvg = old["high"] < curr["low"]
    bear_fvg = old["low"] > curr["high"]

    # ✅ Trend slope improvement
    trend_up = curr["EMA200"] > df.iloc[-2]["EMA200"]

    signal = "HOLD"
    entry_now = False

    if curr_p > curr["EMA200"] and bull_fvg and near_bull_ob and trend_up:
        signal = "SWING LONG"
        momentum = curr["close"] > prev["high"]
        if prev["close"] <= curr["VWAP"] and momentum:
            entry_now = True

    elif curr_p < curr["EMA200"] and bear_fvg and near_bear_ob and not trend_up:
        signal = "SWING SHORT"
        momentum = curr["close"] < prev["low"]
        if prev["close"] >= curr["VWAP"] and momentum:
            entry_now = True

    market_watch.append({
        "SYMBOL": symbol, "PRICE": curr_p,
        "EMA200": round(curr["EMA200"], 2), "SIGNAL": signal
    })

    active_t = next((t for t in st.session_state.trades if t["status"] == "OPEN" and t["pair"] == symbol), None)

    # ================= EXECUTION =================
    if entry_now and active_t is None:

        # ✅ COOLDOWN
        last_trade = next((t for t in reversed(st.session_state.trades) if t["pair"] == symbol), None)
        if last_trade:
            try:
                last_time = datetime.strptime(last_trade["time"], "%Y-%m-%d %H:%M")
                diff = (datetime.now() - last_time).seconds / 3600
                if diff < COOLDOWN_HOURS:
                    continue
            except:
                pass

        # ✅ RISK BASED QTY
        sl_pct = 0.03
        risk_amount = TOTAL_CAPITAL * RISK_PER_TRADE
        sl_distance = curr_p * sl_pct
        qty = round(risk_amount / sl_distance, 4)

        new_trade = {
            "pair": symbol, "side": "BUY" if "LONG" in signal else "SELL", "entry": curr_p,
            "qty": qty,
            "sl": round(curr_p * 0.97 if "LONG" in signal else curr_p * 1.03, 2),
            "target": round(curr_p * 1.05 if "LONG" in signal else curr_p * 0.95, 2),
            "status": "OPEN", "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "pnl": 0.0
        }
        st.session_state.trades.append(new_trade)
        save_data(st.session_state.trades)

    # ================= MANAGEMENT =================
    for t in st.session_state.trades:
        if t["status"] == "OPEN" and t["pair"] == symbol:
            move = (curr_p - t["entry"]) if t["side"] == "BUY" else (t["entry"] - curr_p)
            t["pnl"] = round(move * t["qty"], 2)

            # ✅ TRAILING SL
            if t["side"] == "BUY":
                new_sl = df.iloc[-2]["low"]
                if new_sl > t["sl"]:
                    t["sl"] = round(new_sl, 2)
            else:
                new_sl = df.iloc[-2]["high"]
                if new_sl < t["sl"]:
                    t["sl"] = round(new_sl, 2)

            # ✅ CANDLE BASED EXIT
            if t["side"] == "BUY":
                hit_sl = df.iloc[-1]["low"] <= t["sl"]
            else:
                hit_sl = df.iloc[-1]["high"] >= t["sl"]

            if (t["side"] == "BUY" and curr_p >= t["target"]) or (t["side"] == "SELL" and curr_p <= t["target"]):
                t["status"] = "CLOSED (TARGET)"
                save_data(st.session_state.trades)

            elif hit_sl:
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
