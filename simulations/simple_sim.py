import numpy as np
import matplotlib.pyplot as plt
from collections import defaultdict
import bisect
import random

np.random.seed(3)

# -----------------------
# PARAMETERS
# -----------------------
N_TRADERS = 200
TICKS = 1000
TICK_SIZE = 0.1

LONG_TERM = 0.1
SHORT_TERM = 0.01

ORDERS_PER_TICK = 10
CANCEL_PROB = 0.08  # higher → thinner book
CANDLE_SIZE = 5  # ticks per candle

# -----------------------
# ORDER BOOK
# -----------------------
bids = defaultdict(int)
asks = defaultdict(int)
bid_prices = []
ask_prices = []

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
        price = (bp + ap) / 2

        trades.append((price, vol))

        remove_order(bids, bid_prices, bp, vol)
        remove_order(asks, ask_prices, ap, vol)

    return trades

# -----------------------
# PERSISTENT ORDER FLOW
# -----------------------
last_side = np.random.choice(["buy", "sell"])

def persistent_side(p=0.7):
    global last_side
    if np.random.rand() < p:
        return last_side
    else:
        last_side = "buy" if last_side == "sell" else "sell"
        return last_side

# -----------------------
# TRADER CLASS WITH STRATEGIES
# -----------------------
class Trader:
    def __init__(self):
        self.type = np.random.choice(
            ["trend", "mean", "panic", "noise"],
            p=[0.3, 0.3, 0.2, 0.2]
        )
        self.memory = []

    def act(self, price, ref):
        self.memory.append(price)
        if len(self.memory) > 10:
            self.memory.pop(0)

        dev = abs(price - ref) / ref
        base = np.random.pareto(2) * 2
        volume = max(1, int(base * (1 + 5 * dev)))

        # TREND FOLLOWERS
        if self.type == "trend" and len(self.memory) > 3:
            trend = self.memory[-1] - self.memory[-4]
            if trend > 0:
                return ("market", "buy", volume)
            else:
                return ("market", "sell", volume)

        # MEAN REVERSION
        if self.type == "mean":
            if price > ref:
                return ("market", "sell", volume)
            else:
                return ("market", "buy", volume)

        # PANIC TRADERS
        if self.type == "panic":
            if dev > 0.02 and len(self.memory) > 3:
                trend = self.memory[-1] - self.memory[-4]
                side = "buy" if trend > 0 else "sell"
                return ("market", side, int(volume * 2))

        # NOISE / LIQUIDITY
        side = persistent_side()
        if side == "buy":
            offset = -abs(np.random.exponential(1))
        else:
            offset = abs(np.random.exponential(1))
        p = price + offset
        p = round(p / TICK_SIZE) * TICK_SIZE
        return ("limit", side, p, volume)

traders = [Trader() for _ in range(N_TRADERS)]

# -----------------------
# SIMULATION LOOP
# -----------------------
price = 100.0
ref_price = price
prices = []
volume_buy = []
volume_sell = []

# track volume in current candle
vol_buy_candle = 0
vol_sell_candle = 0

for t in range(TICKS):
    # ORDER SUBMISSION
    for _ in range(ORDERS_PER_TICK):
        tr = random.choice(traders)
        action = tr.act(price, ref_price)

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
                price = ap
                vol_buy_candle += vol
            elif side == "sell" and bid_prices:
                bp = best_bid()
                remove_order(bids, bid_prices, bp, vol)
                price = bp
                vol_sell_candle += vol

    # MATCHING
    trades = match()
    for p_trade, v_trade in trades:
        price = p_trade
        # Assign volume to buy/sell based on price vs mid
        mid = (best_bid() + best_ask()) / 2 if best_bid() and best_ask() else price
        if p_trade >= mid:
            vol_buy_candle += v_trade
        else:
            vol_sell_candle += v_trade

    # CANCELLATIONS
    for book, plist in [(bids, bid_prices), (asks, ask_prices)]:
        for p_ in plist.copy():
            if np.random.rand() < CANCEL_PROB:
                remove_order(book, plist, p_, 1)

    # REFERENCE PRICE (slow memory)
    ref_price = 0.999 * ref_price + 0.001 * price

    prices.append(price)

    # AGGREGATE VOLUME PER CANDLE
    if (t+1) % CANDLE_SIZE == 0:
        volume_buy.append(vol_buy_candle)
        volume_sell.append(vol_sell_candle)
        vol_buy_candle = 0
        vol_sell_candle = 0

# -----------------------
# AGGREGATE CANDLES
# -----------------------
opens, highs, lows, closes = [], [], [], []

for i in range(0, len(prices), CANDLE_SIZE):
    chunk = prices[i:i + CANDLE_SIZE]
    if len(chunk) < CANDLE_SIZE:
        break
    o = chunk[0]
    h = max(chunk)
    l = min(chunk)
    c = chunk[-1]
    opens.append(o)
    highs.append(h)
    lows.append(l)
    closes.append(c)

# -----------------------
# PLOT CANDLES + VOLUME
# -----------------------
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14,6), gridspec_kw={'height_ratios':[3,1]}, sharex=True)

# Candlesticks
for i in range(len(opens)):
    o, h, l, c = opens[i], highs[i], lows[i], closes[i]
    color = 'green' if c >= o else 'red'
    # wick
    ax1.plot([i, i], [l, h], color=color)
    # body
    ax1.plot([i, i], [o, c], linewidth=5, color=color)

ax1.set_ylabel("Price")
ax1.set_title("Candlestick Chart with Buy/Sell Volume per Candle")

# Volume bars
x = np.arange(len(volume_buy))
ax2.bar(x, volume_buy, color='green', alpha=0.5, label='Buy Volume')
ax2.bar(x, volume_sell, bottom=volume_buy, color='red', alpha=0.5, label='Sell Volume')
ax2.set_xlabel("Candle Index")
ax2.set_ylabel("Volume")
ax2.legend()

plt.tight_layout()
plt.show()