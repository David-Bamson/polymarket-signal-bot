import requests
import time
import json
from bs4 import BeautifulSoup
from config import (
    HOCKEY_API_KEY, SPORTS_API_KEY, NEWS_API_KEY,
    ANTHROPIC_API_KEY, GEMINI_API_KEY,
    GAMMA_API_URL, CLOB_HOST,
    SENTIMENT_WEIGHT, MICROSTRUCTURE_WEIGHT, SPORT_DATA_WEIGHT,
    CLAUDE_MODEL, GEMINI_MODEL,
    AI_SENTIMENT_ENABLED, AI_PROVIDER, AI_MAX_CALLS_PER_CYCLE,
)
from logger import logger

# Track AI API usage per cycle
_ai_calls_this_cycle = 0


def reset_ai_call_count():
    global _ai_calls_this_cycle
    _ai_calls_this_cycle = 0


# ── Keyword dictionaries (fallback when Claude unavailable) ──────────

POSITIVE_KEYWORDS = [
    "win", "wins", "won", "victory", "qualify", "qualified", "advance",
    "confirm", "confirmed", "secure", "secured", "lead", "leads", "leading",
    "likely", "favorite", "favored", "strong", "surge", "surges", "rally",
    "approve", "approved", "pass", "passed", "sign", "signed", "deal",
    "boost", "record", "success", "dominate", "clinch", "playoff",
]
NEGATIVE_KEYWORDS = [
    "fail", "fails", "lose", "lost", "loss", "eliminated", "elimination",
    "miss", "missed", "doubt", "crisis", "injury", "injured", "unlikely",
    "banned", "weak", "collapse", "crash", "reject", "rejected", "veto",
    "scandal", "resign", "fired", "suspend", "suspended", "default",
    "deficit", "downgrade", "worst", "struggle", "struggling",
]


# ══════════════════════════════════════════════════════════════════════
# 1. CLAUDE AI SENTIMENT (primary — replaces keyword counting)
# ══════════════════════════════════════════════════════════════════════

def get_sentiment_signal(question):
    """Returns (probability_estimate, confidence) from news + AI analysis."""
    # Get headlines first (needed for both AI and fallback)
    headlines = _fetch_headlines(question)

    # Try AI analysis (Gemini free tier or Claude)
    if AI_SENTIMENT_ENABLED:
        if AI_PROVIDER == "gemini":
            result = _sentiment_from_gemini(question, headlines)
        else:
            result = _sentiment_from_claude(question, headlines)
        if result[1] > 0:
            return result

    # Fallback to keyword counting
    if headlines:
        return _sentiment_from_keywords(headlines)

    return 0.5, 0.05


def _fetch_headlines(question):
    """Fetch headlines from NewsAPI or Google News."""
    if NEWS_API_KEY:
        try:
            resp = requests.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q": question[:80],
                    "sortBy": "publishedAt",
                    "pageSize": 20,
                    "language": "en",
                    "apiKey": NEWS_API_KEY,
                },
                timeout=10,
            )
            data = resp.json()
            articles = data.get("articles", [])
            return [a["title"] for a in articles if a.get("title")]
        except Exception as e:
            logger.warning(f"NewsAPI error: {e}")

    # Fallback: Google News scrape
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        url = f"https://news.google.com/search?q={question.replace(' ', '+')}&hl=en"
        resp = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(resp.text, "html.parser")
        headlines = []
        for tag in soup.find_all("a"):
            text = tag.get_text(strip=True)
            if len(text) > 20:
                headlines.append(text)
        return headlines[:15]
    except Exception:
        return []


def _build_sentiment_prompt(question, headlines):
    """Build the shared prompt for AI sentiment analysis."""
    headlines_text = "\n".join(f"- {h}" for h in headlines[:15])
    return (
        f"You are a prediction market analyst. A market asks:\n"
        f'"{question}"\n\n'
        f"Recent headlines:\n{headlines_text}\n\n"
        f"Based on these headlines, estimate the probability that "
        f"the answer to the market question is YES.\n\n"
        f"Respond with ONLY a JSON object, no other text:\n"
        f'{{"probability": 0.XX, "confidence": 0.XX, "reasoning": "one sentence"}}\n\n'
        f"probability: 0.0 to 1.0 (your estimate)\n"
        f"confidence: 0.0 to 1.0 (how confident you are in your estimate, "
        f"based on headline relevance and clarity)"
    )


def _parse_ai_response(text):
    """Parse JSON from AI response, handling markdown code blocks."""
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)


def _sentiment_from_gemini(question, headlines):
    """
    Use Google Gemini Flash (FREE) to analyze headlines and estimate probability.
    Free tier: 15 requests/minute, 1500/day.
    """
    global _ai_calls_this_cycle

    if _ai_calls_this_cycle >= AI_MAX_CALLS_PER_CYCLE:
        return 0.5, 0.0

    if not headlines:
        return 0.5, 0.0

    try:
        from google import genai

        # Rate limit: stay under 15 req/min (4s between calls)
        time.sleep(4)

        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = _build_sentiment_prompt(question, headlines)

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )

        _ai_calls_this_cycle += 1
        text = response.text.strip()

        result = _parse_ai_response(text)
        prob = float(result["probability"])
        conf = float(result["confidence"]) * 0.8
        reasoning = result.get("reasoning", "")

        prob = max(0.02, min(0.98, prob))
        conf = max(0.0, min(1.0, conf))

        logger.info(
            f"Gemini sentiment: prob={prob:.2f} conf={conf:.2f} | "
            f"{reasoning[:60]} | {question[:40]}"
        )
        return round(prob, 4), round(conf, 4)

    except Exception as e:
        logger.warning(f"Gemini sentiment failed: {e}")
        return 0.5, 0.0


def _sentiment_from_claude(question, headlines):
    """
    Use Claude to analyze headlines and estimate probability.
    Paid but higher quality than Gemini.
    """
    global _ai_calls_this_cycle

    if _ai_calls_this_cycle >= AI_MAX_CALLS_PER_CYCLE:
        return 0.5, 0.0

    if not headlines:
        return 0.5, 0.0

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        prompt = _build_sentiment_prompt(question, headlines)

        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )

        _ai_calls_this_cycle += 1
        text = response.content[0].text.strip()

        result = _parse_ai_response(text)
        prob = float(result["probability"])
        conf = float(result["confidence"]) * 0.8
        reasoning = result.get("reasoning", "")

        prob = max(0.02, min(0.98, prob))
        conf = max(0.0, min(1.0, conf))

        logger.info(
            f"Claude sentiment: prob={prob:.2f} conf={conf:.2f} | "
            f"{reasoning[:60]} | {question[:40]}"
        )
        return round(prob, 4), round(conf, 4)

    except Exception as e:
        logger.warning(f"Claude sentiment failed: {e}")
        return 0.5, 0.0


def _sentiment_from_keywords(headlines):
    """Fallback: keyword-based sentiment when AI is unavailable."""
    pos = neg = 0
    for h in headlines:
        h_lower = h.lower()
        for w in POSITIVE_KEYWORDS:
            if w in h_lower:
                pos += 1
        for w in NEGATIVE_KEYWORDS:
            if w in h_lower:
                neg += 1

    total = pos + neg
    if total == 0:
        return 0.5, 0.05

    ratio = pos / (pos + neg)
    # Keep the nudge small — keywords are low quality
    prob = 0.5 + (ratio - 0.5) * 0.15
    # Very low confidence — this should NOT drive trades on its own
    confidence = min(len(headlines) / 15, 1.0) * 0.1
    return round(prob, 4), round(confidence, 4)


# ══════════════════════════════════════════════════════════════════════
# 2. MARKET MICROSTRUCTURE + ORDERBOOK DEPTH
# ══════════════════════════════════════════════════════════════════════

def get_microstructure_signal(market):
    """
    Analyze market price action, liquidity, and orderbook depth.
    Returns (probability_estimate, confidence).
    """
    last_price = float(market.get("lastTradePrice", 0.5))
    volume = float(market.get("volume", 0))
    best_bid = float(market.get("bestBid", 0))
    best_ask = float(market.get("bestAsk", 1))
    spread = best_ask - best_bid

    # Spread tightness → confidence modifier
    if spread <= 0.02:
        spread_confidence = 1.0
    elif spread <= 0.05:
        spread_confidence = 0.7
    else:
        spread_confidence = 0.3

    # Volume strength → confidence modifier
    if volume > 100_000:
        vol_confidence = 1.0
    elif volume > 50_000:
        vol_confidence = 0.7
    elif volume > 10_000:
        vol_confidence = 0.4
    else:
        vol_confidence = 0.1

    # Bid-ask midpoint vs last trade (directional pressure)
    midpoint = (best_bid + best_ask) / 2
    price_skew = midpoint - last_price

    # Orderbook depth imbalance
    book_prob, book_conf = _get_orderbook_signal(market)

    # Price momentum
    momentum_prob, momentum_conf = _get_price_momentum(market)

    # Combine microstructure sub-signals
    sub_signals = []

    if momentum_conf > 0:
        sub_signals.append((momentum_prob, momentum_conf))

    if book_conf > 0:
        sub_signals.append((book_prob, book_conf))

    if sub_signals:
        total_w = sum(c for _, c in sub_signals)
        prob = sum(p * c for p, c in sub_signals) / total_w
        prob += price_skew * 0.3  # add midpoint pressure
    else:
        prob = midpoint

    prob = max(0.05, min(0.95, prob))
    confidence = (spread_confidence * 0.3 + vol_confidence * 0.4 + book_conf * 0.3) * MICROSTRUCTURE_WEIGHT

    return round(prob, 4), round(confidence, 4)


def _get_orderbook_signal(market):
    """
    Fetch CLOB orderbook and compute bid/ask depth imbalance.
    Heavy bid depth = bullish, heavy ask depth = bearish.
    """
    token_id = ""
    clob_ids = market.get("clobTokenIds")
    if clob_ids and isinstance(clob_ids, list) and clob_ids:
        token_id = clob_ids[0]
    if isinstance(clob_ids, str):
        try:
            parsed = json.loads(clob_ids)
            if parsed:
                token_id = parsed[0]
        except (json.JSONDecodeError, IndexError):
            token_id = clob_ids

    if not token_id:
        return 0.5, 0.0

    try:
        resp = requests.get(
            f"{CLOB_HOST}/book",
            params={"token_id": token_id},
            timeout=5,
        )
        if resp.status_code != 200:
            return 0.5, 0.0

        book = resp.json()
        bids = book.get("bids", [])
        asks = book.get("asks", [])

        if not bids and not asks:
            return 0.5, 0.0

        # Sum depth (price * size) for top 10 levels
        bid_depth = sum(
            float(b.get("price", 0)) * float(b.get("size", 0))
            for b in bids[:10]
        )
        ask_depth = sum(
            float(a.get("price", 0)) * float(a.get("size", 0))
            for a in asks[:10]
        )

        total_depth = bid_depth + ask_depth
        if total_depth == 0:
            return 0.5, 0.0

        # Imbalance: 1.0 = all bids (very bullish), 0.0 = all asks (very bearish)
        imbalance = bid_depth / total_depth

        # Map imbalance to probability nudge
        # 0.5 = balanced, >0.5 = bullish, <0.5 = bearish
        prob = 0.5 + (imbalance - 0.5) * 0.4  # dampen the signal

        # Confidence based on total depth (more liquidity = more meaningful)
        if total_depth > 5000:
            conf = 0.7
        elif total_depth > 1000:
            conf = 0.4
        else:
            conf = 0.15

        logger.debug(
            f"Orderbook: bid_depth=${bid_depth:.0f} ask_depth=${ask_depth:.0f} "
            f"imbalance={imbalance:.2f}"
        )
        return round(prob, 4), round(conf, 4)

    except Exception as e:
        logger.debug(f"Orderbook fetch failed: {e}")
        return 0.5, 0.0


def _get_price_momentum(market):
    """Fetch recent price history and compute momentum."""
    slug = market.get("slug") or market.get("conditionId")
    if not slug:
        return 0.5, 0.0

    try:
        resp = requests.get(
            f"{GAMMA_API_URL}/markets/{slug}/timeseries",
            params={"interval": "1h", "fidelity": 24},
            timeout=5,
        )
        if resp.status_code != 200:
            return 0.5, 0.0

        data = resp.json()
        if not data or len(data) < 2:
            return 0.5, 0.0

        prices = [float(p.get("price", p.get("p", 0.5))) for p in data if p]
        if len(prices) < 2:
            return 0.5, 0.0

        # 24h momentum
        price_change_24h = prices[-1] - prices[0]
        current = prices[-1]

        # Short-term momentum (last 6 data points if available)
        short_prices = prices[-6:] if len(prices) >= 6 else prices
        price_change_short = short_prices[-1] - short_prices[0]

        # Acceleration: is momentum increasing?
        acceleration = price_change_short - (price_change_24h * len(short_prices) / len(prices))

        # Momentum-adjusted probability
        momentum_prob = current + price_change_24h * 0.15 + acceleration * 0.1
        momentum_prob = max(0.05, min(0.95, momentum_prob))

        # Higher confidence when momentum is strong and consistent
        strength = abs(price_change_24h)
        if strength > 0.10:
            conf = 0.6
        elif strength > 0.05:
            conf = 0.4
        else:
            conf = 0.2

        return round(momentum_prob, 4), round(conf, 4)

    except Exception:
        return 0.5, 0.0


# ══════════════════════════════════════════════════════════════════════
# 3. SPORT DATA SIGNALS (NHL + NBA + NFL + MLB)
# ══════════════════════════════════════════════════════════════════════

# --- Historical base rates for playoff probability by position ---
PLAYOFF_PROB_BY_POSITION = {
    1: 0.98, 2: 0.96, 3: 0.93, 4: 0.88,
    5: 0.80, 6: 0.70, 7: 0.55, 8: 0.45,
    9: 0.30, 10: 0.18, 11: 0.10, 12: 0.05,
    13: 0.02, 14: 0.01, 15: 0.005, 16: 0.002,
}

# NBA: top 10 in each conf make play-in, top 6 guaranteed playoffs
NBA_PLAYOFF_PROB = {
    1: 0.99, 2: 0.98, 3: 0.96, 4: 0.93, 5: 0.90, 6: 0.85,
    7: 0.65, 8: 0.55, 9: 0.40, 10: 0.30,
    11: 0.12, 12: 0.05, 13: 0.02, 14: 0.01, 15: 0.005,
}

# NFL: top 7 per conference
NFL_PLAYOFF_PROB = {
    1: 0.99, 2: 0.95, 3: 0.88, 4: 0.78,
    5: 0.65, 6: 0.50, 7: 0.38, 8: 0.25,
    9: 0.15, 10: 0.08, 11: 0.04, 12: 0.02,
    13: 0.01, 14: 0.005, 15: 0.002, 16: 0.001,
}

# MLB: top 6 per league (3 division winners + 3 wild cards)
MLB_PLAYOFF_PROB = {
    1: 0.98, 2: 0.93, 3: 0.85, 4: 0.72, 5: 0.58, 6: 0.45,
    7: 0.30, 8: 0.18, 9: 0.10, 10: 0.05,
    11: 0.02, 12: 0.01, 13: 0.005, 14: 0.002, 15: 0.001,
}


def get_all_sport_standings():
    """Fetch standings for all available sports. Returns dict of sport -> standings."""
    all_standings = {}

    # NHL
    nhl = _fetch_nhl_standings()
    if nhl:
        all_standings["nhl"] = nhl

    # NBA
    nba = _fetch_nba_standings()
    if nba:
        all_standings["nba"] = nba

    # NFL
    nfl = _fetch_nfl_standings()
    if nfl:
        all_standings["nfl"] = nfl

    # MLB
    mlb = _fetch_mlb_standings()
    if mlb:
        all_standings["mlb"] = mlb

    return all_standings


def _get_sports_api_key():
    """Get the sports API key — SPORTS_API_KEY takes precedence, falls back to HOCKEY_API_KEY."""
    return SPORTS_API_KEY or HOCKEY_API_KEY


def _fetch_nhl_standings():
    api_key = _get_sports_api_key()
    if not api_key:
        return {}
    try:
        resp = requests.get(
            "https://v1.hockey.api-sports.io/standings",
            headers={"x-apisports-key": api_key},
            params={"league": "57", "season": "2024"},
            timeout=10,
        )
        data = resp.json()
        standings = {}
        for stage in data.get("response", []):
            for team in stage:
                if team.get("stage") != "NHL - Regular Season":
                    continue
                group = team.get("group", {}).get("name", "")
                if group not in ("Eastern Conference", "Western Conference"):
                    continue
                name = team["team"]["name"]
                standings[name] = {
                    "sport": "nhl",
                    "position": team["position"],
                    "points": team.get("points", 0),
                    "win_pct": float(team["games"]["win"]["percentage"]),
                    "made_playoffs": "Play Offs" in (team.get("description") or ""),
                    "conference": group,
                }
        return standings
    except Exception as e:
        logger.warning(f"NHL standings failed: {e}")
        return {}


def _fetch_nba_standings():
    api_key = _get_sports_api_key()
    if not api_key:
        return {}
    try:
        resp = requests.get(
            "https://v1.basketball.api-sports.io/standings",
            headers={"x-apisports-key": api_key},
            params={"league": "12", "season": "2024-2025"},
            timeout=10,
        )
        data = resp.json()
        standings = {}
        for group in data.get("response", []):
            if not isinstance(group, list):
                group = [group]
            for team in group:
                stage = team.get("stage", "")
                if "Regular" not in stage:
                    continue
                conf = team.get("group", {}).get("name", "")
                if "East" not in conf and "West" not in conf:
                    continue
                name = team["team"]["name"]
                games = team.get("games", {})
                win = games.get("win", {})
                lose = games.get("lose", {})
                total_w = int(win.get("total", 0))
                total_l = int(lose.get("total", 0))
                total_g = total_w + total_l
                standings[name] = {
                    "sport": "nba",
                    "position": team.get("position", 0),
                    "wins": total_w,
                    "losses": total_l,
                    "win_pct": total_w / total_g if total_g > 0 else 0.5,
                    "conference": conf,
                }
        return standings
    except Exception as e:
        logger.warning(f"NBA standings failed: {e}")
        return {}


def _fetch_nfl_standings():
    api_key = _get_sports_api_key()
    if not api_key:
        return {}
    try:
        resp = requests.get(
            "https://v1.american-football.api-sports.io/standings",
            headers={"x-apisports-key": api_key},
            params={"league": "1", "season": "2024"},
            timeout=10,
        )
        data = resp.json()
        standings = {}
        for group in data.get("response", []):
            if not isinstance(group, list):
                group = [group]
            for team in group:
                name = team.get("team", {}).get("name", "")
                if not name:
                    continue
                conf = team.get("group", "")
                won = int(team.get("won", 0))
                lost = int(team.get("lost", 0))
                total = won + lost
                standings[name] = {
                    "sport": "nfl",
                    "position": team.get("position", 0),
                    "wins": won,
                    "losses": lost,
                    "win_pct": won / total if total > 0 else 0.5,
                    "conference": conf,
                }
        return standings
    except Exception as e:
        logger.warning(f"NFL standings failed: {e}")
        return {}


def _fetch_mlb_standings():
    api_key = _get_sports_api_key()
    if not api_key:
        return {}
    try:
        resp = requests.get(
            "https://v1.baseball.api-sports.io/standings",
            headers={"x-apisports-key": api_key},
            params={"league": "1", "season": "2025"},
            timeout=10,
        )
        data = resp.json()
        standings = {}
        for group in data.get("response", []):
            if not isinstance(group, list):
                group = [group]
            for team in group:
                name = team.get("team", {}).get("name", "")
                if not name:
                    continue
                games = team.get("games", {})
                win = games.get("win", {})
                lose = games.get("lose", {})
                total_w = int(win.get("total", 0))
                total_l = int(lose.get("total", 0))
                total_g = total_w + total_l
                standings[name] = {
                    "sport": "mlb",
                    "position": team.get("position", 0),
                    "wins": total_w,
                    "losses": total_l,
                    "win_pct": total_w / total_g if total_g > 0 else 0.5,
                    "conference": team.get("group", {}).get("name", ""),
                }
        return standings
    except Exception as e:
        logger.warning(f"MLB standings failed: {e}")
        return {}


def get_sport_signal(question, all_standings):
    """
    Check if any sport team matches the market question.
    Returns (probability, confidence) or (None, None).
    """
    if not all_standings:
        return None, None, None

    question_lower = question.lower()

    # Sport-specific keywords to help match
    sport_keywords = {
        "nhl": ["nhl", "hockey", "stanley cup", "hat trick"],
        "nba": ["nba", "basketball", "finals", "mvp", "all-star"],
        "nfl": ["nfl", "football", "super bowl", "touchdown", "quarterback"],
        "mlb": ["mlb", "baseball", "world series", "home run"],
    }

    playoff_keywords = [
        "playoff", "play-off", "playoffs", "qualify", "postseason",
        "championship", "finals", "super bowl", "world series", "stanley cup",
    ]

    for sport, standings in all_standings.items():
        # Check if question mentions this sport's keywords
        sport_match = any(kw in question_lower for kw in sport_keywords.get(sport, []))

        for team_name, stats in standings.items():
            if team_name.lower() not in question_lower:
                continue

            pos = stats.get("position", 0)
            win_pct = stats.get("win_pct", 0.5)

            is_playoff_market = any(kw in question_lower for kw in playoff_keywords)

            if is_playoff_market:
                # Use sport-specific base rates
                prob_table = {
                    "nhl": PLAYOFF_PROB_BY_POSITION,
                    "nba": NBA_PLAYOFF_PROB,
                    "nfl": NFL_PLAYOFF_PROB,
                    "mlb": MLB_PLAYOFF_PROB,
                }.get(sport, PLAYOFF_PROB_BY_POSITION)

                base_prob = prob_table.get(pos, 0.5)
                win_pct_adj = (win_pct - 0.50) * 0.3
                prob = max(0.02, min(0.98, base_prob + win_pct_adj))
                confidence = SPORT_DATA_WEIGHT * 0.9
            else:
                # Generic team market
                prob = win_pct
                confidence = SPORT_DATA_WEIGHT * 0.4

            return round(prob, 4), round(confidence, 4), stats

    return None, None, None


# ══════════════════════════════════════════════════════════════════════
# 4. SIGNAL COMBINER
# ══════════════════════════════════════════════════════════════════════

def combine_signals(signals):
    """
    Combine multiple (probability, confidence) signals into a single estimate.
    Uses confidence-weighted average.
    """
    valid = [(p, c) for p, c in signals if p is not None and c is not None and c > 0]
    if not valid:
        return None

    total_weight = sum(c for _, c in valid)
    if total_weight == 0:
        return None

    combined = sum(p * c for p, c in valid) / total_weight
    return round(max(0.02, min(0.98, combined)), 4)
