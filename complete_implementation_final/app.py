import numpy as np
import random
from collections import defaultdict
import bisect
import threading
import time
import json
import os
import urllib.parse
from flask import Flask, render_template, jsonify, request
from dash import Dash, dcc, html, Input, Output, State
import plotly.graph_objects as go

np.random.seed(3)

# --- FLASK CONFIG ---
server = Flask(__name__)
NEWS_PATH = os.path.join(os.path.dirname(__file__), "news.json")

# -----------------------
# PARAMETERS & SECTORS
# -----------------------
N_TRADERS = 250
TICK_SIZE = 0.1
ORDERS_PER_TICK = 15
CANCEL_PROB = 0.08
CANDLE_SIZE = 5
LONG_TERM_DRIFT = 0.00005
PRICE_SCALE = 0.05

SECTORS = [
    "Information Technology", "Health Care", "Financials",
    "Energy", "Industrials", "Consumer Discretionary", "Utilities"
]

# -----------------------
# PORTFOLIO VARIABLES (Per Sector)
# -----------------------
user_balance = 100000.0
user_realized_pnl = 0.0
user_positions = {s: 0 for s in SECTORS + ["Total Market"]}
user_entry_prices = {s: 0.0 for s in SECTORS + ["Total Market"]}
user_impact_enabled = False  # Toggle for market impact

lock = threading.Lock()


# -----------------------
# MARKET / ORDER BOOK LOGIC
# -----------------------
def add_order(book, plist, p, vol):
    if p not in book: bisect.insort(plist, p)
    book[p] += vol


def remove_order(book, plist, p, vol):
    book[p] -= vol
    if book[p] <= 0:
        del book[p]
        plist.remove(p)


last_side = np.random.choice(["buy", "sell"])


def persistent_side(p=0.7):
    global last_side
    if np.random.rand() < p: return last_side
    last_side = "buy" if last_side == "sell" else "sell"
    return last_side


# -----------------------
# THE MARKET CLASS
# -----------------------
class Market:
    def __init__(self, name):
        self.name = name
        self.price = 100.0
        self.ref_price = 100.0
        self.bids = defaultdict(int)
        self.asks = defaultdict(int)
        self.bid_prices = []
        self.ask_prices = []
        self.prices = []
        self.volume_buy = []
        self.volume_sell = []
        self.vol_buy_candle = 0
        self.vol_sell_candle = 0
        self.candles = []

        self.market_bias = 0.0
        self.news_candles_remaining = 0
        self.long_term_effect = 1.0
        self.volatility_mult = 1.0
        self.percentages = [0.2, 0.1, 0.15, 0.2, 0.1, 0.15, 0.1]

        self.traders = [Trader(self) for _ in range(N_TRADERS)]

    def change_percentages(self, news_data_val):
        old_panic = self.percentages[3] + self.percentages[4]
        if news_data_val < 5:
            new_panic = 1 - (news_data_val / 5)
        elif news_data_val > 5:
            new_panic = 1 - (news_data_val / 10)
        else:
            return

        delta = new_panic - old_panic
        redistribute = -delta

        if news_data_val > 5:
            self.percentages[0] += 0.5 * redistribute
            self.percentages[1] += 0.2 * redistribute
            self.percentages[2] += 0.1 * redistribute
            self.percentages[5] += 0.2 * redistribute
        else:
            self.percentages[0] += 0.1 * redistribute
            self.percentages[1] += 0.1 * redistribute
            self.percentages[2] += 0.2 * redistribute
            self.percentages[3] += 0.3 * redistribute
            self.percentages[4] += 0.3 * redistribute

        total = sum(self.percentages)
        self.percentages = [max(0, p / total) for p in self.percentages]

        types = ["trend", "aggr_trend", "mean", "panic", "aggr_panic", "fundamental", "noise"]
        for t in self.traders:
            t.type = np.random.choice(types, p=self.percentages)


class Trader:
    def __init__(self, mkt):
        self.mkt = mkt
        self.type = np.random.choice(["trend", "aggr_trend", "mean", "panic", "aggr_panic", "fundamental", "noise"],
                                     p=self.mkt.percentages)
        self.memory = []

    def act(self, current_p, ref):
        self.memory.append(current_p)
        if len(self.memory) > 10: self.memory.pop(0)

        # Trend traders (Same for all sectors)
        if self.type == "trend" and len(self.memory) > 3:
            trend = self.memory[-1] - self.memory[-4]
            return ("market", "buy" if trend > 0 else "sell", np.random.randint(2, 5))

        if self.type == "aggr_trend" and len(self.memory) > 3:
            trend = self.memory[-1] - self.memory[-4] + self.mkt.market_bias * current_p * 0.02
            return ("market", "buy" if trend > 0 else "sell", np.random.randint(5, 12))

        # Mean reversion traders (Same for all sectors)
        if self.type == "mean":
            return ("market", "sell" if current_p > ref else "buy", np.random.randint(1, 4))

        dev = abs(current_p - ref) / ref

        # --- SPLIT LOGIC: Tech gets the old behavior, everything else gets the fixed behavior ---
        is_tech = (self.mkt.name == "Information Technology")

        if self.type == "panic" and dev > (0.01 * self.mkt.volatility_mult):
            if is_tech:
                # OLD LOGIC (Value investing / "Buy the dip" during crashes)
                return ("market", "buy" if current_p < ref else "sell", np.random.randint(3, 6))
            else:
                # NEW LOGIC (Actual panic / FOMO buying)
                return ("market", "buy" if current_p > ref else "sell", np.random.randint(3, 6))

        if self.type == "aggr_panic" and dev > (0.005 * self.mkt.volatility_mult):
            if is_tech:
                # OLD LOGIC
                return ("market", "buy" if current_p < ref else "sell", np.random.randint(6, 15))
            else:
                # NEW LOGIC
                return ("market", "buy" if current_p > ref else "sell", np.random.randint(6, 15))

        if self.type == "fundamental":
            if is_tech:
                # OLD LOGIC (Permabear: spams sell orders when no news bias is present)
                return ("market", "buy" if self.mkt.market_bias > 0 else "sell", np.random.randint(4, 10))
            else:
                # NEW LOGIC (Neutral/DCA accumulator when no news bias is present)
                if self.mkt.market_bias == 0.0:
                    if np.random.rand() < 0.10:
                        return ("market", "buy", np.random.randint(1, 3))
                    return None
                return ("market", "buy" if self.mkt.market_bias > 0 else "sell", np.random.randint(4, 10))

        # Noise traders / Market Makers (Same for all sectors)
        side = persistent_side()
        offset = -abs(np.random.exponential(0.3)) if side == "buy" else abs(np.random.exponential(0.3))
        p_limit = max(0.01, round((current_p + offset) / TICK_SIZE) * TICK_SIZE)
        return ("limit", side, p_limit, np.random.randint(1, 3))


markets = {s: Market(s) for s in SECTORS}
total_market = Market("Total Market")


# -----------------------
# SIMULATION LOOP
# -----------------------
def simulation_loop():
    t = 0
    while True:
        with lock:
            for name, mkt in markets.items():
                mkt.price *= (1 + LONG_TERM_DRIFT * PRICE_SCALE)

                for _ in range(ORDERS_PER_TICK):
                    tr = random.choice(mkt.traders)
                    action = tr.act(mkt.price, mkt.ref_price)
                    if not action: continue

                    if action[0] == "limit":
                        _, side, p_lim, vol = action
                        if side == "buy":
                            add_order(mkt.bids, mkt.bid_prices, p_lim, vol)
                        else:
                            add_order(mkt.asks, mkt.ask_prices, p_lim, vol)
                    else:
                        _, side, vol = action
                        if side == "buy" and mkt.ask_prices:
                            ap = mkt.ask_prices[0]
                            remove_order(mkt.asks, mkt.ask_prices, ap, vol)
                            mkt.price += (ap - mkt.price) * PRICE_SCALE
                            mkt.vol_buy_candle += vol
                        elif side == "sell" and mkt.bid_prices:
                            bp = mkt.bid_prices[-1]
                            remove_order(mkt.bids, mkt.bid_prices, bp, vol)
                            mkt.price += (bp - mkt.price) * PRICE_SCALE
                            mkt.vol_sell_candle += vol

                trades = []
                while mkt.bid_prices and mkt.ask_prices and mkt.bid_prices[-1] >= mkt.ask_prices[0]:
                    bp, ap = mkt.bid_prices[-1], mkt.ask_prices[0]
                    vol = min(mkt.bids[bp], mkt.asks[ap])
                    trade_price = (bp + ap) / 2
                    trades.append((trade_price, vol))
                    remove_order(mkt.bids, mkt.bid_prices, bp, vol)
                    remove_order(mkt.asks, mkt.ask_prices, ap, vol)

                for p_trade, v_trade in trades:
                    mkt.price += (p_trade - mkt.price) * PRICE_SCALE
                    mkt.price = max(0.01, mkt.price)
                    mid = (mkt.bid_prices[-1] + mkt.ask_prices[
                        0]) / 2 if mkt.bid_prices and mkt.ask_prices else mkt.price
                    if p_trade >= mid:
                        mkt.vol_buy_candle += v_trade
                    else:
                        mkt.vol_sell_candle += v_trade

                for book, plist in [(mkt.bids, mkt.bid_prices), (mkt.asks, mkt.ask_prices)]:
                    for p_ in plist.copy():
                        if np.random.rand() < CANCEL_PROB:
                            remove_order(book, plist, p_, 1)

                mkt.ref_price = 0.99 * mkt.ref_price + 0.01 * mkt.price
                mkt.prices.append(mkt.price)

                if mkt.news_candles_remaining > 1:
                    mkt.news_candles_remaining -= 1
                elif mkt.news_candles_remaining == 1:
                    mkt.change_percentages(mkt.long_term_effect)
                    mkt.news_candles_remaining -= 1
                    mkt.market_bias = 0.0

            avg_price = sum(m.price for m in markets.values()) / len(markets)
            total_market.price = avg_price
            total_market.prices.append(avg_price)
            total_market.vol_buy_candle += sum(m.vol_buy_candle for m in markets.values())
            total_market.vol_sell_candle += sum(m.vol_sell_candle for m in markets.values())

            if (t + 1) % CANDLE_SIZE == 0:
                all_markets = list(markets.values()) + [total_market]
                for mkt in all_markets:
                    mkt.volume_buy.append(mkt.vol_buy_candle)
                    mkt.volume_sell.append(mkt.vol_sell_candle)
                    mkt.vol_buy_candle = 0
                    mkt.vol_sell_candle = 0

                    if len(mkt.prices) >= CANDLE_SIZE:
                        chunk = mkt.prices[-CANDLE_SIZE:]
                        mkt.candles.append((chunk[0], max(chunk), min(chunk), chunk[-1]))

                    # PREVENT MEMORY LEAK: Keep raw prices short
                    if len(mkt.prices) > 50:
                        mkt.prices = mkt.prices[-50:]

                    # Store plenty of candles for higher timeframes
                    if len(mkt.candles) > 15000:
                        mkt.candles = mkt.candles[-15000:]
                        mkt.volume_buy = mkt.volume_buy[-15000:]
                        mkt.volume_sell = mkt.volume_sell[-15000:]

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
    try:
        with open(NEWS_PATH, "r") as f:
            news_list = json.load(f)

        random_index = random.randint(0, len(news_list) - 1)
        event_data = news_list[random_index]
        headline = event_data['event']
        description = event_data['description']
        effects = event_data.get('effects', {})

        with lock:
            for sector_name, stats in effects.items():
                if sector_name in markets:
                    mkt = markets[sector_name]
                    short_term_effect = stats[0]
                    mkt.news_candles_remaining = stats[1]
                    mkt.long_term_effect = stats[2]
                    mkt.market_bias = (short_term_effect - 5) / 5.0
                    mkt.change_percentages(short_term_effect)

        return jsonify({"status": "success", "headline": headline, "description": description})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@server.route("/api/toggle-impact", methods=["POST"])
def api_toggle_impact():
    global user_impact_enabled
    with lock:
        user_impact_enabled = not user_impact_enabled
    return jsonify({"status": "success", "enabled": user_impact_enabled})


@server.route("/api/trade", methods=["POST"])
def api_trade():
    global user_balance, user_realized_pnl
    data = request.json
    action = data.get("action")
    contracts = int(data.get("contracts", 0))
    sector = data.get("sector", "Total Market")

    with lock:
        qty = contracts if action == "BUY" else -contracts

        # --- NEW: MARKET IMPACT LOGIC ---
        if user_impact_enabled:
            # If Total Market, divide the order equally across all sectors
            markets_to_impact = [markets[sector]] if sector != "Total Market" else list(markets.values())
            vol_per_market = abs(qty) // len(markets_to_impact) if sector == "Total Market" else abs(qty)

            for m in markets_to_impact:
                remaining_vol = vol_per_market
                if action == "BUY":
                    while remaining_vol > 0 and m.ask_prices:
                        ap = m.ask_prices[0]
                        take_vol = min(remaining_vol, m.asks[ap])
                        remove_order(m.asks, m.ask_prices, ap, take_vol)
                        m.price += (ap - m.price) * PRICE_SCALE
                        m.vol_buy_candle += take_vol
                        remaining_vol -= take_vol
                else:  # SELL
                    while remaining_vol > 0 and m.bid_prices:
                        bp = m.bid_prices[-1]
                        take_vol = min(remaining_vol, m.bids[bp])
                        remove_order(m.bids, m.bid_prices, bp, take_vol)
                        m.price += (bp - m.price) * PRICE_SCALE
                        m.vol_sell_candle += take_vol
                        remaining_vol -= take_vol
        # --------------------------------

        current_p = total_market.price if sector == "Total Market" else markets[sector].price

        u_pos = user_positions[sector]
        u_entry = user_entry_prices[sector]

        if u_pos == 0:
            user_positions[sector] += qty
            user_entry_prices[sector] = current_p
        elif (u_pos > 0 and qty > 0) or (u_pos < 0 and qty < 0):
            new_pos = u_pos + qty
            user_entry_prices[sector] = ((u_entry * abs(u_pos)) + (current_p * abs(qty))) / abs(new_pos)
            user_positions[sector] = new_pos
        else:
            if abs(qty) <= abs(u_pos):
                closed_qty = abs(qty)
                direction = 1 if u_pos > 0 else -1
                trade_pnl = (current_p - u_entry) * closed_qty * direction

                user_realized_pnl += trade_pnl
                user_balance += trade_pnl
                user_positions[sector] += qty
                if user_positions[sector] == 0:
                    user_entry_prices[sector] = 0.0
            else:
                closed_qty = abs(u_pos)
                direction = 1 if u_pos > 0 else -1
                trade_pnl = (current_p - u_entry) * closed_qty * direction

                user_realized_pnl += trade_pnl
                user_balance += trade_pnl
                user_positions[sector] += qty
                user_entry_prices[sector] = current_p

    return jsonify({"status": "success"})


@server.route("/api/portfolio", methods=["GET"])
def api_portfolio():
    sector = request.args.get("sector", "Total Market")

    with lock:
        current_p = total_market.price if sector == "Total Market" else markets[sector].price
        u_pos = user_positions.get(sector, 0)
        u_entry = user_entry_prices.get(sector, 0.0)

        unrealized_pnl = 0.0
        if u_pos != 0:
            direction = 1 if u_pos > 0 else -1
            unrealized_pnl = (current_p - u_entry) * abs(u_pos) * direction

        return jsonify({
            "balance": user_balance,
            "position": u_pos,
            "entry_price": u_entry,
            "current_price": current_p,
            "realized_pnl": user_realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "sector": sector
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
    tf = 1
    sector = "Total Market"

    if search:
        params = urllib.parse.parse_qs(search.lstrip('?'))
        if 'tf' in params: tf = int(params['tf'][0])
        if 'sector' in params: sector = params['sector'][0]

    with lock:
        mkt = total_market if sector == "Total Market" else markets.get(sector, total_market)
        if not mkt.candles: return go.Figure()

        base_c, base_b, base_s = list(mkt.candles), list(mkt.volume_buy), list(mkt.volume_sell)
        current_position = user_positions.get(sector, 0)
        current_entry_price = user_entry_prices.get(sector, 0.0)

    display_candles, vol_b, vol_s = aggregate_candles(base_c, base_b, base_s, tf)

    # --- ENFORCE MAXIMUM VISIBLE CANDLES ---
    MAX_VISIBLE = 300
    display_candles = display_candles[-MAX_VISIBLE:]
    vol_b = vol_b[-MAX_VISIBLE:]
    vol_s = vol_s[-MAX_VISIBLE:]

    indices = list(range(len(display_candles)))

    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=indices, open=[c[0] for c in display_candles], high=[c[1] for c in display_candles],
        low=[c[2] for c in display_candles], close=[c[3] for c in display_candles],
        increasing_line_color='#26a69a', decreasing_line_color='#ef5350'
    ))

    fig.add_trace(go.Bar(x=indices, y=vol_b, marker_color='rgba(38, 166, 154, 0.4)', yaxis="y2"))
    fig.add_trace(go.Bar(x=indices, y=vol_s, marker_color='rgba(239, 83, 80, 0.4)', yaxis="y2"))

    if current_position != 0:
        line_color = '#10b981' if current_position > 0 else '#ef4444'
        side_text = "LONG" if current_position > 0 else "SHORT"
        fig.add_hline(
            y=current_entry_price, line_dash="dash", line_color=line_color,
            annotation_text=f"{side_text} ENTRY: {current_entry_price:.2f}",
            annotation_position="top right", annotation_font_color=line_color, annotation_font_weight="bold"
        )

    fig.update_layout(
        template='plotly_dark', uirevision=str(tf) + sector, dragmode='pan',
        xaxis=dict(rangeslider_visible=False, showgrid=False),
        yaxis=dict(side="right", fixedrange=False, gridcolor='#222'),
        yaxis2=dict(domain=[0, 0.2], showgrid=False, anchor="x", overlaying="y"),
        margin=dict(l=0, r=50, t=10, b=10), showlegend=False, paper_bgcolor='#000', plot_bgcolor='#000'
    )
    return fig


if __name__ == "__main__":
    server.run(debug=True, port=5000)