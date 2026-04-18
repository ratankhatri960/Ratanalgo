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

# --- AUTO RESET: Purani format ki CSV delete karne ke liye (Sirf ek baar chalega) ---
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

# ================= 2. FUNCTIONS =================
def load_history():
    if os.path.exists(CSV_FILE):
        try: return pd.read_csv(CSV_FILE).to_dict('records')
        except: return []
    return []

def save_history(trades):
    if trades:
        pd.DataFrame(trades).to_csv(CSV_FILE, index=False)

def send_telegram(msg):
    try:
        if not TELEGRAM_TOKEN or not CHAT_ID: return
        url = f"https://telegram.org{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=5)
    except: pass

def get_candles(symbol, tf="5m"):
    try:
        now = int(time.time())
        r = requests.get(f"{BASE_URL}/v2/history/candles",
            params={"symbol": symbol, "resolution": tf, "start": now-86400, "end": now},
            timeout=10).json()
        if "result" not in r: return pd.DataFrame()
        df = pd.DataFrame(r["result"]).sort_values("time")
        for c in ["open","high","low","close","volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.dropna()
    except: return pd.DataFrame()

# ================= 3. SESSION =================
if "trades" not in st.session_state:
    st.session_state.trades = load_history()

# ================= 4. ENGINE =================
market_watch = []

for symbol in ["BTCUSD", "ETHUSD"]:
    df = get_candles(symbol, "5m")
    trend_df = get_candles(symbol, "15m")

    if df.empty or trend_df.empty or len(df) < 50: continue

    # VWAP Calculation
    df['date'] = pd.to_datetime(df['time'], unit='s').dt.date
    df['cum_vol'] = df.groupby('date')['volume'].cumsum()
    df['cum_vol_price'] = (df['close'] * df['volume']).groupby(df['date']).cumsum()
    df['vwap'] = df['cum_vol_price'] / df['cum_vol']

    # Fast Delta
    df["delta"] = df["volume"].where(df["close"] > df["open"], -df["volume"])

    curr = df.iloc[-1]
    prev = df.iloc[-2]
    curr_p = float(curr["close"])
    total_delta = df["delta"].tail(5).sum()
    vwap_val = round(curr["vwap"], 2)

    # Trend (15m EMA)
    trend_df["ema20"] = trend_df["close"].ewm(span=20).mean()
    trend_df["ema50"] = trend_df["close"].ewm(span=50).mean()

    bullish = (trend_df.iloc[-1]["ema20"] > trend_df.iloc[-1]["ema50"])
    
    # Signal
    signal = "HOLD"
    if bullish and curr_p > vwap_val and total_delta > 0:
        signal = "LONG"
    elif not bullish and curr_p < vwap_val and total_delta < 0:
        signal = "SHORT"

    market_watch.append({"SYMBOL": symbol, "PRICE": curr_p, "VWAP": vwap_val, "SIGNAL": signal})

    active_t = next((t for t in st.session_state.trades if t["pair"] == symbol and t["status"] == "OPEN"), None)

    # Entry Logic
    is_fresh = signal != "HOLD" 
    entry_trigger = False
    if signal == "LONG": entry_trigger = curr["high"] > prev["high"]
    elif signal == "SHORT": entry_trigger = curr["low"] < prev["low"]

    if is_fresh and active_t is None and entry_trigger:
        # Cooldown check using timestamp
        last_t = next((t for t in reversed(st.session_state.trades) if t["pair"] == symbol), None)
        if last_t:
            try:
                # Convert time string to comparable object
                diff = (time.time() - last_t.get('exit_ts', 0)) / 60
                if diff < COOLDOWN_MIN: continue
            except: pass

        risk_amount = TOTAL_CAPITAL * RISK_PER_TRADE
        sl_dist = curr_p * SL_VAL_PCT
        qty = max(round(risk_amount / sl_dist, 4), 0.0001)

        trade = {
            "pair": symbol, "side": signal, "entry": curr_p, "qty": qty,
            "sl": round(curr_p - sl_dist if signal == "LONG" else curr_p + sl_dist, 2),
            "t1": round(curr_p + (curr_p*T1_VAL_PCT) if signal == "LONG" else curr_p - (curr_p*T1_VAL_PCT), 2),
            "partial": False, "status": "OPEN", 
            "entry_dt": datetime.now().strftime("%d/%m %H:%M"),
            "exit_dt": "-", "exit_ts": 0,
            "entry_index": len(df), "pnl": 0.0
        }
        st.session_state.trades.append(trade)
        save_history(st.session_state.trades)
        send_telegram(f"🚀 {signal} {symbol} @ {curr_p}")

    # Management
    for t in st.session_state.trades:
        if t["status"] == "OPEN" and t["pair"] == symbol:
            pnl_move = (curr_p - t["entry"]) if t["side"] == "LONG" else (t["entry"] - curr_p)
            t["pnl"] = round(pnl_move * t["qty"], 2)

            # T1 Hit
            if not t["partial"]:
                hit = (curr_p >= t["t1"]) if t["side"] == "LONG" else (curr_p <= t["t1"])
                if hit:
                    t["partial"] = True
                    t["qty"] = round(t["qty"] * 0.5, 4)
                    t["sl"] = round(t["entry"] * (1 + TSL_SECURE_PCT) if t["side"] == "LONG" else t["entry"] * (1 - TSL_SECURE_PCT), 2)
                    save_history(st.session_state.trades)

            # Trailing
            if t["partial"]:
                new_sl = prev["low"] if t["side"] == "LONG" else prev["high"]
                if t["side"] == "LONG" and new_sl > t["sl"]: t["sl"] = round(new_sl, 2)
                elif t["side"] == "SHORT" and new_sl < t["sl"]: t["sl"] = round(new_sl, 2)

            # Exit logic (Index check fixed)
            if len(df) > t.get("entry_index", 0):
                exit_hit = (curr["low"] <= t["sl"]) if t["side"] == "LONG" else (curr["high"] >= t["sl"])
                if exit_hit:
                    t["status"], t["exit_dt"], t["exit_ts"] = "CLOSED", datetime.now().strftime("%d/%m %H:%M"), time.time()
                    save_history(st.session_state.trades)
                    send_telegram(f"❌ EXIT {symbol} @ {t['sl']}")

# ================= 5. UI =================
st.subheader("📊 Live Market Watch")
st.table(pd.DataFrame(market_watch))

st.divider()
st.subheader("📋 Active & Closed Trades")

if st.session_state.trades:
    # Header
    h = st.columns([1.2, 0.8, 1, 1, 1, 1, 1.5, 1.5, 1])
    h[0].write("**Symbol**"); h[1].write("**Side**"); h[2].write("**Entry**")
    h[3].write("**SL (Trail)**"); h[4].write("**Target**"); h[5].write("**PnL**")
    h[6].write("**Entry Date/T**"); h[7].write("**Exit Date/T**"); h[8].write("**Action**")

    for i, t in enumerate(st.session_state.trades):
        r = st.columns([1.2, 0.8, 1, 1, 1, 1, 1.5, 1.5, 1])
        r[0].write(f"**{t.get('pair')}**")
        r[1].write(t.get('side'))
        r[2].write(f"{t.get('entry')}")
        r[3].write(f"🛡️ {t.get('sl')}")
        r[4].write(f"🎯 {t.get('t1')}")
        
        pnl = t.get('pnl', 0)
        r[5].write(f":{'green' if pnl >= 0 else 'red'}[{pnl}]")
        
        r[6].write(t.get('entry_dt', '-'))
        r[7].write(t.get('exit_dt', '-'))

        if t["status"] == "OPEN":
            if r[8].button("Exit", key=f"ex_{i}"):
                t["status"], t["exit_dt"], t["exit_ts"] = "CLOSED", datetime.now().strftime("%d/%m %H:%M"), time.time()
                save_history(st.session_state.trades)
                st.rerun()
        else:
            r[8].write("✅")
else:
    st.info("No trades found. Bot is scanning...")

# Sidebar Tools
if st.sidebar.button("🗑️ Clear All History"):
    if os.path.exists(CSV_FILE): os.remove(CSV_FILE)
    st.session_state.trades = []
    st.rerun()
