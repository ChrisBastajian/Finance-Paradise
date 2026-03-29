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
from dash import State
import google.generativeai as genai
from dotenv import load_dotenv

# --- LLM CONFIGURATION ---
load_dotenv()
my_api_key = os.environ.get("GEMINI_API_KEY")
genai.configure(api_key=my_api_key)

# We enforce JSON output so the script can parse the LLM's trading decisions flawlessly
model = genai.GenerativeModel(
    "gemini-2.5-flash",
    generation_config={"response_mime_type": "application/json"}
)

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
PRICE_SCALE = 0.05
news_button_pressed = False

# Order book
bids = defaultdict(int)
asks = defaultdict(int)
bid_prices = []
ask_prices = []

# Trader percentages: [trend, mean, panic, fundamental, noise]
# Simplified slightly to match LLM groups perfectly
percentages = [0.25, 0.25, 0.2, 0.2, 0.1]

# --- LLM PERSONA BIASES ---
# 0.0 is neutral, -1.0 is maximum short, 1.0 is maximum long
llm_biases = {
    "trend": 0.0,
    "mean": 0.0,
    "panic": 0.0,
    "fundamental": 0.0
}

news_path = os.path.join(os.path.dirname(__file__), "news.json")
news_candles_remaining = 0


# -----------------------
# LLM NEWS DECIPHER
# -----------------------
def read_news_and_get_llm_reaction(news_number):
    global llm_biases, news_candles_remaining

    # Read the news file
    with open(news_path, "r") as file:
        data = json.load(file)
        event_info = data[news_number]['event']
        description = data[news_number]['description']

    print(f"🚨 BREAKING NEWS: {event_info} - Fetching LLM Consensus...")

    # Prompt the LLM to act as the market personas
    prompt = f"""
    A major news event just occurred in the financial markets:
    Headline: {event_info}
    Context: {description}

    You are simulating the psychology of four different types of institutional traders. 
    Evaluate the news and output a bias score for each group from -1.0 (aggressive selling/shorting) to 1.0 (aggressive buying). 0.0 is neutral.

    - 'trend': Buys into momentum. Do they see this creating a massive new trend?
    - 'mean': Contrarians. Do they think the market will overreact so they should fade the move?
    - 'panic': Highly leveraged retail and emotional traders. Are they terrified (-1.0) or experiencing FOMO (1.0)?
    - 'fundamental': Deep value analysts. Does this fundamentally increase or decrease the asset's real value?

    Respond ONLY with a valid JSON object using the exact keys: "trend", "mean", "panic", "fundamental".
    """

    try:
        response = model.generate_content(prompt)
        llm_decision = json.loads(response.text)

        # Update the live market biases
        llm_biases["trend"] = float(llm_decision.get("trend", 0.0))
        llm_biases["mean"] = float(llm_decision.get("mean", 0.0))
        llm_biases["panic"] = float(llm_decision.get("panic", 0.0))
        llm_biases["fundamental"] = float(llm_decision.get("fundamental", 0.0))

        # Determine how long the news lasts based on the severity of the fundamental reaction
        severity = abs(llm_biases["fundamental"])
        news_candles_remaining = int(20 + (severity * 50))

        print(f"🧠 LLM Sentiments Received: {llm_decision}")

    except Exception as e:
        print(f"LLM Error: {e}")


# -----------------------
# HELPER FUNCTIONS
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


def add_order(book, plist, price, vol):
    if price not in book: bisect.insort(plist, price)
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
        price = (bp + ap) / 2
        trades.append((price, vol))
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
# TRADER CLASS (LLM DRIVEN)
# -----------------------
class Trader:
    def __init__(self):
        global percentages
        types = ["trend", "mean", "panic", "fundamental", "noise"]
        self.type = np.random.choice(types, p=percentages)

    def act(self, price, ref):
        global llm_biases

        # Noise traders just provide liquidity, ignoring the LLM
        if self.type == "noise":
            side = persistent_side()
            offset = -abs(np.random.exponential(0.3)) if side == "buy" else abs(np.random.exponential(0.3))
            p = price + offset
            p = max(0.01, round(p / TICK_SIZE) * TICK_SIZE)
            vol = np.random.randint(1, 3)
            return ("limit", side, p, vol)

        # For the persona traders, we pull their LLM-assigned bias
        bias = llm_biases.get(self.type, 0.0)

        # Convert the -1.0 to 1.0 bias into a probability of buying (0.0 to 1.0)
        # 0.0 bias = 50% chance to buy. 1.0 bias = 100% chance to buy.
        buy_probability = 0.5 + (bias / 2.0)

        # Execute trade based on LLM probability
        side = "buy" if np.random.rand() < buy_probability else "sell"

        # Volume aggressiveness scales with how extreme the LLM's bias is
        intensity = abs(bias)
        vol = np.random.randint(2, max(4, int(15 * intensity)))

        return ("market", side, vol)


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
    global vol_buy_candle, vol_sell_candle, candles, news_button_pressed, llm_biases

    t = 0
    while True:
        price *= (1 + LONG_TERM_DRIFT * PRICE_SCALE)

        for _ in range(ORDERS_PER_TICK):
            tr = random.choice(traders)
            action = tr.act(price, ref_price)
            if action is None: continue

            if action[0] == "limit":
                _, side, p, vol = action
                if side == "buy":
                    add_order(bids, bid_prices, p, vol)
                else:
                    add_order(asks, ask_prices, p, vol)
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
            with lock:
                volume_buy.append(vol_buy_candle)
                volume_sell.append(vol_sell_candle)
                vol_buy_candle = 0
                vol_sell_candle = 0
                chunk = prices[-CANDLE_SIZE:]
                o, h, l, c = chunk[0], max(chunk), min(chunk), chunk[-1]
                candles.append((o, h, l, c))

            # Cool off the LLM biases over time as the news gets "priced in"
            if news_candles_remaining > 0:
                news_candles_remaining -= 1
                if news_candles_remaining == 0:
                    print("Market normalized. LLM biases reset to 0.")
                    llm_biases = {"trend": 0.0, "mean": 0.0, "panic": 0.0, "fundamental": 0.0}

        # Trigger LLM in a separate thread so it doesn't freeze the chart
        if news_button_pressed:
            news_button_pressed = False
            random_idx = random.randint(0, 5)  # Assuming you have at least 6 items in news.json
            threading.Thread(target=read_news_and_get_llm_reaction, args=(random_idx,)).start()

        t += 1
        time.sleep(0.05)


# -----------------------
# DASH APP
# -----------------------
app = Dash(__name__)
app.layout = html.Div([
    html.Div([
        html.Div([
            html.Span("LIVE_MKT", style={'fontWeight': 'bold', 'marginRight': '15px', 'color': '#00FF00'}),
            dcc.Dropdown(
                id='timeframe-selector',
                options=[
                    {'label': '1m', 'value': 1},
                    {'label': '5m', 'value': 5},
                    {'label': '15m', 'value': 15},
                    {'label': '1h', 'value': 60},
                    {'label': '4h', 'value': 240},
                ],
                value=1, clearable=False, searchable=False,
                style={'width': '80px', 'color': '#000'}
            ),
        ], style={'display': 'flex', 'alignItems': 'center'}),

        html.Button("Trigger LLM News Event", id="news-button", n_clicks=0,
                    style={'backgroundColor': '#333', 'color': 'white', 'border': '1px solid #555',
                           'padding': '10px', 'cursor': 'pointer', 'fontWeight': 'bold'})
    ], style={
        'display': 'flex', 'justifyContent': 'space-between', 'alignItems': 'center',
        'padding': '10px 20px', 'backgroundColor': '#1a1a1a', 'borderBottom': '1px solid #333'
    }),

    html.Div([
        dcc.Graph(id="live-chart", config={'scrollZoom': True}, style={'height': '550px'}),
    ], style={'backgroundColor': '#111'}),

    dcc.Interval(id="interval", interval=500, n_intervals=0),
], style={'backgroundColor': '#111', 'fontFamily': 'sans-serif', 'overflow': 'hidden'})


@app.callback(
    Output("live-chart", "figure"),
    [Input("interval", "n_intervals"), Input("timeframe-selector", "value")],
    State("live-chart", "relayoutData")
)
def update_chart(_, tf_multiplier, relayout_data):
    with lock:
        if not candles: return go.Figure()
        base_c, base_b, base_s = list(candles), list(volume_buy), list(volume_sell)

    display_candles, vol_b, vol_s = aggregate_candles(base_c, base_b, base_s, tf_multiplier)
    indices = list(range(len(display_candles)))

    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=indices, open=[c[0] for c in display_candles], high=[c[1] for c in display_candles],
        low=[c[2] for c in display_candles], close=[c[3] for c in display_candles],
        increasing_line_color='#26a69a', decreasing_line_color='#ef5350'
    ))
    fig.add_trace(go.Bar(x=indices, y=vol_b, marker_color='rgba(38, 166, 154, 0.2)', yaxis="y2"))
    fig.add_trace(go.Bar(x=indices, y=vol_s, marker_color='rgba(239, 83, 80, 0.2)', yaxis="y2"))

    fig.update_layout(
        template='plotly_dark', uirevision=tf_multiplier, dragmode='pan',
        xaxis=dict(rangeslider_visible=False, showgrid=False, color='#555'),
        yaxis=dict(side="right", gridcolor='#222', color='#999', fixedrange=False),
        yaxis2=dict(domain=[0, 0.15], showgrid=False, anchor="x", overlaying="y"),
        margin=dict(l=10, r=50, t=10, b=30), showlegend=False,
        plot_bgcolor='#111', paper_bgcolor='#111'
    )
    return fig


@app.callback(
    Output("news-button", "children"),
    Input("news-button", "n_clicks")
)
def trigger_news(n_clicks):
    global news_button_pressed
    if n_clicks and n_clicks > 0:
        news_button_pressed = True
    return "Trigger LLM News Event"


threading.Thread(target=simulation_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(debug=True)