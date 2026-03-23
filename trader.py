from config import (
    CLOB_HOST, CHAIN_ID, DRY_RUN,
    POLYMARKET_PRIVATE_KEY, POLYMARKET_API_KEY,
    POLYMARKET_API_SECRET, POLYMARKET_API_PASSPHRASE,
)
from logger import logger, log_trade


class PolymarketTrader:
    """Handles order execution against the Polymarket CLOB."""

    def __init__(self):
        self.client = None
        self._initialized = False

        if DRY_RUN:
            logger.info("Trader initialized in DRY RUN mode — no orders will be placed")
            return

        if not POLYMARKET_PRIVATE_KEY:
            logger.warning(
                "No POLYMARKET_PRIVATE_KEY set — trading disabled. "
                "Set it in .env to enable live trading."
            )
            return

        try:
            from py_clob_client.client import ClobClient

            self.client = ClobClient(
                host=CLOB_HOST,
                key=POLYMARKET_API_KEY,
                chain_id=CHAIN_ID,
                private_key=POLYMARKET_PRIVATE_KEY,
                signature_type=2,  # POLY_GNOSIS_SAFE
                api_secret=POLYMARKET_API_SECRET,
                api_passphrase=POLYMARKET_API_PASSPHRASE,
            )
            self._initialized = True
            logger.info("Trader initialized — LIVE trading enabled")
        except ImportError:
            logger.error(
                "py-clob-client not installed. Run: pip install py-clob-client"
            )
        except Exception as e:
            logger.error(f"Failed to initialize CLOB client: {e}")

    def derive_api_credentials(self):
        """
        One-time setup: derive API key/secret/passphrase from your private key.
        Run this once, then save the output to your .env file.
        """
        if not self.client:
            logger.error("Client not initialized")
            return None
        try:
            creds = self.client.create_or_derive_api_creds()
            logger.info("API credentials derived successfully")
            logger.info(f"API Key: {creds.api_key}")
            logger.info(f"API Secret: {creds.api_secret}")
            logger.info(f"API Passphrase: {creds.api_passphrase}")
            return creds
        except Exception as e:
            logger.error(f"Failed to derive API creds: {e}")
            return None

    def place_order(self, token_id, side, price, size, market_id="", question=""):
        """
        Place a limit order on the Polymarket CLOB.

        token_id: the CLOB token ID for the YES or NO outcome
        side: "BUY" or "SELL"
        price: limit price (0.01 to 0.99)
        size: position size in number of shares (not USDC)
        """
        if DRY_RUN:
            logger.info(
                f"[DRY RUN] Would {side} {size:.1f} shares @ ${price:.2f} "
                f"(${size * price:.2f} USDC) | {question[:60]}"
            )
            log_trade(market_id, question, side, price, size * price, "DRY_RUN", "simulated")
            return {"status": "dry_run", "order_id": "DRY_RUN"}

        if not self._initialized:
            logger.error("Cannot place order — trader not initialized")
            return None

        try:
            from py_clob_client.clob_types import OrderArgs

            order_args = OrderArgs(
                price=price,
                size=size,
                side=side,
                token_id=token_id,
            )
            result = self.client.create_and_post_order(order_args)

            order_id = result.get("orderID", result.get("id", "unknown"))
            status = result.get("status", "submitted")

            log_trade(market_id, question, side, price, size * price, order_id, status)
            logger.info(f"Order placed: {order_id} | {side} @ {price}")

            return result

        except Exception as e:
            logger.error(f"Order failed: {e}")
            log_trade(market_id, question, side, price, size * price, "FAILED", str(e))
            return None

    def cancel_order(self, order_id):
        if not self._initialized:
            return False
        try:
            self.client.cancel(order_id)
            logger.info(f"Order cancelled: {order_id}")
            return True
        except Exception as e:
            logger.error(f"Cancel failed: {e}")
            return False

    def get_open_orders(self):
        if not self._initialized:
            return []
        try:
            return self.client.get_orders()
        except Exception as e:
            logger.error(f"Failed to fetch orders: {e}")
            return []
