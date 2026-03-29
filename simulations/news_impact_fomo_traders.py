import numpy as np
import random
from collections import defaultdict
import bisect
from dash import Dash, dcc, html
from dash.dependencies import Input, Output
import plotly.graph_objects as go
import threading
import time
import json
import os

np.random.seed(3)

# -----------------------
# PARAMETERS
# -----------------------
N_TRADERS = 250
TICK_SIZE = 0.1
ORDERS_PER_TICK = 15
CANCEL_PROB = 0.08
CANDLE_SIZE = 5
LONG_TERM_DRIFT = 0.00005
PRICE_SCALE = 0.05  # per order price impact
news_button_pressed = False

# Order book
bids = defaultdict(int)
asks = defaultdict(int)
bid_prices = []
ask_prices = []

# Trader percentages: [trend, aggressive_trend, mean, panic, aggressive_panic, fundamental, noise]
percentages = [0.2, 0.1, 0.15, 0.2, 0.1, 0.15, 0.1]

# News variables
news_data = []
news_path = os.path.join(os.path.dirname(__file__), "..", "news.json")

# Market bias multiplier
market_bias = 0.0
volatility_mult = 1.0

# -----------------------
# NEWS DECIPHER
# -----------------------
current_news_effect = None
news_candles_remaining = 0
short_term_effect = 1.0
long_term_effect = 1.0

def read_news(news_number):
    global news_data
    with open(news_path, "r") as file:
        data = json.load(file)
        event_info = data[news_number]['event']
        news_data = data[news_number]['effects']['Information Technology']
        print(f"Breaking news:{event_info} | {news_data}")
        return event_info, news_data

def change_percentages(news_data):
    global percentages
    old_panic = percentages[3] + percentages[4]  # panic + aggressive panic

    if news_data < 5:
        new_panic = 1 - (news_data / 5)
    elif news_data > 5:
        new_panic = 1 - (news_data / 10)
    else:
        return

    delta = new_panic - old_panic
    redistribute = -delta

    if news_data > 5:  # bullish
        percentages[0] += 0.5*redistribute
        percentages[1] += 0.2*redistribute
        percentages[2] += 0.1*redistribute
        percentages[5] += 0.2*redistribute
        percentages[6] += 0.0*redistribute
    else:  # bearish
        percentages[0] += 0.1*redistribute
        percentages[1] += 0.1*redistribute
        percentages[2] += 0.2*redistribute
        percentages[3] += 0.3*redistribute
        percentages[4] += 0.3*redistribute
        percentages[6] += 0.0*redistribute

    total = sum(percentages)
    percentages = [max(0, p/total) for p in percentages]

# -----------------------
# ORDER BOOK FUNCTIONS
# -----------------------
def add_order(book, plist, price, vol):
    if price not in book:
        bisect.insort(plist, price)
    book[price] += vol

def remove_order(book, plist, price, vol):
    book[price] -= vol
    if book[price] <= 0:
        del book[price]
        plist.remove(price)

def best_bid(): return bid_prices[-1] if bid_prices else None
def best_ask(): return ask_prices[0] if ask_prices else None

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
        types = ["trend","aggr_trend","mean","panic","aggr_panic","fundamental","noise"]
        self.type = np.random.choice(types, p=percentages)
        self.memory = []

    def act(self, price, ref):
        global market_bias, volatility_mult
        self.memory.append(price)
        if len(self.memory) > 10:
            self.memory.pop(0)

        # Trend trader
        if self.type=="trend" and len(self.memory)>3:
            trend = self.memory[-1]-self.memory[-4]
            side = "buy" if trend>0 else "sell"
            vol = np.random.randint(2,5)
            return ("market", side, vol)

        # Aggressive trend trader
        if self.type=="aggr_trend" and len(self.memory)>3:
            trend = self.memory[-1]-self.memory[-4] + market_bias*price*0.02
            side = "buy" if trend>0 else "sell"
            vol = np.random.randint(5,12)
            return ("market", side, vol)

        # Mean-reversion trader
        if self.type=="mean":
            side = "sell" if price>ref else "buy"
            vol = np.random.randint(1,4)
            return ("market", side, vol)

        # Panic trader
        dev = abs(price-ref)/ref
        if self.type=="panic" and dev>0.01:
            side = "buy" if price<ref else "sell"
            vol = np.random.randint(3,6)
            return ("market", side, vol)

        # Aggressive panic
        if self.type=="aggr_panic" and dev>0.005:
            side = "buy" if price<ref else "sell"
            vol = np.random.randint(6,15)
            return ("market", side, vol)

        # Fundamental trader reacts to news
        if self.type=="fundamental":
            side = "buy" if market_bias>0 else "sell"
            vol = np.random.randint(4,10)
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
# SIMULATION LOOP
# -----------------------
def simulation_loop():
    global price, news_candles_remaining, ref_price, prices, volume_buy, volume_sell
    global vol_buy_candle, vol_sell_candle, candles, news_button_pressed, market_bias

    t = 0
    while True:
        price *= (1 + LONG_TERM_DRIFT * PRICE_SCALE)

        for _ in range(ORDERS_PER_TICK):
            tr = random.choice(traders)
            action = tr.act(price, ref_price)
            if action is None:
                continue

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
                    price += (ap-price)*PRICE_SCALE
                    vol_buy_candle += vol
                elif side=="sell" and bid_prices:
                    bp = best_bid()
                    remove_order(bids, bid_prices, bp, vol)
                    price += (bp-price)*PRICE_SCALE
                    vol_sell_candle += vol

        trades = match()
        for p_trade, v_trade in trades:
            price += (p_trade-price)*PRICE_SCALE
            price = max(0.01, price)
            mid = (best_bid()+best_ask())/2 if best_bid() and best_ask() else price
            if p_trade>=mid:
                vol_buy_candle += v_trade
            else:
                vol_sell_candle += v_trade

        for book, plist in [(bids, bid_prices), (asks, ask_prices)]:
            for p_ in plist.copy():
                if np.random.rand() < CANCEL_PROB:
                    remove_order(book, plist, p_, 1)

        ref_price = 0.99*ref_price + 0.01*price
        prices.append(price)

        if (t+1) % CANDLE_SIZE == 0:
            with lock:
                volume_buy.append(vol_buy_candle)
                volume_sell.append(vol_sell_candle)
                vol_buy_candle = 0
                vol_sell_candle = 0
                chunk = prices[-CANDLE_SIZE:]
                o,h,l,c = chunk[0], max(chunk), min(chunk), chunk[-1]
                candles.append((o,h,l,c))

            if news_candles_remaining > 1:
                news_candles_remaining -= 1
            elif news_candles_remaining == 1:
                change_percentages(long_term_effect)
                news_candles_remaining -= 1

        if news_button_pressed:
            headline, news_data = read_news(random.randint(0,5))
            short_term_effect = news_data[0]
            news_candles_remaining = news_data[1]
            long_term_effect = news_data[2]

            market_bias = (short_term_effect-5)/5
            change_percentages(short_term_effect)
            news_button_pressed = False

        t += 1
        time.sleep(0.05)

# -----------------------
# DASH APP
# -----------------------
app = Dash(__name__)
app.layout = html.Div([
    html.H2("Live 1-Min Candlestick Simulation"),
    dcc.Graph(id="live-chart"),
    dcc.Interval(id="interval", interval=500, n_intervals=0),
    html.Button("Trigger News", id="news-button", n_clicks=0)
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
    fig.add_trace(go.Candlestick(x=list(range(len(candles))), open=o, high=h, low=l, close=c_, name="Price", yaxis="y1"))
    fig.add_trace(go.Bar(x=list(range(len(vol_buy))), y=vol_buy, marker_color='green', name='Buy Volume', yaxis="y2"))
    fig.add_trace(go.Bar(x=list(range(len(vol_sell))), y=vol_sell, marker_color='red', name='Sell Volume', yaxis="y2"))
    fig.update_layout(
        height=600,
        width=900,
        xaxis_rangeslider_visible=False,
        template='plotly_dark',
        yaxis=dict(domain=[0.3,1]),
        yaxis2=dict(domain=[0,0.25], showgrid=False),
        barmode='stack'
    )
    return fig

@app.callback(
    Output("news-button", "children"),
    Input("news-button", "n_clicks")
)
def trigger_news(n_clicks):
    global news_button_pressed
    if n_clicks and n_clicks>0:
        news_button_pressed = True
    return "Trigger News"

threading.Thread(target=simulation_loop, daemon=True).start()

if __name__=="__main__":
    app.run(debug=True)