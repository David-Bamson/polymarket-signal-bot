import csv
import os
import logging
from datetime import datetime

LOG_FILE = "signals_log.csv"
TRADE_LOG_FILE = "trades_log.csv"

# Structured console + file logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("polybot")


def log_signal(question, price, volume, spread, signal, score, signal_type,
               estimated_prob=None, edge=None, nhl_stats=None):
    file_exists = os.path.exists(LOG_FILE)

    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        if not file_exists:
            writer.writerow([
                "timestamp", "market", "price_at_signal", "volume",
                "spread", "signal", "score", "signal_type",
                "estimated_prob", "edge",
                "nhl_position", "nhl_points", "nhl_win_pct", "nhl_playoffs",
                "outcome", "exit_price", "profit_loss",
            ])

        nhl_position = nhl_stats["position"] if nhl_stats else ""
        nhl_points = nhl_stats["points"] if nhl_stats else ""
        nhl_win_pct = nhl_stats["win_pct"] if nhl_stats else ""
        nhl_playoffs = nhl_stats["made_playoffs"] if nhl_stats else ""

        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            question,
            price,
            volume,
            spread,
            signal,
            score,
            signal_type,
            round(estimated_prob, 4) if estimated_prob is not None else "",
            round(edge, 4) if edge is not None else "",
            nhl_position,
            nhl_points,
            nhl_win_pct,
            nhl_playoffs,
            "", "", "",  # outcome, exit_price, profit_loss (filled later)
        ])

    logger.info(f"Signal logged: {signal} | {question[:60]}...")


def log_trade(market_id, question, side, price, size, order_id, status):
    file_exists = os.path.exists(TRADE_LOG_FILE)

    with open(TRADE_LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        if not file_exists:
            writer.writerow([
                "timestamp", "market_id", "market", "side", "price",
                "size_usdc", "order_id", "status",
            ])

        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            market_id, question, side, price, size, order_id, status,
        ])

    logger.info(f"Trade: {side} ${size:.2f} @ {price} | {question[:50]}...")
