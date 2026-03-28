import numpy as np
import random
from collections import defaultdict
import bisect
from dash import Dash, dcc, html
from dash.dependencies import Input, Output
import plotly.graph_objects as go
import threading
import time

np.random.seed(3)

# -----------------------
# PARAMETERS
# -----------------------
N_TRADERS = 200
TICKS = 1000
TICK_SIZE = 0.1
ORDERS_PER_TICK = 10
CANCEL_PROB = 0.08
CANDLE_SIZE = 5
LONG_TERM_DRIFT = 0.00005
PRICE_SCALE = 0.05  # reduce impact for 1-min chart

# -----------------------
# ORDER BOOK (for internal logic, not plotted)
# -----------------------
bids = defaultdict(int)
asks = defaultdict(int)
bid_prices = []
ask_prices = []

#Percentages:
percentages = [0.3,0.2,0.3,0.2] #[trend, mean, panic, noise]

#Deciphering news.json:

def add_order(book, plist, price, vol):
    if price not in book:
        bisect.insort(plist, price)
    book[price] += vol

def remove_order(book, plist, price, vol):
    book[price] -= vol
    if book[price] <= 0:
        del book[price]
        plist.remove(price)

def best_bid():
    return bid_prices[-1] if bid_prices else None

def best_ask():
    return ask_prices[0] if ask_prices else None

def match():
    trades = []
    while bid_prices and ask_prices and best_bid() >= best_ask():
        bp = best_bid()
        ap = best_ask()
        vol = min(bids[bp], asks[ap])
        price = (bp + ap)/2
        trades.append((price, vol))
        remove_order(bids, bid_prices, bp, vol)
        remove_order(asks, ask_prices, ap, vol)
    return trades

# -----------------------
# PERSISTENT SIDE
# -----------------------
last_side = np.random.choice(["buy","sell"])
def persistent_side(p=0.7):
    global last_side
    if np.random.rand() < p:
        return last_side
    else:
        last_side = "buy" if last_side=="sell" else "sell"
        return last_side

# -----------------------
# TRADER CLASS
# -----------------------
class Trader:
    def __init__(self):
        global percentages
        self.type = np.random.choice(
            ["trend","mean","panic","noise"], p=percentages
        )
        self.memory = []

    def act(self, price, ref):
        self.memory.append(price)
        if len(self.memory) > 10:
            self.memory.pop(0)

        if self.type=="trend" and len(self.memory)>3:
            trend = self.memory[-1]-self.memory[-4]
            side = "buy" if trend>0 else "sell"
            vol = np.random.randint(1,5)
            return ("market", side, vol)

        if self.type=="mean":
            side = "sell" if price>ref else "buy"
            vol = np.random.randint(1,4)
            return ("market", side, vol)

        dev = abs(price-ref)/ref
        if self.type=="panic" and dev>0.02 and len(self.memory)>3:
            trend = self.memory[-1]-self.memory[-4]
            side = "buy" if trend>0 else "sell"
            vol = np.random.randint(2,6)
            return ("market", side, vol)

        # Noise trader (limit)
        side = persistent_side()
        offset = -abs(np.random.exponential(0.3)) if side=="buy" else abs(np.random.exponential(0.3))
        p = price + offset
        p = max(0.01, round(p/TICK_SIZE)*TICK_SIZE)
        vol = np.random.randint(1,3)
        return ("limit", side, p, vol)

traders = [Trader() for _ in range(N_TRADERS)]

# -----------------------
# SHARED STATE
# -----------------------
price = 100.0
ref_price = price
prices = []
volume_buy = []
volume_sell = []
vol_buy_candle = 0
vol_sell_candle = 0
candles = []

lock = threading.Lock()

# -----------------------
# SIMULATION THREAD
# -----------------------
def simulation_loop():
    global price, ref_price, prices, volume_buy, volume_sell, vol_buy_candle, vol_sell_candle, candles
    t= 0 #ticks
    while True:
        price *= (1 + LONG_TERM_DRIFT * PRICE_SCALE)

        for _ in range(ORDERS_PER_TICK):
            tr = random.choice(traders)
            action = tr.act(price, ref_price)
            if action[0]=="limit":
                _, side, p, vol = action
                if side=="buy":
                    add_order(bids, bid_prices, p, vol)
                else:
                    add_order(asks, ask_prices, p, vol)
            else:
                _, side, vol = action
                if side=="buy" and ask_prices:
                    ap = best_ask()
                    remove_order(asks, ask_prices, ap, vol)
                    price += (ap - price) * PRICE_SCALE
                    vol_buy_candle += vol
                elif side=="sell" and bid_prices:
                    bp = best_bid()
                    remove_order(bids, bid_prices, bp, vol)
                    price += (bp - price) * PRICE_SCALE
                    vol_sell_candle += vol

        trades = match()
        for p_trade, v_trade in trades:
            price += (p_trade - price) * PRICE_SCALE
            price = max(0.01, price)
            mid = (best_bid() + best_ask())/2 if best_bid() and best_ask() else price
            if p_trade>=mid:
                vol_buy_candle += v_trade
            else:
                vol_sell_candle += v_trade

        for book, plist in [(bids, bid_prices),(asks, ask_prices)]:
            for p_ in plist.copy():
                if np.random.rand()<CANCEL_PROB:
                    remove_order(book, plist, p_,1)

        ref_price = 0.99*ref_price + 0.01*price
        prices.append(price)

        if (t+1)%CANDLE_SIZE==0:
            with lock:
                volume_buy.append(vol_buy_candle)
                volume_sell.append(vol_sell_candle)
                vol_buy_candle = 0
                vol_sell_candle = 0

                # aggregate candle
                chunk = prices[-CANDLE_SIZE:]
                o, h, l, c = chunk[0], max(chunk), min(chunk), chunk[-1]
                candles.append((o,h,l,c))

        time.sleep(0.05)  # slow down to visualize in "real-time"
        t+=1
# -----------------------
# DASH APP
# -----------------------
app = Dash(__name__)
app.layout = html.Div([
    html.H2("Live 1-Min Candlestick Simulation"),
    dcc.Graph(id="live-chart"),
    dcc.Interval(id="interval", interval=500, n_intervals=0)
])

@app.callback(
    Output("live-chart", "figure"),
    Input("interval", "n_intervals")
)
def update_chart(_):
    with lock:
        if len(candles)==0:
            return go.Figure()
        o = [c[0] for c in candles]
        h = [c[1] for c in candles]
        l = [c[2] for c in candles]
        c_ = [c[3] for c in candles]
        vol_buy = volume_buy
        vol_sell = volume_sell

    fig = go.Figure()

    # Candlesticks (top row)
    fig.add_trace(go.Candlestick(
        x=list(range(len(candles))),
        open=o, high=h, low=l, close=c_,
        name="Price",
        yaxis="y1"
    ))

    # Buy volume
    fig.add_trace(go.Bar(
        x=list(range(len(vol_buy))),
        y=vol_buy,
        marker_color='green',
        name='Buy Volume',
        yaxis="y2"
    ))

    # Sell volume
    fig.add_trace(go.Bar(
        x=list(range(len(vol_sell))),
        y=vol_sell,
        marker_color='red',
        name='Sell Volume',
        yaxis="y2"
    ))

    fig.update_layout(
        height=600,
        width=900,
        xaxis_rangeslider_visible=False,
        template='plotly_dark',
        yaxis=dict(domain=[0.3,1]),  # top 70% for price
        yaxis2=dict(domain=[0,0.25], showgrid=False),  # bottom 25% for volume
        barmode='stack'
    )

    return fig

# -----------------------
# START SIMULATION THREAD
# -----------------------
threading.Thread(target=simulation_loop, daemon=True).start()

if __name__=="__main__":
    app.run(debug=True)