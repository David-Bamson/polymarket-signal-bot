# Polymarket Signal Bot

A Python bot that scans Polymarket prediction markets and flags potential mispricings using multiple signal sources.

## How it works

1. Pulls live markets from the Polymarket API
2. Filters for quality markets (volume, spread, price range)
3. Scores each market using Google News sentiment analysis
4. Cross-references NHL standings data from api-sports.io
5. Flags BUY/SELL signals when multiple signals align

## Signal Logic

- **Sentiment score** — scans Google News headlines for positive/negative keywords
- **NHL data signal** — uses real standings data (position, points, win%, playoff status)
- **Combined score threshold** — only flags markets where both signals agree

## Tech Stack

- Python
- `requests` — API calls and web scraping
- `beautifulsoup4` — HTML parsing for Google News
- Polymarket Gamma API
- api-sports.io Hockey API

## Setup
```bash
pip install requests beautifulsoup4
```

Add your api-sports.io key to `bot_v2.py`:
```python
HOCKEY_API_KEY = "your_key_here"
```

Then run:
```bash
python bot_v2.py


## Sample Output
```
⚡ 3 opportunities found:

Market: Will the Tampa Bay Lightning win the 2026 NHL Stanley Cup?
Price: 0.157 | Volume: $215,972.38 | Spread: 0.01
NHL Data: Pos 3 | Pts 102 | Win% 0.5 | Playoffs: True
Signal: 🟢 BUY — Score: 12 | Type: NHL+Sentiment
```

## Status

Prototype 1 — signal detection only, no auto-trading.