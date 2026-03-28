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

ORDERS_PER_TICK = 10
CANCEL_PROB = 0.08
CANDLE_SIZE = 5

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
        self.type = np.random.choice(
            ["trend","mean","panic","noise"], p=[0.3,0.3,0.2,0.2]
        )
        self.memory = []

    def act(self, price, ref):
        self.memory.append(price)
        if len(self.memory) > 10:
            self.memory.pop(0)

        # Trend trader: fires every tick with bias
        if self.type=="trend" and len(self.memory)>3:
            trend = self.memory[-1] - self.memory[-4]
            # Directional bias: 60% chance to follow trend
            side = "buy" if trend>0 else "sell"
            vol = np.random.randint(5,15)
            return ("market", side, vol)

        # Mean reversion
        if self.type=="mean":
            side = "sell" if price>ref else "buy"
            vol = np.random.randint(3,10)
            return ("market", side, vol)

        # Panic trader
        dev = abs(price-ref)/ref
        if self.type=="panic" and dev>0.02 and len(self.memory)>3:
            trend = self.memory[-1]-self.memory[-4]
            side = "buy" if trend>0 else "sell"
            vol = np.random.randint(10,25)
            return ("market", side, vol)

        # Noise / liquidity
        side = persistent_side()
        offset = -abs(np.random.exponential(1)) if side=="buy" else abs(np.random.exponential(1))
        p = price + offset
        p = round(p/TICK_SIZE)*TICK_SIZE
        vol = np.random.randint(1,5)
        return ("limit", side, p, vol)

traders = [Trader() for _ in range(N_TRADERS)]

# -----------------------
# SIMULATION LOOP
# -----------------------
price = 100.0
ref_price = price
prices = []
volume_buy = []
volume_sell = []
vol_buy_candle = 0
vol_sell_candle = 0

LONG_TERM_DRIFT = 0.0005  # small directional bias per tick

for t in range(TICKS):
    price *= (1 + LONG_TERM_DRIFT)  # long-term drift

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
                price = ap
                vol_buy_candle += vol
            elif side=="sell" and bid_prices:
                bp = best_bid()
                remove_order(bids, bid_prices, bp, vol)
                price = bp
                vol_sell_candle += vol

    trades = match()
    for p_trade, v_trade in trades:
        price = p_trade
        mid = (best_bid() + best_ask())/2 if best_bid() and best_ask() else price
        if p_trade >= mid:
            vol_buy_candle += v_trade
        else:
            vol_sell_candle += v_trade

    for book, plist in [(bids, bid_prices),(asks, ask_prices)]:
        for p_ in plist.copy():
            if np.random.rand()<CANCEL_PROB:
                remove_order(book, plist, p_,1)

    # slower reference price to allow deviations
    ref_price = 0.99*ref_price + 0.01*price
    prices.append(price)

    if (t+1)%CANDLE_SIZE==0:
        volume_buy.append(vol_buy_candle)
        volume_sell.append(vol_sell_candle)
        vol_buy_candle = 0
        vol_sell_candle = 0

# -----------------------
# AGGREGATE CANDLES
# -----------------------
opens, highs, lows, closes = [], [], [], []
for i in range(0,len(prices),CANDLE_SIZE):
    chunk = prices[i:i+CANDLE_SIZE]
    if len(chunk)<CANDLE_SIZE: break
    opens.append(chunk[0])
    highs.append(max(chunk))
    lows.append(min(chunk))
    closes.append(chunk[-1])

# -----------------------
# PLOT: Candlestick + Volume + Order Book
# -----------------------
fig = plt.figure(figsize=(14,6))
gs = fig.add_gridspec(2,2, width_ratios=[3,1], height_ratios=[3,1])
ax1 = fig.add_subplot(gs[0,0])  # candlestick
ax2 = fig.add_subplot(gs[1,0], sharex=ax1)  # volume
ax3 = fig.add_subplot(gs[:,1])  # order book

# Candlesticks
for i in range(len(opens)):
    o,h,l,c = opens[i], highs[i], lows[i], closes[i]
    color = 'green' if c>=o else 'red'
    ax1.plot([i,i],[l,h], color=color)
    ax1.plot([i,i],[o,c], linewidth=5, color=color)
ax1.set_ylabel("Price")
ax1.set_title("Candles + Volume + Order Book")

# Volume
x = np.arange(len(volume_buy))
ax2.bar(x, volume_buy, color='green', alpha=0.5)
ax2.bar(x, volume_sell, bottom=volume_buy, color='red', alpha=0.5)
ax2.set_xlabel("Candle Index")
ax2.set_ylabel("Volume")

# Order book snapshot
bid_prices_sorted = sorted(bids.keys())
ask_prices_sorted = sorted(asks.keys())
bid_vols = [bids[p] for p in bid_prices_sorted]
ask_vols = [asks[p] for p in ask_prices_sorted]

ax3.barh(bid_prices_sorted, bid_vols, color='green', alpha=0.5, label='Bids')
ax3.barh(ask_prices_sorted, ask_vols, color='red', alpha=0.5, label='Asks')
ax3.set_xlabel("Volume")
ax3.set_ylabel("Price")
ax3.legend()

plt.tight_layout()
plt.show()