import json
import os
from datetime import date
from config import (
    KELLY_FRACTION, MAX_POSITION_USDC, MAX_DAILY_LOSS_USDC,
    MAX_PORTFOLIO_EXPOSURE_USDC, MAX_POSITIONS, MIN_ORDER_USDC,
)
from logger import logger

STATE_FILE = "portfolio_state.json"


def kelly_size(edge, market_price, bankroll, fraction=KELLY_FRACTION):
    """
    Kelly criterion position sizing.

    edge: estimated_prob - market_price (for BUY YES)
    market_price: current market price
    bankroll: available capital in USDC
    fraction: Kelly fraction (0.25 = quarter-Kelly, conservative)

    Returns recommended bet size in USDC.
    """
    if edge <= 0 or market_price <= 0 or market_price >= 1:
        return 0.0

    # Estimated true probability
    p = market_price + edge
    p = max(0.01, min(0.99, p))
    q = 1 - p

    # Decimal odds: if you buy YES at market_price, you get 1.0 back if correct
    # Net profit per dollar risked = (1 - market_price) / market_price
    b = (1 - market_price) / market_price

    if b <= 0:
        return 0.0

    kelly = (b * p - q) / b
    if kelly <= 0:
        return 0.0

    bet_fraction = kelly * fraction
    size = bankroll * bet_fraction

    # Cap at max position size
    size = min(size, MAX_POSITION_USDC)

    return round(size, 2)


class RiskManager:
    def __init__(self):
        self.open_positions = {}
        self.daily_pnl = 0.0
        self.today = str(date.today())
        self._load_state()

    def _load_state(self):
        if not os.path.exists(STATE_FILE):
            return
        try:
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
            self.open_positions = state.get("open_positions", {})
            saved_date = state.get("date", "")
            if saved_date == self.today:
                self.daily_pnl = state.get("daily_pnl", 0.0)
            else:
                # New day — reset daily PnL
                self.daily_pnl = 0.0
            logger.info(
                f"Loaded state: {len(self.open_positions)} positions, "
                f"daily PnL: ${self.daily_pnl:.2f}"
            )
        except Exception as e:
            logger.warning(f"Failed to load state: {e}")

    def _save_state(self):
        state = {
            "date": self.today,
            "daily_pnl": self.daily_pnl,
            "open_positions": self.open_positions,
        }
        try:
            with open(STATE_FILE, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save state: {e}")

    def can_trade(self, market_id, proposed_size):
        """
        Check all risk limits before allowing a trade.
        Returns (allowed: bool, reason: str).
        """
        # 1. Daily loss limit
        if self.daily_pnl <= -MAX_DAILY_LOSS_USDC:
            return False, "daily loss limit reached"

        # 2. Single position limit
        if proposed_size > MAX_POSITION_USDC:
            return False, f"size ${proposed_size:.2f} exceeds max ${MAX_POSITION_USDC}"

        # 3. Minimum order size
        if proposed_size < MIN_ORDER_USDC:
            return False, f"size ${proposed_size:.2f} below minimum ${MIN_ORDER_USDC}"

        # 4. Portfolio exposure cap
        total_exposure = sum(
            p["size"] for p in self.open_positions.values()
        )
        if total_exposure + proposed_size > MAX_PORTFOLIO_EXPOSURE_USDC:
            return False, "portfolio exposure limit reached"

        # 5. Max concurrent positions
        if len(self.open_positions) >= MAX_POSITIONS:
            return False, "max concurrent positions reached"

        # 6. No doubling down
        if market_id in self.open_positions:
            return False, "already have a position in this market"

        return True, "ok"

    def record_position(self, market_id, side, size, entry_price, question=""):
        self.open_positions[market_id] = {
            "side": side,
            "size": size,
            "entry_price": entry_price,
            "question": question[:80],
        }
        self._save_state()
        logger.info(f"Position opened: {side} ${size:.2f} @ {entry_price} | {question[:50]}")

    def close_position(self, market_id, exit_price):
        if market_id not in self.open_positions:
            return 0.0

        pos = self.open_positions.pop(market_id)
        if pos["side"] == "BUY":
            pnl = (exit_price - pos["entry_price"]) * (pos["size"] / pos["entry_price"])
        else:
            pnl = (pos["entry_price"] - exit_price) * (pos["size"] / pos["entry_price"])

        self.daily_pnl += pnl
        self._save_state()
        logger.info(
            f"Position closed: {pos['question'][:40]} | PnL: ${pnl:+.2f} | "
            f"Daily PnL: ${self.daily_pnl:+.2f}"
        )
        return pnl

    def get_portfolio_summary(self):
        total_exposure = sum(p["size"] for p in self.open_positions.values())
        return {
            "open_positions": len(self.open_positions),
            "total_exposure": round(total_exposure, 2),
            "daily_pnl": round(self.daily_pnl, 2),
            "positions": self.open_positions,
        }
