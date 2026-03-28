import json
import random

# =========================
# LOAD DATA
# =========================
with open("traders.json") as f:
    traders = json.load(f)

with open("market.json") as f:
    market = json.load(f)

with open("news.json") as f:
    news = json.load(f)

# =========================
# GENERATE DAILY NEWS
# =========================
def generate_news():
    news = []
    num_events = random.randint(1, 3)

    for i in range(num_events):
        event = {
            "event": "Event_" + str(i),
            "effects": [random.randint(0, 10) for _ in range(10)]
        }
        news.append(event)

    return news

# =========================
# PROCESS NEWS IMPACT
# =========================
def get_news_impact(news):
    total = 0

    for event in news:
        impact = sum(event["effects"]) / len(event["effects"])
        total = total + impact

    if len(news) > 0:
        total = total / len(news)

    return total

# =========================
# UPDATE MARKET
# =========================
def update_market(news):
    news_impact = get_news_impact(news)

    for stock in market:
        base_change = random.uniform(-2, 2)

        # carry over last day's price + influence
        change = base_change + (news_impact - 5) * 0.5

        stock["price"] = stock["price"] + change

        if stock["price"] < 1:
            stock["price"] = 1

# =========================
# TRADER SIMULATION
# =========================
def simulate_traders():
    for trader in traders:
        for stock in market:

            bias = 0

            if stock["sector"] in trader["likes"]:
                bias = bias + 1
            if stock["sector"] in trader["dislikes"]:
                bias = bias - 1

            decision = random.random()

            if decision < trader["risk"] + (bias * 0.1):
                amount = trader["money"] * 0.05
                trader["money"] = trader["money"] - amount
            else:
                trader["money"] = trader["money"] + random.uniform(0, 50)

# =========================
# RUN MULTI-DAY SIMULATION
# =========================
days = 10  # <-- change this to X

for day in range(1, days + 1):

    print("\n=== DAY", day, "===")

    # new news each day
    news = generate_news()

    # update market from previous state
    update_market(news)

    # simulate traders
    simulate_traders()

    # print market snapshot
    print("Market:")
    for stock in market:
        print(" ", stock["company"], "->", round(stock["price"], 2))

    print("Traders:")
    for trader in traders:
        print(" ", trader["name"], "->", round(trader["money"], 2))