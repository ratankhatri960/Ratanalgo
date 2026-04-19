import streamlit as st
import pandas as pd
import requests
from datetime import datetime, time as dt_time
from streamlit_autorefresh import st_autorefresh

# ================= CONFIG =================
st.set_page_config(layout="wide", page_title="MCX ORB + EMA + VWAP PRO")
st.title("🚀 MCX ORB + EMA + VWAP (DHAN LIVE)")

st_autorefresh(interval=8000, key="refresh")

# ================= DHAN API =================
DHAN_CLIENT_ID = "YOUR_CLIENT_ID"
DHAN_ACCESS_TOKEN = "YOUR_ACCESS_TOKEN"

HEADERS = {
    "access-token": DHAN_ACCESS_TOKEN,
    "client-id": DHAN_CLIENT_ID
}

# ================= SYMBOL MAP =================
SYMBOLS = {
    "CRUDEOIL": 426249,
    "NATURALGAS": 426268
}

# ================= MARKET CHECK =================
def is_market_open():
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    return dt_time(9,0) <= now.time() <= dt_time(23,30)

# ================= GET CANDLES =================
def get_candles(security_id):
    try:
        url = "https://api.dhan.co/v2/charts/intraday"
        payload = {
            "securityId": str(security_id),
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

# ================= ORB =================
def calculate_orb(df):
    orb_df = df[df["time"].dt.time <= dt_time(9,15)]
    return orb_df["high"].max(), orb_df["low"].min()

# ================= ENGINE =================
rows = []

for name, sec_id in SYMBOLS.items():

    if not is_market_open():
        rows.append({"Symbol": name, "Status": "MARKET CLOSED"})
        continue

    df = get_candles(sec_id)

    if df.empty or len(df) < 20:
        rows.append({"Symbol": name, "Status": "No Data"})
        continue

    # ================= INDICATORS =================
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

    # BUY
    if price > orb_high and uptrend and price > curr["vwap"]:
        signal = "BUY"
        entry = price
        sl = curr["ema50"]
        target = entry + (entry - sl) * 2

    # SELL
    elif price < orb_low and downtrend and price < curr["vwap"]:
        signal = "SELL"
        entry = price
        sl = curr["ema50"]
        target = entry - (sl - entry) * 2

    rows.append({
        "Symbol": name,
        "Price": round(price,2),
        "ORB High": round(orb_high,2),
        "ORB Low": round(orb_low,2),
        "EMA20": round(curr["ema20"],2),
        "EMA50": round(curr["ema50"],2),
        "VWAP": round(curr["vwap"],2),
        "Signal": signal,
        "Entry": entry,
        "SL": sl,
        "Target": target
    })

# ================= UI =================
st.subheader("📊 Live MCX Signals")

st.dataframe(pd.DataFrame(rows), use_container_width=True)
