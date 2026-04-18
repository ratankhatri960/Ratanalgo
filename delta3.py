import streamlit as st
import pandas as pd
import requests
import time
import os
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# ================= 1. CONFIG & SETTINGS =================
st.set_page_config(layout="wide", page_title="Delta AI Pro: Trailing Engine")
st.title("🤖 Delta AI Pro: Volume Delta + Smart Trailing")

st_autorefresh(interval=5000, key="refresh")

TOTAL_CAPITAL = 1000
ALLOCATION = {"BTCUSD": 0.60, "ETHUSD": 0.40}
LEVERAGE = 25
BASE_URL = "https://api.india.delta.exchange"
CSV_FILE = "trailing_trade_history.csv"

SL_VAL_PCT = 0.005
T1_VAL_PCT = 0.005
TSL_SECURE_PCT = 0.00025

# ✅ NEW ADDITIONS
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
    if trades: pd.DataFrame(trades).to_csv(CSV_FILE, index=False)

def send_telegram(msg):
    try:
        if not TELEGRAM_TOKEN or not CHAT_ID: return
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
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

# ================= 3. SESSION STATE =================
if "trades" not in st.session_state:
    st.session_state.trades = load_history()

# ================= 4. MAIN ENGINE =================
market_watch = []

for symbol in ["BTCUSD", "ETHUSD"]:
    df = get_candles(symbol, "5m")
    trend_df = get_candles(symbol, "15m")
    if df.empty or trend_df.empty or len(df) < 50 or len(trend_df) < 50:
        continue

    # ================= FIXED VWAP =================
    df['date'] = pd.to_datetime(df['time'], unit='s').dt.date
    df['cum_vol'] = df.groupby('date')['volume'].cumsum()
    df['cum_vol_price'] = (df['close'] * df['volume']).groupby(df['date']).cumsum()
    df['vwap'] = df['cum_vol_price'] / df['cum_vol']

    # ================= EXISTING LOGIC =================
    df["delta"] = df.apply(lambda x: x["volume"] if x["close"] > x["open"] else -x["volume"], axis=1)
    
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    curr_p = float(curr["close"])
    total_delta = df["delta"].tail(5).sum()
    vwap_val = round(curr["vwap"], 2)
    
    # Trend Check (15m)
    trend_df["ema20"] = trend_df["close"].ewm(span=20).mean()
    trend_df["ema50"] = trend_df["close"].ewm(span=50).mean()
    
    bullish = (trend_df.iloc[-1]["ema20"] > trend_df.iloc[-1]["ema50"]) and \
              (trend_df.iloc[-1]["ema20"] > trend_df.iloc[-2]["ema20"])

    # Signal
    signal = "HOLD"
    if bullish and curr_p > vwap_val and total_delta > 0: signal = "LONG"
    elif not bullish and curr_p < vwap_val and total_delta < 0: signal = "SHORT"

    was_signaled = (trend_df.iloc[-2]["ema20"] > trend_df.iloc[-2]["ema50"]) and (prev["close"] > prev["vwap"])
    is_fresh = signal in ["LONG", "SHORT"] and not was_signaled

    market_watch.append({"SYMBOL": symbol, "PRICE": curr_p, "VWAP": vwap_val, "SIGNAL": signal})

    active_t = next((t for t in st.session_state.trades if t["pair"] == symbol and t["status"] == "OPEN"), None)

    # ================= EXECUTION =================
    if is_fresh and active_t is None:

        # ✅ COOLDOWN
        last_trade = next((t for t in reversed(st.session_state.trades) if t["pair"] == symbol), None)
        if last_trade:
            try:
                last_time = datetime.strptime(last_trade["time"], "%H:%M:%S")
                diff = (datetime.now() - last_time).seconds / 60
                if diff < COOLDOWN_MIN:
                    continue
            except:
                pass

        # ✅ RISK BASED QTY
        risk_amount = TOTAL_CAPITAL * RISK_PER_TRADE
        sl_distance = curr_p * SL_VAL_PCT
        qty = round(risk_amount / sl_distance, 4)

        size_usd = TOTAL_CAPITAL * ALLOCATION[symbol] * LEVERAGE  # kept as-is

        trade = {
            "pair": symbol, "side": signal, "entry": curr_p, "qty": qty, "orig_qty": qty,
            "sl": round(curr_p - sl_distance if signal == "LONG" else curr_p + sl_distance, 2),
            "t1": round(curr_p + (curr_p*T1_VAL_PCT) if signal == "LONG" else curr_p - (curr_p*T1_VAL_PCT), 2),
            "partial": False, "status": "OPEN", "time": datetime.now().strftime("%H:%M:%S"), "pnl": 0.0
        }
        st.session_state.trades.append(trade)
        save_history(st.session_state.trades)
        send_telegram(f"🚀 {signal} {symbol} Entry: {curr_p}")

    # ================= MANAGEMENT =================
    for t in st.session_state.trades:
        if t["status"] == "OPEN" and t["pair"] == symbol:

            pnl_move = (curr_p - t["entry"]) if t["side"] == "LONG" else (t["entry"] - curr_p)
            t["pnl"] = round(pnl_move * t["qty"], 2)

            # T1
            if not t["partial"]:
                if t["side"] == "LONG":
                   hit_t1 = df.iloc[-1]["high"] >= t["t1"]
            else:
                   hit_t1 = df.iloc[-1]["low"] <= t["t1"]
   
            if hit_t1:
                  t["partial"] = True

                  close_qty = t["qty"] / 2
                  t["qty"] = round(t["qty"] - close_qty, 4)
                    shift = t["entry"] * TSL_SECURE_PCT
                    t["sl"] = round(t["entry"] + shift if t["side"] == "LONG" else t["entry"] - shift, 2)
                    save_history(st.session_state.trades)
                    send_telegram(f"💰 T1 HIT {symbol} | 50% Closed | SL Trailed")

            # ✅ REAL TRAILING
            if t["partial"]:
                if t["side"] == "LONG":
                    new_sl = df.iloc[-2]["low"]
                    if new_sl > t["sl"]:
                        t["sl"] = round(new_sl, 2)
                else:
                    new_sl = df.iloc[-2]["high"]
                    if new_sl < t["sl"]:
                        t["sl"] = round(new_sl, 2)

            # ✅ CANDLE SL HIT
            if t["side"] == "LONG":
                exit_hit = df.iloc[-1]["low"] <= t["sl"]
            else:
                exit_hit = df.iloc[-1]["high"] >= t["sl"]

            if exit_hit:
                t["status"], t["exit_price"] = "CLOSED", curr_p
                save_history(st.session_state.trades)
                send_telegram(f"❌ EXIT {symbol} @ {curr_p} | P&L: ${t['pnl']}")

# ================= 5. UI =================
st.subheader("📊 Live Market Watch")
st.table(pd.DataFrame(market_watch))
st.divider()

st.subheader("📋 Active & Closed Trades")
if st.session_state.trades:
    # Header columns setup
    header = st.columns([1.2, 0.8, 1, 1, 1, 1, 1, 1.2, 1])
    header[0].write("**Symbol**")
    header[1].write("**Side**")
    header[2].write("**Entry**")
    header[3].write("**SL (Live)**")
    header[4].write("**Target**")
    header[5].write("**PnL**")
    header[6].write("**Entry T**")
    header[7].write("**Exit T**")
    header[8].write("**Action**")

    for i, t in enumerate(st.session_state.trades):
        row = st.columns([1.2, 0.8, 1, 1, 1, 1, 1, 1.2, 1])
        
        # Symbol & Side
        row[0].write(f"**{t.get('pair')}**")
        row[1].write(t.get('side'))
        
        # Entry Price
        row[2].write(f"{t.get('entry')}")
        
        # --- TRAIL SL LOGIC DISPLAY ---
        # Agar SL trail hua hai toh ye current live SL dikhayega
        sl_val = t.get('sl', 0)
        row[3].write(f"🛡️ {sl_val}")
        
        # Target 1
        row[4].write(f"🎯 {t.get('target1')}")
        
        # PnL with Color
        pnl = t.get('pnl', 0)
        color = "green" if pnl > 0 else "red"
        row[5].write(f":{color}[{pnl}]")
        
        # Times
        row[6].write(f"{t.get('entry_time', '-')}")
        row[7].write(f"{t.get('exit_time', '-')}")

        # Action Button or Status
        if t["status"] == "OPEN":
            if row[8].button(f"Exit", key=f"exit_btn_{i}"):
                t["status"] = "CLOSED"
                t["exit_time"] = datetime.now().strftime("%H:%M:%S")
                t["exit_timestamp"] = time.time()
                save_data(st.session_state.trades)
                st.rerun()
        else:
            row[8].write("✅ Closed")

    # ================= 6. DOWNLOAD SECTION =================
    if st.session_state.trades:
       st.divider()
       # Dataframe ko CSV format mein convert karein
       df_download = pd.DataFrame(st.session_state.trades)
       csv_data = df_download.to_csv(index=False).encode('utf-8')

       # Download Button
       st.download_button(
           label="📥 Download Trade History (CSV)",
           data=csv_data,
           file_name=f"trading_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
           mime="text/csv",
           help="Click here to download all trades in an Excel-friendly CSV format"
       )
