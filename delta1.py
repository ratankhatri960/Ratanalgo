import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime, time as dt_time
st.set_page_config(layout="wide")
# ================= CONFIG =================
BASE_URL = "https://api.india.delta.exchange"
SYMBOLS = ["BTCUSD", "ETHUSD"]

TELEGRAM_TOKEN = "8675465625:AAF-wa2a7_6t4HmFsg1tCOsYKgAsjj7LnrU"
TELEGRAM_CHAT_ID = "447597474"

LEVERAGE = 10
BALANCE = 10000

# ================= SESSION INIT =================
if "active_trades" not in st.session_state:
    st.session_state.active_trades = []

if "closed_trades" not in st.session_state:
    st.session_state.closed_trades = []

if "orb" not in st.session_state:
    st.session_state.orb = {}

if "telegram_status" not in st.session_state:
    st.session_state.telegram_status = None

# ================= TELEGRAM =================
def test_telegram():
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        r = requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": "🚀 Bot Connected"
        }, timeout=5)
        st.session_state.telegram_status = (r.status_code == 200)
    except:
        st.session_state.telegram_status = False

def send_telegram(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": msg},
            timeout=5
        )
    except:
        pass

# ================= DATA =================
def get_candles(symbol, tf="5m"):
    try:
        now = int(time.time())
        r = requests.get(
            f"{BASE_URL}/v2/history/candles",
            params={"symbol": symbol, "resolution": tf, "start": now-86400, "end": now},
            timeout=5
        ).json()

        if "result" not in r:
            return pd.DataFrame()

        df = pd.DataFrame(r["result"]).sort_values("time")

        for c in ["open","high","low","close"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")

        return df.dropna()

    except:
        return pd.DataFrame()

def get_price(symbol, df):
    try:
        r = requests.get(f"{BASE_URL}/v2/tickers/{symbol}", timeout=5).json()
        return float(r["result"]["close"])
    except:
        if not df.empty:
            return float(df.iloc[-1]["close"])
        return 0

# ================= UTIL =================
def ema(series, n):
    return series.ewm(span=n, adjust=False).mean()

def calc_qty(price):
    risk = BALANCE * 0.1
    return round((risk * LEVERAGE) / price, 4)

def trade_exists(symbol, strategy):
    for t in st.session_state.active_trades:
        if t["symbol"] == symbol and strategy in t["strategy"]:
            return True
    return False

# ================= ORB =================
def update_orb(symbol, df):
    if df.empty:
        return

    df["dt"] = pd.to_datetime(df["time"], unit="s")
    df["dt"] += pd.Timedelta(hours=5, minutes=30)
    df["t"] = df["dt"].dt.time

    orb_df = df[(df["t"] >= dt_time(23,30)) | (df["t"] <= dt_time(0,30))]

    if orb_df.empty:
        return

    st.session_state.orb[symbol] = {
        "high": float(orb_df["high"].max()),
        "low": float(orb_df["low"].min())
    }

# ================= PARTIAL =================
def partial_booking(trade):
    if trade.get("partial_done"):
        return
    if trade["running_pnl"] >= 100:
        trade["partial_done"] = True
        trade["qty"] /= 2
        send_telegram(f"💰 Partial booked {trade['symbol']}")

# ================= TRAILING =================
def update_sl(trade, price):
    pnl = trade["running_pnl"]
    entry = trade["entry_price"]

    if pnl >= 80:
        trade["sl"] = entry

    if pnl >= 120:
        if trade["side"] == "BUY":
            trade["sl"] = max(trade["sl"], price - 50)
        else:
            trade["sl"] = min(trade["sl"], price + 50)

# ================= CLOSE =================
def close_trade(trade, price):
    trade["exit_price"] = price
    trade["exit_time"] = datetime.now().strftime("%H:%M:%S")
    trade["real_pnl"] = trade["running_pnl"]
    trade["status"] = "CLOSED"

    st.session_state.closed_trades.append(trade)
    st.session_state.active_trades.remove(trade)

    send_telegram(f"✅ Closed {trade['symbol']} PnL {trade['real_pnl']}")

# ================= MANAGE =================
def manage_trades():

    for trade in st.session_state.active_trades[:]:

        symbol = trade["symbol"]

        df = get_candles(symbol, "5m")
        price = get_price(symbol, df)

        trade["running_pnl"] = (
            price - trade["entry_price"]
            if trade["side"] == "BUY"
            else trade["entry_price"] - price
        )

        partial_booking(trade)
        update_sl(trade, price)

        if trade["side"] == "BUY":
            if price <= trade["sl"] or price >= trade["target"]:
                close_trade(trade, price)

        else:
            if price >= trade["sl"] or price <= trade["target"]:
                close_trade(trade, price)
# ================= EMA =================
def check_ema(symbol, df):
    if len(df) < 21:
        return

    df["ema9"] = ema(df["close"], 9)
    df["ema21"] = ema(df["close"], 21)

    prev = df.iloc[-2]
    curr = df.iloc[-1]

    price = curr["close"]

    if prev["ema9"] < prev["ema21"] and curr["ema9"] > curr["ema21"]:

        if not trade_exists(symbol, "EMA"):
            st.session_state.active_trades.append({
                "symbol": symbol,
                "side": "BUY",
                "entry_price": price,
                "entry_time": datetime.now().strftime("%H:%M:%S"),
                "qty": calc_qty(price),
                "strategy": "EMA BUY",
                "sl": price - 100,
                "target": price + 200,
                "running_pnl": 0,
                "real_pnl": 0,
                "status": "OPEN",
                "partial_done": False
            })
            send_telegram(f"📈 EMA BUY {symbol}")

    elif prev["ema9"] > prev["ema21"] and curr["ema9"] < curr["ema21"]:

        if not trade_exists(symbol, "EMA"):
            st.session_state.active_trades.append({
                "symbol": symbol,
                "side": "SELL",
                "entry_price": price,
                "entry_time": datetime.now().strftime("%H:%M:%S"),
                "qty": calc_qty(price),
                "strategy": "EMA SELL",
                "sl": price + 100,
                "target": price - 200,
                "running_pnl": 0,
                "real_pnl": 0,
                "status": "OPEN",
                "partial_done": False
            })
            send_telegram(f"📉 EMA SELL {symbol}")

# ================= ORB =================
def check_orb(symbol, df):
    if len(df) < 2:
        return

    orb = st.session_state.orb.get(symbol)
    if not orb:
        return

    prev = df.iloc[-2]
    curr = df.iloc[-1]

    price = curr["close"]

    if prev["close"] <= orb["high"] and curr["close"] > orb["high"]:

        if not trade_exists(symbol, "ORB"):
            st.session_state.active_trades.append({
                "symbol": symbol,
                "side": "BUY",
                "entry_price": price,
                "entry_time": datetime.now().strftime("%H:%M:%S"),
                "qty": calc_qty(price),
                "strategy": "ORB BUY",
                "sl": prev["low"],
                "target": price + 200,
                "running_pnl": 0,
                "real_pnl": 0,
                "status": "OPEN",
                "partial_done": False
            })
            send_telegram(f"🚀 ORB BUY {symbol}")

    elif prev["close"] >= orb["low"] and curr["close"] < orb["low"]:

        if not trade_exists(symbol, "ORB"):
            st.session_state.active_trades.append({
                "symbol": symbol,
                "side": "SELL",
                "entry_price": price,
                "entry_time": datetime.now().strftime("%H:%M:%S"),
                "qty": calc_qty(price),
                "strategy": "ORB SELL",
                "sl": prev["high"],
                "target": price - 200,
                "running_pnl": 0,
                "real_pnl": 0,
                "status": "OPEN",
                "partial_done": False
            })
            send_telegram(f"🚀 ORB SELL {symbol}")

# ================= UI =================

st.title("🚀 DELTA PRO BOT - FINAL STABLE ENGINE")

test_telegram()

st.subheader("📡 Telegram Status")
st.write("CONNECTED ✅" if st.session_state.telegram_status else "NOT CONNECTED ❌")

rows = []

for s in SYMBOLS:

    df5 = get_candles(s, "5m")
    df15 = get_candles(s, "15m")

    update_orb(s, df15)

    price = get_price(s, df5)

    if not df5.empty:
        df5["ema9"] = ema(df5["close"], 9)
        df5["ema21"] = ema(df5["close"], 21)
        check_ema(s, df5)

    if not df15.empty:
        check_orb(s, df15)

    manage_trades()

    rows.append({
        "SYMBOL": s,
        "PRICE": price,
        "ORB HIGH": st.session_state.orb.get(s, {}).get("high", 0),
        "ORB LOW": st.session_state.orb.get(s, {}).get("low", 0),
        "EMA9": df5.iloc[-1]["ema9"] if not df5.empty else 0,
        "EMA21": df5.iloc[-1]["ema21"] if not df5.empty else 0
    })

st.subheader("📊 MARKET DATA")
st.dataframe(pd.DataFrame(rows), use_container_width=True)

st.subheader("📒 TRADE LOG BOOK")

trade_rows = []

for t in st.session_state.active_trades:

    trade_rows.append({
        "SYMBOL": t.get("symbol", ""),
        "ENTRY PRICE": t.get("entry_price", ""),
        "ENTRY TIME": t.get("entry_time", ""),
        "QTY": t.get("qty", ""),
        "STRATEGY": t.get("strategy", ""),
        "PARTIAL EXIT": t.get("partial_done", False),
        "EXIT PRICE": str(t.get("exit_price", "-")),
        "EXIT TIME": str(t.get("exit_time", "-")),
        "RUNNING PNL": round(t.get("running_pnl", 0), 2),
        "REAL PNL": round(t.get("real_pnl", 0), 2),
        "STATUS": t.get("status", "")
    })

for t in st.session_state.closed_trades:

    trade_rows.append({
        "SYMBOL": t.get("symbol", ""),
        "ENTRY PRICE": t.get("entry_price", ""),
        "ENTRY TIME": t.get("entry_time", ""),
        "QTY": t.get("qty", ""),
        "STRATEGY": t.get("strategy", ""),
        "PARTIAL EXIT": t.get("partial_done", False),
        "EXIT PRICE": t.get("exit_price", "-"),
        "EXIT TIME": t.get("exit_time", "-"),
        "RUNNING PNL": round(t.get("running_pnl", 0), 2),
        "REAL PNL": round(t.get("real_pnl", 0), 2),
        "STATUS": t.get("status", "")
    })

st.dataframe(pd.DataFrame(trade_rows), use_container_width=True)

time.sleep(5)
st.rerun()