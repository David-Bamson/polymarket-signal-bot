"""
Polymarket Signal Bot v2
========================
Scans Polymarket for mispriced markets using Claude AI sentiment,
orderbook depth analysis, market microstructure, and multi-sport
data (NHL/NBA/NFL/MLB). Sizes positions with Kelly criterion and
manages risk automatically.

Usage:
    python bot_v2.py                  # dry-run scan loop (default, safe)
    python bot_v2.py --scan-once      # single scan cycle
    python bot_v2.py --live           # REAL trading (requires funded wallet)
    python bot_v2.py --bankroll 500   # set bankroll for position sizing
    python bot_v2.py --setup          # derive Polymarket API credentials
    python bot_v2.py --backtest       # run backtest on logged signals
"""

import argparse
import config


def main():
    parser = argparse.ArgumentParser(description="Polymarket Signal Bot")
    parser.add_argument(
        "--live", action="store_true",
        help="Enable LIVE trading (real money). Default is dry-run.",
    )
    parser.add_argument(
        "--scan-once", action="store_true",
        help="Run a single scan cycle and exit.",
    )
    parser.add_argument(
        "--bankroll", type=float, default=1000.0,
        help="Available bankroll in USDC for position sizing (default: 1000).",
    )
    parser.add_argument(
        "--setup", action="store_true",
        help="Derive Polymarket CLOB API credentials from your private key.",
    )
    parser.add_argument(
        "--backtest", action="store_true",
        help="Run backtest analysis on logged signals.",
    )
    parser.add_argument(
        "--refresh", action="store_true",
        help="With --backtest: update market outcomes before analysis.",
    )
    args = parser.parse_args()

    # --- Backtest mode ---
    if args.backtest:
        from backtest import load_signals, refresh_outcomes, save_signals, run_backtest
        signals = load_signals()
        if not signals:
            print("No signals to backtest. Run the bot first.")
            return
        if args.refresh:
            signals = refresh_outcomes(signals)
            save_signals(signals)
        run_backtest(signals)
        return

    # --- Setup mode ---
    if args.setup:
        config.DRY_RUN = False  # need real client for setup
        from trader import PolymarketTrader
        trader = PolymarketTrader()
        creds = trader.derive_api_credentials()
        if creds:
            print("\nAdd these to your .env file:")
            print(f"  POLYMARKET_API_KEY={creds.api_key}")
            print(f"  POLYMARKET_API_SECRET={creds.api_secret}")
            print(f"  POLYMARKET_API_PASSPHRASE={creds.api_passphrase}")
        return

    # --- Trading mode ---
    if args.live:
        config.DRY_RUN = False
        print("\n  *** LIVE TRADING MODE — REAL MONEY AT RISK ***\n")
    else:
        print("\n  Dry-run mode — no real orders will be placed.\n")

    # Show what's enabled
    print(f"  Bankroll:     ${args.bankroll:,.2f}")
    if config.AI_PROVIDER == "gemini":
        ai_status = "GEMINI FLASH (free)"
    elif config.AI_PROVIDER == "claude":
        ai_status = "CLAUDE (paid)"
    else:
        ai_status = "DISABLED (set GEMINI_API_KEY in .env — it's free)"
    print(f"  AI Sentiment: {ai_status}")
    print(f"  Sports API:   {'ENABLED' if config.SPORTS_API_KEY or config.HOCKEY_API_KEY else 'DISABLED'}")
    print(f"  News API:     {'ENABLED' if config.NEWS_API_KEY else 'DISABLED (using Google fallback)'}")
    print()

    from scanner import main_loop, run_scan_cycle
    from trader import PolymarketTrader
    from risk import RiskManager

    if args.scan_once:
        trader = PolymarketTrader()
        risk_manager = RiskManager()
        run_scan_cycle(trader, risk_manager, bankroll=args.bankroll)
    else:
        main_loop(bankroll=args.bankroll)


if __name__ == "__main__":
    main()
