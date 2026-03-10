import requests

def get_markets():
    url = "https://gamma-api.polymarket.com/markets"
    
    params = {
        "limit": 50,
        "active": True,
        "closed": False
    }
    
    response = requests.get(url, params=params)
    markets = response.json()
    
    flagged = []

    for market in markets:
        question = market.get("question", "N/A")
        volume = float(market.get("volume", 0))
        best_bid = market.get("bestBid")
        best_ask = market.get("bestAsk")
        last_price = market.get("lastTradePrice")

        if not best_bid or not best_ask or not last_price:
            continue

        best_bid = float(best_bid)
        best_ask = float(best_ask)
        last_price = float(last_price)
        spread = round(best_ask - best_bid, 4)

        # Scoring logic
        score = 0

        if volume > 50000:
            score += 2
        elif volume > 10000:
            score += 1

        if spread <= 0.02:
            score += 2
        elif spread <= 0.05:
            score += 1

        if 0.20 <= last_price <= 0.80:
            score += 2

        if score >= 5:
            flagged.append({
                "question": question,
                "volume": volume,
                "bid": best_bid,
                "ask": best_ask,
                "last_price": last_price,
                "spread": spread,
                "score": score
            })

    # Sort by score
    flagged.sort(key=lambda x: x["score"], reverse=True)

    print(f"\n🔍 {len(flagged)} markets flagged as interesting:\n")
    for m in flagged:
        print(f"Market: {m['question']}")
        print(f"Score: {m['score']} | Volume: ${m['volume']:,.2f} | Last Price: {m['last_price']}")
        print(f"Bid: {m['bid']} | Ask: {m['ask']} | Spread: {m['spread']}")
        print("---")

get_markets()