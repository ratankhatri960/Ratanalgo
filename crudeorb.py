import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime, time as dt_time
from streamlit_autorefresh import st_autorefresh

# ================= CONFIG =================
st.set_page_config(layout="wide", page_title="MCX Paper Bot FINAL PRO")
st.title("🤖 MCX ORB + EMA + VWAP (Paper Bot PRO)")

st_autorefresh(interval=8000, key="refresh")

# ================= DHAN =================
DHAN_CLIENT_ID = st.secrets["DHAN_CLIENT_ID"]
DHAN_ACCESS_TOKEN = st.secrets["DHAN_ACCESS_TOKEN"]

HEADERS = {
    "access-token": DHAN_ACCESS_TOKEN,
    "client-id": DHAN_CLIENT_ID
}

SYMBOLS = {
    "CRUDEOIL": 426249,
    "NATURALGAS": 426268
}

TOTAL_CAPITAL = 10000
RISK = 0.02

# ================= STATE =================
if "trades" not in st.session_state:
    st.session_state.trades = []

if "last_candle" not in st.session_state:
    st.session_state.last_candle = {}

# ================= MARKET =================
def is_market_open():
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    return dt_time(9,0) <= now.time() <= dt_time(23,30)

# ================= DATA =================
def get_candles(sec_id):
    try:
        url = "https://api.dhan.co/v2/charts/intraday"
        payload = {
            "securityId": str(sec_id),
            "exchangeSegment": "MCX_COMM",
            "instrument": "FUTCOM",
            "interval": "5"
        }
        r = requests.post(url, json=payload, headers=HEADERS)
        data = r.json()

        df = pd.DataFrame(data["data"])
        df.columns = ["time","open","high","low","close","volume"]
        df["time"] = pd.to_datetime(df["time"], unit="s")

        return df
    except:
        return pd.DataFrame()

# ================= INDICATORS =================
def calculate_orb(df):
    orb_df = df[df["time"].dt.time <= dt_time(9,15)]
    return orb_df["high"].max(), orb_df["low"].min()

def select_strike(price):
    return round(price / 50) * 50

# ================= ENGINE =================
market = []

for name, sec_id in SYMBOLS.items():

    if not is_market_open():
        market.append({"Symbol": name, "Status": "MARKET CLOSED"})
        continue

    df = get_candles(sec_id)

    if df.empty or len(df) < 20:
        market.append({"Symbol": name, "Status": "No Data"})
        continue

    df["ema20"] = df["close"].ewm(span=20).mean()
    df["ema50"] = df["close"].ewm(span=50).mean()
    df["vwap"] = (df["close"] * df["volume"]).cumsum() / df["volume"].cumsum()

    curr = df.iloc[-1]
    price = curr["close"]

    orb_high, orb_low = calculate_orb(df)

    uptrend = curr["ema20"] > curr["ema50"]
    downtrend = curr["ema20"] < curr["ema50"]

    signal = "HOLD"
    entry = sl = target = None
    strike = option = None

    if price > orb_high and uptrend and price > curr["vwap"]:
        signal = "BUY"
        entry = price
        sl = curr["ema50"]
        target = entry + (entry - sl) * 2
        strike = select_strike(price)
        option = "CE"

    elif price < orb_low and downtrend and price < curr["vwap"]:
        signal = "SELL"
        entry = price
        sl = curr["ema50"]
        target = entry - (sl - entry) * 2
        strike = select_strike(price)
        option = "PE"

    market.append({
        "Symbol": name,
        "Price": round(price,2),
        "Signal": signal,
        "Strike": strike,
        "Option": option
    })

    # ===== PAPER TRADE =====
    active = next((t for t in st.session_state.trades if t["symbol"]==name and t["status"]=="OPEN"), None)

    candle_time = curr["time"]

    if signal != "HOLD" and active is None and st.session_state.last_candle.get(name) != candle_time:

        qty = max(int((TOTAL_CAPITAL * RISK) / abs(entry - sl)),1)

        st.session_state.trades.append({
            "symbol": name,
            "side": signal,
            "entry": entry,
            "strike": strike,
            "option": option,
            "sl": round(sl,2),
            "target": round(target,2),
            "qty": qty,
            "status": "OPEN",
            "pnl": 0,
            "entry_time": datetime.now().strftime("%H:%M:%S"),
            "exit_time": "-",
            "partial_done": False
        })

        st.session_state.last_candle[name] = candle_time

    # ===== MANAGEMENT =====
    for t in st.session_state.trades:
        if t["symbol"] == name and t["status"] == "OPEN":

            move = (price - t["entry"]) if t["side"]=="BUY" else (t["entry"] - price)
            t["pnl"] = round(move * t["qty"],2)

            # ===== PARTIAL BOOKING (50%) =====
            if not t["partial_done"]:
                partial_target = t["entry"] + (t["target"] - t["entry"]) * 0.5 if t["side"]=="BUY" else t["entry"] - (t["entry"] - t["target"]) * 0.5

                if (price >= partial_target if t["side"]=="BUY" else price <= partial_target):
                    t["partial_done"] = True
                    t["qty"] = t["qty"] / 2
                    t["sl"] = t["entry"]  # BE move

            # ===== TRAILING SL =====
            if move > (t["entry"] * 0.003):

                gap = t["entry"] * 0.002

                if t["side"] == "BUY":
                    new_sl = price - gap
                    if new_sl > t["sl"]:
                        t["sl"] = round(new_sl, 2)

                else:
                    new_sl = price + gap
                    if new_sl < t["sl"]:
                        t["sl"] = round(new_sl, 2)

            # ===== EXIT =====
            if (price >= t["target"] if t["side"]=="BUY" else price <= t["target"]):
                t["status"] = "CLOSED"
                t["exit_time"] = datetime.now().strftime("%H:%M:%S")

            elif (price <= t["sl"] if t["side"]=="BUY" else price >= t["sl"]):
                t["status"] = "CLOSED"
                t["exit_time"] = datetime.now().strftime("%H:%M:%S")

# ================= UI =================
st.subheader("📊 Market Signals")
st.dataframe(pd.DataFrame(market), use_container_width=True)

st.divider()

st.subheader("📋 Paper Trades")

if st.session_state.trades:
    df = pd.DataFrame(st.session_state.trades)

    df_display = df.rename(columns={
        "sl": "Live SL",
        "strike": "Strike",
        "option": "Option"
    })

    st.dataframe(df_display.sort_index(ascending=False), use_container_width=True)
else:
    st.info("No trades yet")
