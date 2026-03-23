import os
from dotenv import load_dotenv

load_dotenv()

# --- API Credentials ---
POLYMARKET_PRIVATE_KEY = os.getenv("POLYMARKET_PRIVATE_KEY", "")
POLYMARKET_API_KEY = os.getenv("POLYMARKET_API_KEY", "")
POLYMARKET_API_SECRET = os.getenv("POLYMARKET_API_SECRET", "")
POLYMARKET_API_PASSPHRASE = os.getenv("POLYMARKET_API_PASSPHRASE", "")
HOCKEY_API_KEY = os.getenv("HOCKEY_API_KEY", "")
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
SPORTS_API_KEY = os.getenv("SPORTS_API_KEY", "")  # api-sports.io (covers all sports)

# --- Polymarket APIs ---
GAMMA_API_URL = "https://gamma-api.polymarket.com"
CLOB_HOST = "https://clob.polymarket.com"
CHAIN_ID = 137  # Polygon mainnet

# --- Scanning ---
SCAN_INTERVAL_SECONDS = 300       # 5 minutes between full scans
PRIORITY_SCAN_SECONDS = 60        # 1 minute for high-value markets
GAMMA_API_PAGE_LIMIT = 100        # markets per API page
MIN_VOLUME = 10_000               # minimum volume to consider
MAX_SPREAD = 0.05                 # maximum bid-ask spread
PRICE_RANGE = (0.05, 0.95)       # avoid near-certain outcomes
HIGH_VALUE_VOLUME = 100_000       # threshold for "high value" priority scanning

# --- Edge Detection ---
MIN_EDGE_THRESHOLD = 0.05         # 5% minimum estimated edge to act

# --- Signal Weights ---
SENTIMENT_WEIGHT = 0.25
MICROSTRUCTURE_WEIGHT = 0.35
SPORT_DATA_WEIGHT = 0.40

# --- AI Sentiment ---
# Gemini Flash is FREE (15 req/min). Claude is paid but higher quality.
GEMINI_MODEL = "gemini-2.0-flash"
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
AI_SENTIMENT_ENABLED = bool(GEMINI_API_KEY) or bool(ANTHROPIC_API_KEY)
AI_PROVIDER = "gemini" if GEMINI_API_KEY else ("claude" if ANTHROPIC_API_KEY else None)
AI_MAX_CALLS_PER_CYCLE = 30

# --- Risk Management ---
DRY_RUN = True                    # MUST be True until you're ready to risk real money
KELLY_FRACTION = 0.25             # quarter-Kelly (conservative)
MAX_POSITION_USDC = 50            # max $ per single market
MAX_DAILY_LOSS_USDC = 200         # stop trading if daily loss exceeds this
MAX_PORTFOLIO_EXPOSURE_USDC = 500 # total open position cap
MAX_POSITIONS = 10                # max concurrent positions
MIN_ORDER_USDC = 1.0              # Polymarket minimum order size
