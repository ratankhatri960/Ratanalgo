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
        return {
            "positions": [],
            "orb": {
                "CRUDEOIL": {
                    "high": None,
                    "low": None,
                    "active": False
                },
                "NATURALGAS": {
                    "high": None,
                    "low": None,
                    "active": False
                }
            }
        }

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

state = load_state()

# ================= TIME LOGIC =================
def current_time_minutes():
    now = datetime.now()
    return now.hour * 60 + now.minute

def is_orb_time():
    t = current_time_minutes()
    return 540 <= t <= 555   # 09:00 - 09:15

def after_orb():
    return current_time_minutes() > 555

# ================= MCX PRICE (SIM) =================
def get_mcx_price(symbol):
    base = {
        "CRUDEOIL": 6500,
        "NATURALGAS": 280
    }[symbol]

    # small realistic fluctuation
    return base + random.randint(-40, 40)

# ================= OPTION CHAIN =================
def get_mcx_option_chain(spot, step=50):
    strikes = []
    for i in range(-10, 11):
        strikes.append({
            "strike": spot + (i * step),
            "ce_oi": random.randint(5000, 60000),
            "pe_oi": random.randint(5000, 60000),
        })
    return strikes

# ================= DELTA =================
def calc_delta(spot, strike, opt):
    diff = (spot - strike) / spot
    delta = max(min(diff * 5, 1), -1)
    return delta if opt == "CE" else -delta

# ================= STRIKE SELECTION =================
def select_strike(chain, spot, signal, delta):
    atm = min(chain, key=lambda x: abs(x["strike"] - spot))["strike"]
    step = 50

    if signal == "BUY":
        if delta > 0.60:
            return atm + step, "CE"
        elif delta > 0.40:
            return atm, "CE"
        else:
            return atm - step, "CE"

    else:
        if delta < -0.60:
            return atm - step, "PE"
        elif delta < -0.40:
            return atm, "PE"
        else:
            return atm + step, "PE"

# ================= FAKE BREAKOUT FILTER =================
def fake_filter(delta, ce_oi, pe_oi, direction):
    if direction == "UP":
        if delta < 0.35 or ce_oi < pe_oi:
            return False

    if direction == "DOWN":
        if delta > -0.35 or pe_oi < ce_oi:
            return False

    return True

# ================= SIGNAL ENGINE =================
def generate_signal(price):
    ema20 = price * 1.001
    ema50 = price * 0.999
    vwap = price * 1.0002

    prev_high = price - 20
    next_low = price + 20

    if ema20 > ema50 and price > vwap and prev_high < next_low:
        return "BUY", "UP"

    elif ema20 < ema50 and price < vwap and prev_high > next_low:
        return "SELL", "DOWN"

    return "NO TRADE", None

# ================= ORB ENGINE (FIXED) =================
def update_orb(symbol, price):

    orb = state["orb"][symbol]

    # ORB ACTIVE START
    if is_orb_time():
        orb["active"] = True

    # INIT FIX (VERY IMPORTANT)
    if orb["high"] is None or orb["low"] is None:
        orb["high"] = price
        orb["low"] = price

    # UPDATE ONLY DURING ORB
    if orb["active"]:
        orb["high"] = max(orb["high"], price)
        orb["low"] = min(orb["low"], price)

    state["orb"][symbol] = orb

# ================= EXECUTION =================
def place_trade(symbol, qty, side):
    print(f"ORDER EXECUTED: {side} {symbol} QTY {qty}")

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

            update_orb(symbol, spot)
            orb = state["orb"][symbol]

            signal, direction = generate_signal(spot)

            print(symbol, spot, signal, orb)

            if signal == "NO TRADE":
                continue

            # AFTER ORB ONLY
            if not after_orb():
                continue

            # BREAKOUT VALIDATION
            if signal == "BUY" and spot <= orb["high"]:
                continue
            if signal == "SELL" and spot >= orb["low"]:
                continue

            delta = calc_delta(spot, chain[0]["strike"], "CE")
            strike, opt = select_strike(chain, spot, signal, delta)

            ce_oi = sum(x["ce_oi"] for x in chain) / len(chain)
            pe_oi = sum(x["pe_oi"] for x in chain) / len(chain)

            if not fake_filter(delta, ce_oi, pe_oi, direction):
                print("❌ Fake breakout rejected")
                continue

            open_positions = [p for p in state["positions"] if p["status"] == "OPEN"]

            if len(open_positions) == 0:

                entry = spot
                sl = spot * 0.995 if signal == "BUY" else spot * 1.005

                qty = calc_qty(CAPITAL, RISK, abs(entry - sl))

                place_trade(symbol, qty, signal)

                state["positions"].append({
                    "symbol": symbol,
                    "side": signal,
                    "strike": strike,
                    "type": opt,
                    "entry": entry,
                    "sl": sl,
                    "qty": qty,
                    "status": "OPEN",
                    "time": str(datetime.now())
                })

                save_state(state)

        time.sleep(5)

run()
