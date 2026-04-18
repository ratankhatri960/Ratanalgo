import requests
import time
import json
import math
import random
from datetime import datetime

# ================= STATE =================
STATE_FILE = "mcx_state.json"

def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {"positions": []}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

state = load_state()

# ================= MCX LIVE SIM (replace with Dhan feed) =================
def get_mcx_price(symbol):

    base = {
        "CRUDEOIL": 6500,
        "NATURALGAS": 280
    }[symbol]

    return base + random.randint(-60, 60)

# ================= MCX OPTION CHAIN MAPPING =================
def get_mcx_option_chain(spot, step=50):

    strikes = []

    for i in range(-10, 11):

        strike = spot + (i * step)

        strikes.append({
            "strike": strike,
            "ce_oi": random.randint(5000, 60000),
            "pe_oi": random.randint(5000, 60000),
            "ce_vol": random.randint(100, 5000),
            "pe_vol": random.randint(100, 5000),
        })

    return strikes

# ================= DELTA MODEL =================
def calc_delta(spot, strike, opt):

    diff = (spot - strike) / spot
    delta = max(min(diff * 5, 1), -1)

    return delta if opt == "CE" else -delta

# ================= AUTO STRIKE SELECTION (REAL LOGIC) =================
def select_strike(chain, spot, signal, delta):

    atm = min(chain, key=lambda x: abs(x["strike"] - spot))["strike"]

    step = 50

    if signal == "BUY":

        if delta > 0.60:
            strike = atm + step   # OTM CE
        elif delta > 0.40:
            strike = atm         # ATM CE
        else:
            strike = atm - step  # ITM CE

        return strike, "CE"

    else:

        if delta < -0.60:
            strike = atm - step   # OTM PE
        elif delta < -0.40:
            strike = atm         # ATM PE
        else:
            strike = atm + step  # ITM PE

        return strike, "PE"

# ================= FAKE BREAKOUT FILTER =================
def fake_filter(delta, ce_oi, pe_oi, direction):

    if direction == "UP":
        if delta < 0.35:
            return False
        if ce_oi < pe_oi:
            return False

    if direction == "DOWN":
        if delta > -0.35:
            return False
        if pe_oi < ce_oi:
            return False

    return True

# ================= SIGNAL ENGINE (ORB + VWAP + EMA + FVG simplified) =================
def generate_signal(price):

    ema20 = price * 1.001
    ema50 = price * 0.999
    vwap = price * 1.0002

    prev_high = price - 20
    next_low = price + 20

    bull_fvg = prev_high < next_low
    bear_fvg = prev_high > next_low

    if ema20 > ema50 and price > vwap and bull_fvg:
        return "BUY", "UP"

    elif ema20 < ema50 and price < vwap and bear_fvg:
        return "SELL", "DOWN"

    return "NO TRADE", None

# ================= EXECUTION =================
def place_trade(symbol, qty, side):

    print(f"ORDER EXECUTED: {side} {symbol} QTY {qty}")

# ================= RISK =================
def calc_qty(capital, risk_pct, sl_distance):
    return max(int((capital * risk_pct) / sl_distance), 1)

# ================= MAIN ENGINE =================
def run():

    SYMBOLS = ["CRUDEOIL", "NATURALGAS"]

    CAPITAL = 10000
    RISK = 0.02

    while True:

        for symbol in SYMBOLS:

            spot = get_mcx_price(symbol)
            chain = get_mcx_option_chain(spot)

            signal, direction = generate_signal(spot)

            print(symbol, spot, signal)

            if signal == "NO TRADE":
                continue

            delta = calc_delta(spot, chain[0]["strike"], "CE")

            strike, opt = select_strike(chain, spot, signal, delta)

            ce_oi = sum(x["ce_oi"] for x in chain) / len(chain)
            pe_oi = sum(x["pe_oi"] for x in chain) / len(chain)

            valid = fake_filter(delta, ce_oi, pe_oi, direction)

            if not valid:
                print("❌ Fake breakout rejected")
                continue

            # ENTRY CONDITIONS
            open_positions = [p for p in state["positions"] if p["status"] == "OPEN"]

            if len(open_positions) == 0:

                entry = spot
                sl = spot * 0.995 if signal == "BUY" else spot * 1.005
                tp = spot * 1.01 if signal == "BUY" else spot * 0.99

                qty = calc_qty(CAPITAL, RISK, abs(entry - sl))

                place_trade(symbol, qty, signal)

                state["positions"].append({
                    "symbol": symbol,
                    "side": signal,
                    "strike": strike,
                    "type": opt,
                    "entry": entry,
                    "sl": sl,
                    "tp": tp,
                    "qty": qty,
                    "status": "OPEN",
                    "time": str(datetime.now())
                })

                save_state(state)

        time.sleep(5)

# ================= START =================
run()
