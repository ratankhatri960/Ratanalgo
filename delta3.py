import streamlit as st
import pandas as pd
import requests
import time
import os
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# ================= 1. CONFIG & RESET =================
st.set_page_config(layout="wide", page_title="Delta AI Pro: Trailing Engine")
st.title("🤖 Delta AI Pro: Volume Delta + Smart Trailing")

CSV_FILE = "trailing_trade_history.csv"

# --- AUTO RESET (SAFE ONLY ON FIRST RUN) ---
if "reset_done" not in st.session_state:
    if os.path.exists(CSV_FILE):
        os.remove(CSV_FILE)
    st.session_state.reset_done = True

st_autorefresh(interval=5000, key="refresh")

TOTAL_CAPITAL = 1000
LEVERAGE = 25
BASE_URL = "https://api.india.delta.exchange"

SL_VAL_PCT = 0.005
T1_VAL_PCT = 0.005
TSL_SECURE_PCT = 0.00025
RISK_PER_TRADE = 0.02
COOLDOWN_MIN = 15

TELEGRAM_TOKEN = st.secrets.get("TELEGRAM_TOKEN", "")
CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "")

# ================= 2. SAFETY STATE FIX (NEW) =================
if "last_entry_time" not in st.session_state:
    st.session_state.last_entry_time = {}

# ================= 3. FUNCTIONS =================
def load_history():
    if os.path.exists(CSV_FILE):
        try: 
            return pd.read_csv(CSV_FILE).to_dict('records')
        except: 
            return []
    return []

def save_history(trades):
    if trades:
        pd.DataFrame(trades).to_csv(CSV_FILE, index=False)

def send_telegram(msg):
    try:
        if not TELEGRAM_TOKEN or not CHAT_ID: return
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=5)
    except: pass

def get_candles(symbol, tf="5m"):
    try:
        now = int(time.time())
        r = requests.get(
            f"{BASE_URL}/v2/history/candles",
            params={"symbol": symbol, "resolution": tf, "start": now-86400, "end": now},
            timeout=10
        ).json()

        if "result" not in r:
            return pd.DataFrame()

        df = pd.DataFrame(r["result"]).sort_values("time")
        for c in ["open","high","low","close","volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.dropna()

    except:
        return pd.DataFrame()

# ================= 4. SESSION =================
if "trades" not in st.session_state:
    st.session_state.trades = load_history()

# ================= 5. ENGINE =================
market_watch = []

for symbol in ["BTCUSD", "ETHUSD"]:

    df = get_candles(symbol, "5m")
    trend_df = get_candles(symbol, "15m")

    if df.empty or trend_df.empty or len(df) < 50:
        continue

    # VWAP
    df['date'] = pd.to_datetime(df['time'], unit='s').dt.date
    df['cum_vol'] = df.groupby('date')['volume'].cumsum()
    df['cum_vol_price'] = (df['close'] * df['volume']).groupby(df['date']).cumsum()
    df['vwap'] = df['cum_vol_price'] / df['cum_vol']

    # Delta
    df["delta"] = df["volume"].where(df["close"] > df["open"], -df["volume"])

    curr = df.iloc[-1]
    prev = df.iloc[-2]

    curr_p = float(curr["close"])
    total_delta = df["delta"].tail(5).sum()
    vwap_val = round(curr["vwap"], 2)

    # Trend
    trend_df["ema20"] = trend_df["close"].ewm(span=20).mean()
    trend_df["ema50"] = trend_df["close"].ewm(span=50).mean()
    bullish = trend_df.iloc[-1]["ema20"] > trend_df.iloc[-1]["ema50"]

    # Signal
    signal = "HOLD"
    if bullish and curr_p > vwap_val and total_delta > 0:
        signal = "LONG"
    elif not bullish and curr_p < vwap_val and total_delta < 0:
        signal = "SHORT"

    market_watch.append({
        "SYMBOL": symbol,
        "PRICE": curr_p,
        "VWAP": vwap_val,
        "SIGNAL": signal
    })

    # ================= ENTRY FIX (MAIN BUG FIX) =================
    active_t = next((t for t in st.session_state.trades if t["pair"] == symbol and t["status"] == "OPEN"), None)

    symbol_key = symbol
    now_ts = time.time()
    last_entry = st.session_state.last_entry_time.get(symbol_key, 0)

    cooldown_ok = (now_ts - last_entry) > COOLDOWN_MIN * 60

    entry_trigger = False
    if signal == "LONG":
        entry_trigger = curr["high"] > prev["high"]
    elif signal == "SHORT":
        entry_trigger = curr["low"] < prev["low"]

    is_fresh = signal != "HOLD"

    # ================= SAFE ENTRY =================
    if is_fresh and active_t is None and entry_trigger and cooldown_ok:

        risk_amount = TOTAL_CAPITAL * RISK_PER_TRADE
        sl_dist = curr_p * SL_VAL_PCT
        qty = max(round(risk_amount / sl_dist, 4), 0.0001)

        trade = {
            "pair": symbol,
            "side": signal,
            "entry": curr_p,
            "qty": qty,
            "sl": round(curr_p - sl_dist if signal == "LONG" else curr_p + sl_dist, 2),
            "t1": round(curr_p + (curr_p*T1_VAL_PCT) if signal == "LONG" else curr_p - (curr_p*T1_VAL_PCT), 2),
            "partial": False,
            "status": "OPEN",
            "entry_dt": datetime.now().strftime("%d/%m %H:%M"),
            "exit_dt": "-",
            "exit_ts": 0,
            "entry_index": len(df),
            "pnl": 0.0
        }

        st.session_state.trades.append(trade)
        save_history(st.session_state.trades)

        # ================= ENTRY LOCK FIX =================
        st.session_state.last_entry_time[symbol_key] = now_ts

        send_telegram(f"🚀 {signal} {symbol} @ {curr_p}")

    # ================= MANAGEMENT =================
    for t in st.session_state.trades:

        if t["status"] == "OPEN" and t["pair"] == symbol:

            pnl_move = (curr_p - t["entry"]) if t["side"] == "LONG" else (t["entry"] - curr_p)
            t["pnl"] = round(pnl_move * t["qty"], 2)

            # T1
            if not t["partial"]:
                hit = (curr_p >= t["t1"]) if t["side"] == "LONG" else (curr_p <= t["t1"])
                if hit:
                    t["partial"] = True
                    t["qty"] = round(t["qty"] * 0.5, 4)
                    t["sl"] = round(
                        t["entry"] * (1 + TSL_SECURE_PCT) if t["side"] == "LONG"
                        else t["entry"] * (1 - TSL_SECURE_PCT),
                        2
                    )
                    save_history(st.session_state.trades)

            # Trailing
            if t["partial"]:
                new_sl = prev["low"] if t["side"] == "LONG" else prev["high"]

                if t["side"] == "LONG" and new_sl > t["sl"]:
                    t["sl"] = round(new_sl, 2)
                elif t["side"] == "SHORT" and new_sl < t["sl"]:
                    t["sl"] = round(new_sl, 2)

            # EXIT SAFE
            exit_hit = (curr["low"] <= t["sl"]) if t["side"] == "LONG" else (curr["high"] >= t["sl"])

            if exit_hit:
                t["status"] = "CLOSED"
                t["exit_dt"] = datetime.now().strftime("%d/%m %H:%M:%S")
                t["exit_ts"] = time.time()
                save_history(st.session_state.trades)
                send_telegram(f"❌ EXIT {symbol} @ SL")

# ================= UI =================
st.subheader("📊 Live Market Watch")
st.table(pd.DataFrame(market_watch))
st.divider()

st.subheader("📋 Active & Closed Trades")

st.table(pd.DataFrame(st.session_state.trades))

# ================= DOWNLOAD =================
if st.session_state.trades:
    st.download_button(
        "📥 Download CSV",
        pd.DataFrame(st.session_state.trades).to_csv(index=False).encode(),
        file_name="trading_history.csv",
        mime="text/csv"
    )
