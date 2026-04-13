import streamlit as st
import pandas as pd
try:
    import plotly.graph_objects as go
except ImportError:
    st.error("Plotly install nahi hui h. Please check requirements.txt")
import requests
try:
    from streamlit_autorefresh import st_autorefresh
except ImportError:
    st.error("Error: streamlit-autorefresh install nahi hui h. requirements.txt check karein.")
    # Dummy function taaki niche ka code crash na ho
    def st_autorefresh(**kwargs):
        pass


# ================= CONFIG =================
st.set_page_config(layout="wide")
st.title("🚀 Delta Pro Paper Trading Dashboard")

st_autorefresh(interval=5000, key="refresh")

TELEGRAM_TOKEN = "YOUR_TELEGRAM_TOKEN"
CHAT_ID = "YOUR_CHAT_ID"


# ================= TELEGRAM ALERT =================
def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

        requests.post(url, data={
            "chat_id": CHAT_ID,
            "text": msg
        })
    except:
        pass


# ================= DELTA API FETCH =================
def get_delta_candles(symbol="BTCUSD", resolution="5m"):
    try:
        # Delta India API URL
        url = "https://delta.exchange"
        
        params = {
            "symbol": symbol,
            "resolution": resolution,
            "add_fvg": True # Agar FVG chahiye toh
        }

        response = requests.get(url, params=params, timeout=10)
        data = response.json()

        # Check if 'result' exists in response
        if "result" in data:
            return data["result"]
        else:
            st.error(f"API Error: {data.get('error', 'Unknown Error')}")
            return [] # Return empty list if no result
            
    except Exception as e:
        st.error(f"Connection Error: {e}")
        return []
# ================= FVG DETECTION =================
def detect_fvg(df):

    bullish_fvg = None
    bearish_fvg = None

    if len(df) < 3:
        return bullish_fvg, bearish_fvg

    if df.iloc[-3]["high"] < df.iloc[-1]["low"]:
        bullish_fvg = (
            df.iloc[-3]["high"],
            df.iloc[-1]["low"]
        )

    if df.iloc[-3]["low"] > df.iloc[-1]["high"]:
        bearish_fvg = (
            df.iloc[-1]["high"],
            df.iloc[-3]["low"]
        )

    return bullish_fvg, bearish_fvg


# ================= SIGNAL GENERATOR =================
def generate_signal(df):

    price = df.iloc[-1]["close"]

    ema20 = df["close"].ewm(span=20).mean().iloc[-1]
    ema50 = df["close"].ewm(span=50).mean().iloc[-1]

    vwap = (
        (df["close"] * df["volume"]).sum()
        /
        df["volume"].sum()
    )

    bullish_fvg, bearish_fvg = detect_fvg(df)

    if price > vwap and ema20 > ema50 and bullish_fvg:
        return "BUY"

    elif price < vwap and ema20 < ema50 and bearish_fvg:
        return "SELL"

    return "HOLD"


# ================= SESSION STATE =================
if "trades" not in st.session_state:
    st.session_state.trades = []

if "last_signal" not in st.session_state:
    st.session_state.last_signal = None


# ================= UI =================
symbol = st.selectbox(
    "Select Pair",
    ["BTCUSDT", "ETHUSDT"]
)


# ================= FETCH DATA =================
candles = get_delta_candles(symbol)

df = pd.DataFrame(candles)

df.columns = [
    "time",
    "open",
    "high",
    "low",
    "close",
    "volume"
]

df["time"] = pd.to_datetime(df["time"], unit="s")


# ================= INDICATORS =================
df["EMA20"] = df["close"].ewm(span=20).mean()

df["EMA50"] = df["close"].ewm(span=50).mean()

df["VWAP"] = (
    (df["close"] * df["volume"]).cumsum()
    /
    df["volume"].cumsum()
)


# ================= SIGNAL =================
signal = generate_signal(df)

current_price = float(df.iloc[-1]["close"])


# ================= ACTIVE TRADE =================
active_trade = next(
    (
        t for t in st.session_state.trades
        if t["status"] == "OPEN"
    ),
    None
)


# ================= NEW ENTRY =================
if signal in ["BUY", "SELL"] and active_trade is None:

    trade = {
        "pair": symbol,
        "signal": signal,
        "entry": current_price,
        "sl": current_price - 200 if signal == "BUY" else current_price + 200,
        "target": current_price + 400 if signal == "BUY" else current_price - 400,
        "status": "OPEN"
    }

    st.session_state.trades.append(trade)

    if st.session_state.last_signal != signal:

        send_telegram(
            f"""
🚀 NEW SIGNAL

Pair: {symbol}
Signal: {signal}
Entry: {current_price}
SL: {trade['sl']}
Target: {trade['target']}
"""
        )

        st.session_state.last_signal = signal


# ================= TRAILING + EXIT =================
for trade in st.session_state.trades:

    if trade["status"] == "OPEN":

        if trade["signal"] == "BUY":

            if current_price > trade["entry"] + 200:
                trade["sl"] = max(
                    trade["sl"],
                    trade["entry"]
                )

            if current_price > trade["entry"] + 300:
                trade["sl"] = max(
                    trade["sl"],
                    trade["entry"] + 100
                )

            if current_price <= trade["sl"]:
                trade["status"] = "SL HIT"
                trade["exit"] = current_price

                send_telegram(f"❌ BUY SL HIT @ {current_price}")

            elif current_price >= trade["target"]:
                trade["status"] = "TARGET HIT"
                trade["exit"] = current_price

                send_telegram(f"🎯 BUY TARGET HIT @ {current_price}")

        elif trade["signal"] == "SELL":

            if current_price < trade["entry"] - 200:
                trade["sl"] = min(
                    trade["sl"],
                    trade["entry"]
                )

            if current_price < trade["entry"] - 300:
                trade["sl"] = min(
                    trade["sl"],
                    trade["entry"] - 100
                )

            if current_price >= trade["sl"]:
                trade["status"] = "SL HIT"
                trade["exit"] = current_price

                send_telegram(f"❌ SELL SL HIT @ {current_price}")

            elif current_price <= trade["target"]:
                trade["status"] = "TARGET HIT"
                trade["exit"] = current_price

                send_telegram(f"🎯 SELL TARGET HIT @ {current_price}")


# ================= CHART =================
fig = go.Figure()

fig.add_trace(go.Candlestick(
    x=df["time"],
    open=df["open"],
    high=df["high"],
    low=df["low"],
    close=df["close"],
    name="Candles"
))

fig.add_trace(go.Scatter(
    x=df["time"],
    y=df["EMA20"],
    mode="lines",
    name="EMA20"
))

fig.add_trace(go.Scatter(
    x=df["time"],
    y=df["EMA50"],
    mode="lines",
    name="EMA50"
))

fig.add_trace(go.Scatter(
    x=df["time"],
    y=df["VWAP"],
    mode="lines",
    name="VWAP"
))


# Entry/SL/Target Lines
if active_trade:

    fig.add_hline(
        y=active_trade["entry"],
        annotation_text="ENTRY"
    )

    fig.add_hline(
        y=active_trade["sl"],
        annotation_text="SL"
    )

    fig.add_hline(
        y=active_trade["target"],
        annotation_text="TARGET"
    )


# Buy Sell Markers
for trade in st.session_state.trades:

    fig.add_trace(go.Scatter(
        x=[df.iloc[-1]["time"]],
        y=[trade["entry"]],
        mode="markers+text",
        text=[trade["signal"]],
        textposition="top center",
        marker=dict(size=12),
        name=trade["signal"]
    ))


st.plotly_chart(
    fig,
    use_container_width=True
)


# ================= ANALYTICS =================
wins = len([
    t for t in st.session_state.trades
    if t["status"] == "TARGET HIT"
])

losses = len([
    t for t in st.session_state.trades
    if t["status"] == "SL HIT"
])

total = wins + losses

win_rate = (
    round((wins / total) * 100, 2)
    if total > 0 else 0
)


pnl = 0

for trade in st.session_state.trades:

    if "exit" in trade:

        if trade["signal"] == "BUY":
            pnl += (
                trade["exit"] -
                trade["entry"]
            )

        else:
            pnl += (
                trade["entry"] -
                trade["exit"]
            )


# ================= DASHBOARD METRICS =================
col1, col2, col3, col4 = st.columns(4)

col1.metric("💰 Total PnL", round(pnl, 2))
col2.metric("📈 Wins", wins)
col3.metric("📉 Losses", losses)
col4.metric("🎯 Win Rate", f"{win_rate}%")


# ================= TRADE TABLE =================
st.subheader("📊 Trade History")

st.dataframe(st.session_state.trades)
