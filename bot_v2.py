import requests
from bs4 import BeautifulSoup
import time
from logger import log_signal

HOCKEY_API_KEY = "72d0facdc03c7d99141b5b71c7d0b4f8"

def get_polymarket():
    url = "https://gamma-api.polymarket.com/markets"
    params = {"limit": 50, "active": True, "closed": False}
    response = requests.get(url, params=params)
    return response.json()

def get_nhl_standings():
    url = "https://v1.hockey.api-sports.io/standings"
    headers = {"x-apisports-key": HOCKEY_API_KEY}
    response = requests.get(url, headers=headers, params={"league": "57", "season": "2024"})
    data = response.json()
    
    standings = {}
    for stage in data["response"]:
        for team in stage:
            if team["stage"] != "NHL - Regular Season":
                continue
            if team["group"]["name"] not in ["Eastern Conference", "Western Conference"]:
                continue
            name = team["team"]["name"]
            standings[name] = {
                "position": team["position"],
                "points": team["points"],
                "win_pct": float(team["games"]["win"]["percentage"]),
                "made_playoffs": "Play Offs" in (team["description"] or "")
            }
    return standings

def get_sentiment(query):
    headers = {"User-Agent": "Mozilla/5.0"}
    url = f"https://news.google.com/search?q={query.replace(' ', '+')}&hl=en"
    try:
        response = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(response.text, "html.parser")
        headlines = [h.get_text() for h in soup.find_all("a", class_="JtKRv")][:10]
    except:
        return 0
    
    positive = ["win", "qualify", "success", "advance", "confirm", "secure", "lead", "likely", "favorite", "strong", "playoff"]
    negative = ["fail", "lose", "eliminated", "miss", "doubt", "crisis", "injury", "unlikely", "banned", "weak"]
    
    score = 0
    for h in headlines:
        h = h.lower()
        for w in positive:
            if w in h: score += 1
        for w in negative:
            if w in h: score -= 1
    return score

def get_nhl_signal(question, standings):
    for team_name, stats in standings.items():
        if team_name.lower() in question.lower():
            score = 0
            if stats["made_playoffs"]: score += 3
            if stats["position"] <= 4: score += 2
            elif stats["position"] <= 8: score += 1
            if stats["win_pct"] >= 0.50: score += 2
            elif stats["win_pct"] >= 0.40: score += 1
            return score, stats
    return None, None

def scan():
    print("\n🔍 Scanning Polymarket...\n")
    markets = get_polymarket()
    standings = get_nhl_standings()
    opportunities = []

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

        if volume < 5000 or spread > 0.05 or not (0.15 <= last_price <= 0.85):
            continue

        sentiment = get_sentiment(question)
        time.sleep(1)

        nhl_score, nhl_stats = get_nhl_signal(question, standings)

        total_score = sentiment
        if nhl_score is not None:
            total_score += nhl_score
            signal_type = "NHL+Sentiment"
        else:
            signal_type = "Sentiment only"

        signal = None
        if total_score >= 4 and last_price < 0.50:
            signal = f"BUY — Score: {total_score} | Type: {signal_type}"
        elif total_score <= -3 and last_price > 0.50:
            signal = f"SELL — Score: {total_score} | Type: {signal_type}"

        if signal:
            opportunities.append({
                "question": question,
                "last_price": last_price,
                "volume": volume,
                "spread": spread,
                "signal": signal,
                "nhl_stats": nhl_stats
            })
            log_signal(
                question=question,
                price=last_price,
                volume=volume,
                spread=spread,
                signal=signal,
                score=total_score,
                signal_type=signal_type,
                nhl_stats=nhl_stats
            )

    if not opportunities:
        print("No strong opportunities found.")
    else:
        print(f"⚡ {len(opportunities)} opportunities found:\n")
        for o in opportunities:
            print(f"Market: {o['question']}")
            print(f"Price: {o['last_price']} | Volume: ${o['volume']:,.2f} | Spread: {o['spread']}")
            if o["nhl_stats"]:
                s = o["nhl_stats"]
                print(f"NHL Data: Pos {s['position']} | Pts {s['points']} | Win% {s['win_pct']} | Playoffs: {s['made_playoffs']}")
            print(f"Signal: {o['signal']}")
            print("---")

scan()