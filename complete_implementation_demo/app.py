import numpy as np
import random
from collections import defaultdict
import bisect
import threading
import time
import json
import os
from flask import Flask, render_template, jsonify, request
from dash import Dash, dcc, html, Input, Output, State
import plotly.graph_objects as go

np.random.seed(3)

# --- FLASK CONFIG ---
server = Flask(__name__)
NEWS_PATH = os.path.join(os.path.dirname(__file__), "news.json")

# -----------------------
# PARAMETERS
# -----------------------
N_TRADERS = 250
TICK_SIZE = 0.1
ORDERS_PER_TICK = 15
CANCEL_PROB = 0.08
CANDLE_SIZE = 5
LONG_TERM_DRIFT = 0.00005
PRICE_SCALE = 0.05
news_button_pressed = False

# Order book
bids = defaultdict(int)
asks = defaultdict(int)
bid_prices = []
ask_prices = []

# Trader percentages
percentages = [0.2, 0.1, 0.15, 0.2, 0.1, 0.15, 0.1]

# Market bias multiplier
market_bias = 0.0
volatility_mult = 1.0

# -----------------------
# PORTFOLIO VARIABLES
# -----------------------
user_balance = 100000.0  # Starting with $100k
user_position = 0  # Positive for long, negative for short
user_entry_price = 0.0
user_realized_pnl = 0.0

# -----------------------
# NEWS DECIPHER
# -----------------------
current_news_effect = None
news_candles_remaining = 0
short_term_effect = 1.0
long_term_effect = 1.0


def read_news(news_number):
    with open(NEWS_PATH, "r") as file:
        data = json.load(file)
        event_info = data[news_number]['event']
        news_data_val = data[news_number]['effects']['Information Technology']
        description = data[news_number]['description']
        return event_info, description, news_data_val


def change_percentages(news_data_val):
    global percentages
    old_panic = percentages[3] + percentages[4]

    if news_data_val < 5:
        new_panic = 1 - (news_data_val / 5)
    elif news_data_val > 5:
        new_panic = 1 - (news_data_val / 10)
    else:
        return

    delta = new_panic - old_panic
    redistribute = -delta

    if news_data_val > 5:  # bullish
        percentages[0] += 0.5 * redistribute #["trend", "aggr_trend", "mean", "panic", "aggr_panic", "fundamental", "noise"]
        percentages[1] += 0.2 * redistribute
        percentages[2] += 0.1 * redistribute
        percentages[5] += 0.2 * redistribute
        percentages[6] += 0.0 * redistribute
    else:  # bearish
        percentages[0] += 0.1 * redistribute
        percentages[1] += 0.1 * redistribute
        percentages[2] += 0.2 * redistribute
        percentages[3] += 0.3 * redistribute
        percentages[4] += 0.3 * redistribute
        percentages[6] += 0.0 * redistribute

    total = sum(percentages)
    percentages = [max(0, p / total) for p in percentages]


# --- SHARED MARKET DATA ---
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
# ORDER BOOK FUNCTIONS
# -----------------------
def add_order(book, plist, p, vol):
    if p not in book: bisect.insort(plist, p)
    book[p] += vol


def remove_order(book, plist, p, vol):
    book[p] -= vol
    if book[p] <= 0:
        del book[p]
        plist.remove(p)


def best_bid(): return bid_prices[-1] if bid_prices else None


def best_ask(): return ask_prices[0] if ask_prices else None


def match():
    trades = []
    while bid_prices and ask_prices and best_bid() >= best_ask():
        bp, ap = best_bid(), best_ask()
        vol = min(bids[bp], asks[ap])
        trade_price = (bp + ap) / 2
        trades.append((trade_price, vol))
        remove_order(bids, bid_prices, bp, vol)
        remove_order(asks, ask_prices, ap, vol)
    return trades


last_side = np.random.choice(["buy", "sell"])


def persistent_side(p=0.7):
    global last_side
    if np.random.rand() < p: return last_side
    last_side = "buy" if last_side == "sell" else "sell"
    return last_side


# -----------------------
# TRADER AGENTS
# -----------------------
class Trader:
    def __init__(self):
        global percentages
        types = ["trend", "aggr_trend", "mean", "panic", "aggr_panic", "fundamental", "noise"]
        self.type = np.random.choice(types, p=percentages)
        self.memory = []

    def act(self, current_p, ref):
        global market_bias, volatility_mult
        self.memory.append(current_p)
        if len(self.memory) > 10: self.memory.pop(0)

        if self.type == "trend" and len(self.memory) > 3:
            trend = self.memory[-1] - self.memory[-4]
            return ("market", "buy" if trend > 0 else "sell", np.random.randint(2, 5))

        if self.type == "aggr_trend" and len(self.memory) > 3:
            trend = self.memory[-1] - self.memory[-4] + market_bias * current_p * 0.02
            return ("market", "buy" if trend > 0 else "sell", np.random.randint(5, 12))

        if self.type == "mean":
            return ("market", "sell" if current_p > ref else "buy", np.random.randint(1, 4))

        dev = abs(current_p - ref) / ref
        if self.type == "panic" and dev > (0.01 * volatility_mult):
            return ("market", "buy" if current_p < ref else "sell", np.random.randint(3, 6))

        if self.type == "aggr_panic" and dev > (0.005 * volatility_mult):
            return ("market", "buy" if current_p < ref else "sell", np.random.randint(6, 15))

        if self.type == "fundamental":
            return ("market", "buy" if market_bias > 0 else "sell", np.random.randint(4, 10))

        side = persistent_side()
        offset = -abs(np.random.exponential(0.3)) if side == "buy" else abs(np.random.exponential(0.3))
        p_limit = max(0.01, round((current_p + offset) / TICK_SIZE) * TICK_SIZE)
        return ("limit", side, p_limit, np.random.randint(1, 3))


traders = [Trader() for _ in range(N_TRADERS)]


# -----------------------
# SIMULATION LOOP
# -----------------------
def simulation_loop():
    global price, news_candles_remaining, ref_price, prices, volume_buy, volume_sell
    global vol_buy_candle, vol_sell_candle, candles, market_bias, long_term_effect

    t = 0
    while True:
        price *= (1 + LONG_TERM_DRIFT * PRICE_SCALE)

        with lock:
            for _ in range(ORDERS_PER_TICK):
                tr = random.choice(traders)
                action = tr.act(price, ref_price)
                if not action: continue

                if action[0] == "limit":
                    _, side, p_lim, vol = action
                    if side == "buy":
                        add_order(bids, bid_prices, p_lim, vol)
                    else:
                        add_order(asks, ask_prices, p_lim, vol)
                else:
                    _, side, vol = action
                    if side == "buy" and ask_prices:
                        ap = best_ask()
                        remove_order(asks, ask_prices, ap, vol)
                        price += (ap - price) * PRICE_SCALE
                        vol_buy_candle += vol
                    elif side == "sell" and bid_prices:
                        bp = best_bid()
                        remove_order(bids, bid_prices, bp, vol)
                        price += (bp - price) * PRICE_SCALE
                        vol_sell_candle += vol

            trades = match()
            for p_trade, v_trade in trades:
                price += (p_trade - price) * PRICE_SCALE
                price = max(0.01, price)
                mid = (best_bid() + best_ask()) / 2 if best_bid() and best_ask() else price
                if p_trade >= mid:
                    vol_buy_candle += v_trade
                else:
                    vol_sell_candle += v_trade

            for book, plist in [(bids, bid_prices), (asks, ask_prices)]:
                for p_ in plist.copy():
                    if np.random.rand() < CANCEL_PROB:
                        remove_order(book, plist, p_, 1)

            ref_price = 0.99 * ref_price + 0.01 * price
            prices.append(price)

            if (t + 1) % CANDLE_SIZE == 0:
                volume_buy.append(vol_buy_candle)
                volume_sell.append(vol_sell_candle)
                vol_buy_candle = 0
                vol_sell_candle = 0

                chunk = prices[-CANDLE_SIZE:]
                candles.append((chunk[0], max(chunk), min(chunk), chunk[-1]))

                if len(candles) > 1000:
                    candles.pop(0)
                    volume_buy.pop(0)
                    volume_sell.pop(0)

                if news_candles_remaining > 1:
                    news_candles_remaining -= 1
                elif news_candles_remaining == 1:
                    change_percentages(long_term_effect)
                    news_candles_remaining -= 1
                    market_bias = 0.0

        t += 1
        time.sleep(0.1)


threading.Thread(target=simulation_loop, daemon=True).start()


# -----------------------
# FLASK ROUTES
# -----------------------
@server.route("/")
def home(): return render_template("index.html")


@server.route("/chart", strict_slashes=False)
def chart_page(): return render_template("chart.html")


@server.route("/api/trigger-news", methods=["POST"])
def api_trigger_news():
    global market_bias, news_candles_remaining, long_term_effect, news_button_pressed
    try:
        with open(NEWS_PATH, "r") as f:
            data_len = len(json.load(f))

        random_index = random.randint(0, data_len - 1)
        headline, description, stats = read_news(random_index)

        with lock:
            news_button_pressed = True
            short_term_effect = stats[0]
            news_candles_remaining = stats[1]
            long_term_effect = stats[2]
            market_bias = (short_term_effect - 5) / 5.0
            change_percentages(short_term_effect)

        return jsonify({"status": "success", "headline": headline, "description": description})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


# --- NEW: TRADING ENDPOINTS ---
@server.route("/api/trade", methods=["POST"])
def api_trade():
    global user_balance, user_position, user_entry_price, user_realized_pnl, price
    data = request.json
    action = data.get("action")
    contracts = int(data.get("contracts", 0))

    with lock:
        current_p = price
        qty = contracts if action == "BUY" else -contracts

        if user_position == 0:
            user_position += qty
            user_entry_price = current_p
        elif (user_position > 0 and qty > 0) or (user_position < 0 and qty < 0):
            new_pos = user_position + qty
            user_entry_price = ((user_entry_price * abs(user_position)) + (current_p * abs(qty))) / abs(new_pos)
            user_position = new_pos
        else:
            if abs(qty) <= abs(user_position):
                closed_qty = abs(qty)
                direction = 1 if user_position > 0 else -1
                trade_pnl = (current_p - user_entry_price) * closed_qty * direction

                user_realized_pnl += trade_pnl
                user_balance += trade_pnl
                user_position += qty
                if user_position == 0:
                    user_entry_price = 0.0
            else:
                closed_qty = abs(user_position)
                direction = 1 if user_position > 0 else -1
                trade_pnl = (current_p - user_entry_price) * closed_qty * direction

                user_realized_pnl += trade_pnl
                user_balance += trade_pnl

                user_position += qty
                user_entry_price = current_p

    return jsonify({"status": "success"})


@server.route("/api/portfolio", methods=["GET"])
def api_portfolio():
    global user_balance, user_position, user_entry_price, user_realized_pnl, price
    with lock:
        unrealized_pnl = 0.0
        if user_position != 0:
            direction = 1 if user_position > 0 else -1
            unrealized_pnl = (price - user_entry_price) * abs(user_position) * direction

        return jsonify({
            "balance": user_balance,
            "position": user_position,
            "entry_price": user_entry_price,
            "current_price": price,
            "realized_pnl": user_realized_pnl,
            "unrealized_pnl": unrealized_pnl
        })


# -----------------------
# DASH APP
# -----------------------
def aggregate_candles(base_candles, b_vol, s_vol, window):
    if not base_candles: return [], [], []
    agg_c, agg_b, agg_s = [], [], []
    for i in range(0, len(base_candles), window):
        chunk = base_candles[i: i + window]
        if not chunk: continue
        o = chunk[0][0]
        h = max(c[1] for c in chunk)
        l = min(c[2] for c in chunk)
        c = chunk[-1][3]
        agg_c.append((o, h, l, c))
        agg_b.append(sum(b_vol[i: i + window]))
        agg_s.append(sum(s_vol[i: i + window]))
    return agg_c, agg_b, agg_s


dash_app = Dash(__name__, server=server, url_base_pathname='/dash-chart/')

dash_app.layout = html.Div([
    dcc.Location(id='url', refresh=False),
    dcc.Graph(id="live-chart", config={'scrollZoom': True, 'displayModeBar': False},
              style={'height': '100vh', 'width': '100%'}),
    dcc.Interval(id="interval", interval=1000, n_intervals=0),
], style={'backgroundColor': '#000', 'margin': '0', 'overflow': 'hidden'})


@dash_app.callback(
    Output("live-chart", "figure"),
    [Input("interval", "n_intervals"), Input("url", "search")],
    State("live-chart", "relayoutData")
)
def update_chart(_, search, relayout):
    global user_position, user_entry_price
    try:
        tf = int(search.split('=')[1]) if search else 1
    except:
        tf = 1

    with lock:
        if not candles: return go.Figure()
        base_c, base_b, base_s = list(candles), list(volume_buy), list(volume_sell)
        current_position = user_position
        current_entry_price = user_entry_price

    display_candles, vol_b, vol_s = aggregate_candles(base_c, base_b, base_s, tf)
    indices = list(range(len(display_candles)))

    fig = go.Figure()

    # Draw Candlesticks
    fig.add_trace(go.Candlestick(
        x=indices, open=[c[0] for c in display_candles], high=[c[1] for c in display_candles],
        low=[c[2] for c in display_candles], close=[c[3] for c in display_candles],
        increasing_line_color='#26a69a', decreasing_line_color='#ef5350'
    ))

    # Draw Volume
    fig.add_trace(go.Bar(x=indices, y=vol_b, marker_color='rgba(38, 166, 154, 0.4)', yaxis="y2"))
    fig.add_trace(go.Bar(x=indices, y=vol_s, marker_color='rgba(239, 83, 80, 0.4)', yaxis="y2"))

    # --- ADD ENTRY LINE IF IN A TRADE ---
    if current_position != 0:
        line_color = '#10b981' if current_position > 0 else '#ef4444'
        side_text = "LONG" if current_position > 0 else "SHORT"
        fig.add_hline(
            y=current_entry_price,
            line_dash="dash",
            line_color=line_color,
            annotation_text=f"{side_text} ENTRY: {current_entry_price:.2f}",
            annotation_position="top right",
            annotation_font_color=line_color,
            annotation_font_weight="bold"
        )

    fig.update_layout(
        template='plotly_dark', uirevision=str(tf), dragmode='pan',
        xaxis=dict(rangeslider_visible=False, showgrid=False),
        yaxis=dict(side="right", fixedrange=False, gridcolor='#222'),
        yaxis2=dict(domain=[0, 0.2], showgrid=False, anchor="x", overlaying="y"),
        margin=dict(l=0, r=50, t=10, b=10),
        showlegend=False, paper_bgcolor='#000', plot_bgcolor='#000'
    )
    return fig


if __name__ == "__main__":
    server.run(debug=True, port=5000)