import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
from config import (
    GAMMA_API_URL, GAMMA_API_PAGE_LIMIT,
    MIN_VOLUME, MAX_SPREAD, PRICE_RANGE, MIN_EDGE_THRESHOLD,
    SCAN_INTERVAL_SECONDS, PRIORITY_SCAN_SECONDS,
    HIGH_VALUE_VOLUME, DRY_RUN, MIN_ORDER_USDC,
)
from signals import (
    get_sentiment_signal, get_microstructure_signal,
    get_all_sport_standings, get_sport_signal,
    combine_signals, reset_ai_call_count,
)
from risk import RiskManager, kelly_size
from trader import PolymarketTrader
from logger import logger, log_signal


def _create_session():
    """Create a requests session with retry logic and SSL handling."""
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=[500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


# Reusable session for all market fetches
_session = _create_session()


def fetch_all_markets():
    """Fetch ALL active markets from Gamma API with pagination."""
    global _session
    all_markets = []
    offset = 0

    while True:
        try:
            resp = _session.get(
                f"{GAMMA_API_URL}/markets",
                params={
                    "limit": GAMMA_API_PAGE_LIMIT,
                    "active": True,
                    "closed": False,
                    "offset": offset,
                },
                timeout=30,
            )
            resp.raise_for_status()
            batch = resp.json()
        except Exception as e:
            logger.error(f"Failed to fetch markets at offset {offset}: {e}")
            if offset == 0:
                logger.info("Retrying with fresh session...")
                _session = _create_session()
                try:
                    resp = _session.get(
                        f"{GAMMA_API_URL}/markets",
                        params={
                            "limit": GAMMA_API_PAGE_LIMIT,
                            "active": True,
                            "closed": False,
                            "offset": offset,
                        },
                        timeout=30,
                    )
                    resp.raise_for_status()
                    batch = resp.json()
                except Exception as e2:
                    logger.error(f"Retry also failed: {e2}")
                    break
            else:
                break

        if not batch:
            break

        all_markets.extend(batch)
        offset += len(batch)

        if len(batch) < GAMMA_API_PAGE_LIMIT:
            break

        time.sleep(0.5)

    return all_markets


def filter_tradeable(markets):
    """Filter to liquid, tradeable markets with reasonable prices."""
    results = []

    for m in markets:
        volume = float(m.get("volume", 0))
        best_bid = m.get("bestBid")
        best_ask = m.get("bestAsk")
        last_price = m.get("lastTradePrice")

        if not all([best_bid, best_ask, last_price]):
            continue

        try:
            best_bid = float(best_bid)
            best_ask = float(best_ask)
            last_price = float(last_price)
        except (ValueError, TypeError):
            continue

        spread = best_ask - best_bid

        if volume < MIN_VOLUME:
            continue
        if spread > MAX_SPREAD:
            continue
        if not (PRICE_RANGE[0] <= last_price <= PRICE_RANGE[1]):
            continue

        m["_spread"] = round(spread, 4)
        m["_last_price"] = last_price
        m["_volume"] = volume
        m["_best_bid"] = best_bid
        m["_best_ask"] = best_ask
        results.append(m)

    # Sort by volume descending — analyze highest-volume markets first
    # (most likely to have real mispricings + best liquidity for execution)
    results.sort(key=lambda x: x["_volume"], reverse=True)
    return results


def analyze_market(market, all_standings):
    """
    Run all signals on a single market.
    Returns dict with analysis or None if no edge found.
    """
    question = market.get("question", "")
    last_price = market["_last_price"]

    # Gather signals: each returns (probability, confidence)
    signals = []

    # 1. Claude AI / news sentiment (strongest new signal)
    sentiment = get_sentiment_signal(question)
    signals.append(sentiment)
    time.sleep(0.3)

    # 2. Market microstructure + orderbook depth
    micro = get_microstructure_signal(market)
    signals.append(micro)

    # 3. Sport-specific data (NHL + NBA + NFL + MLB)
    sport_prob, sport_conf, sport_stats = get_sport_signal(question, all_standings)
    if sport_prob is not None:
        signals.append((sport_prob, sport_conf))

    # Combine into single probability estimate
    estimated_prob = combine_signals(signals)
    if estimated_prob is None:
        return None

    # Determine side and edge
    edge_yes = estimated_prob - last_price
    edge_no = last_price - estimated_prob

    if edge_yes >= MIN_EDGE_THRESHOLD:
        side = "BUY"
        edge = edge_yes
        exec_price = market["_best_ask"]
    elif edge_no >= MIN_EDGE_THRESHOLD:
        side = "SELL"
        edge = edge_no
        exec_price = market["_best_bid"]
    else:
        return None

    # Build token ID (handle string or list format)
    token_id = ""
    clob_ids = market.get("clobTokenIds")
    if isinstance(clob_ids, list) and clob_ids:
        token_id = clob_ids[0]
    elif isinstance(clob_ids, str):
        try:
            import json
            parsed = json.loads(clob_ids)
            if parsed:
                token_id = parsed[0]
        except Exception:
            token_id = clob_ids

    return {
        "question": question,
        "market_id": market.get("id", market.get("conditionId", "")),
        "token_id": token_id,
        "side": side,
        "edge": round(edge, 4),
        "estimated_prob": estimated_prob,
        "last_price": last_price,
        "exec_price": exec_price,
        "spread": market["_spread"],
        "volume": market["_volume"],
        "signal_sources": [
            f"sentiment({sentiment[0]:.2f}, conf={sentiment[1]:.2f})",
            f"micro({micro[0]:.2f}, conf={micro[1]:.2f})",
        ] + (
            [f"sport({sport_prob:.2f}, conf={sport_conf:.2f})"]
            if sport_prob is not None else []
        ),
        "sport_stats": sport_stats,
    }


def run_scan_cycle(trader, risk_manager, bankroll=1000.0):
    """Execute one full scan cycle."""
    logger.info("=" * 60)
    logger.info("Starting scan cycle...")
    reset_ai_call_count()

    # Fetch markets
    markets = fetch_all_markets()
    tradeable = filter_tradeable(markets)
    logger.info(f"Scanned {len(markets)} markets, {len(tradeable)} pass filters")

    # Fetch ALL sport standings (NHL + NBA + NFL + MLB)
    all_standings = get_all_sport_standings()
    for sport, standings in all_standings.items():
        logger.info(f"Loaded {sport.upper()} standings: {len(standings)} teams")

    opportunities = []
    portfolio_full = False

    for market in tradeable:
        # Stop early if portfolio is maxed out
        if portfolio_full:
            break

        try:
            analysis = analyze_market(market, all_standings)
        except Exception as e:
            logger.warning(f"Analysis failed for '{market.get('question', '')[:50]}': {e}")
            continue

        if analysis is None:
            continue

        # Position sizing via Kelly criterion
        size_usdc = kelly_size(
            edge=analysis["edge"],
            market_price=analysis["last_price"],
            bankroll=bankroll,
        )

        if size_usdc < MIN_ORDER_USDC:
            continue

        # Risk check
        allowed, reason = risk_manager.can_trade(analysis["market_id"], size_usdc)
        if not allowed:
            if "exposure limit" in reason or "max concurrent" in reason:
                logger.info(f"Portfolio full — stopping scan. ({reason})")
                portfolio_full = True
            else:
                logger.info(f"Risk blocked ({reason}): {analysis['question'][:50]}")
            continue

        analysis["size_usdc"] = size_usdc
        opportunities.append(analysis)

        # Build signal description
        signal_desc = (
            f"{analysis['side']} — Edge: {analysis['edge']:.1%} | "
            f"Est. prob: {analysis['estimated_prob']:.2f} vs price {analysis['last_price']:.2f}"
        )

        # Log the signal
        log_signal(
            question=analysis["question"],
            price=analysis["last_price"],
            volume=analysis["volume"],
            spread=analysis["spread"],
            signal=signal_desc,
            score=analysis["edge"],
            signal_type=" + ".join(analysis["signal_sources"]),
            estimated_prob=analysis["estimated_prob"],
            edge=analysis["edge"],
            nhl_stats=analysis.get("sport_stats"),
        )

        # Execute trade
        shares = size_usdc / analysis["exec_price"] if analysis["exec_price"] > 0 else 0
        result = trader.place_order(
            token_id=analysis["token_id"],
            side=analysis["side"],
            price=analysis["exec_price"],
            size=round(shares, 2),
            market_id=analysis["market_id"],
            question=analysis["question"],
        )

        if result:
            risk_manager.record_position(
                market_id=analysis["market_id"],
                side=analysis["side"],
                size=size_usdc,
                entry_price=analysis["exec_price"],
                question=analysis["question"],
            )

    print_scan_summary(opportunities, risk_manager)
    return opportunities


def run_priority_scan(trader, risk_manager, bankroll=1000.0):
    """
    Fast scan of high-volume markets only.
    Runs more frequently to catch breaking news mispricings.
    """
    logger.info("--- Priority scan (high-value markets) ---")

    markets = fetch_all_markets()
    # Only high-volume markets for speed
    tradeable = [
        m for m in filter_tradeable(markets)
        if m["_volume"] >= HIGH_VALUE_VOLUME
    ]

    if not tradeable:
        return []

    logger.info(f"Priority scan: {len(tradeable)} high-value markets")

    all_standings = get_all_sport_standings()
    opportunities = []

    for market in tradeable:
        try:
            analysis = analyze_market(market, all_standings)
        except Exception:
            continue

        if analysis is None:
            continue

        size_usdc = kelly_size(
            edge=analysis["edge"],
            market_price=analysis["last_price"],
            bankroll=bankroll,
        )
        if size_usdc < MIN_ORDER_USDC:
            continue

        allowed, reason = risk_manager.can_trade(analysis["market_id"], size_usdc)
        if not allowed:
            continue

        analysis["size_usdc"] = size_usdc
        opportunities.append(analysis)

        signal_desc = (
            f"[PRIORITY] {analysis['side']} — Edge: {analysis['edge']:.1%} | "
            f"Est. prob: {analysis['estimated_prob']:.2f} vs price {analysis['last_price']:.2f}"
        )

        log_signal(
            question=analysis["question"],
            price=analysis["last_price"],
            volume=analysis["volume"],
            spread=analysis["spread"],
            signal=signal_desc,
            score=analysis["edge"],
            signal_type=" + ".join(analysis["signal_sources"]),
            estimated_prob=analysis["estimated_prob"],
            edge=analysis["edge"],
            nhl_stats=analysis.get("sport_stats"),
        )

        shares = size_usdc / analysis["exec_price"] if analysis["exec_price"] > 0 else 0
        result = trader.place_order(
            token_id=analysis["token_id"],
            side=analysis["side"],
            price=analysis["exec_price"],
            size=round(shares, 2),
            market_id=analysis["market_id"],
            question=analysis["question"],
        )

        if result:
            risk_manager.record_position(
                market_id=analysis["market_id"],
                side=analysis["side"],
                size=size_usdc,
                entry_price=analysis["exec_price"],
                question=analysis["question"],
            )

    if opportunities:
        print_scan_summary(opportunities, risk_manager)
    return opportunities


def print_scan_summary(opportunities, risk_manager):
    """Print human-readable scan results."""
    if not opportunities:
        logger.info("No opportunities found this cycle.")
        print("\nNo strong opportunities found.\n")
        return

    mode = "DRY RUN" if DRY_RUN else "LIVE"
    logger.info(f"Found {len(opportunities)} opportunities [{mode}]")
    print(f"\n{'='*60}")
    print(f"  {len(opportunities)} OPPORTUNITIES FOUND [{mode}]")
    print(f"{'='*60}\n")

    for o in opportunities:
        print(f"  Market:  {o['question']}")
        print(f"  Signal:  {o['side']} | Edge: {o['edge']:.1%} | "
              f"Est prob: {o['estimated_prob']:.2f} vs price {o['last_price']:.2f}")
        print(f"  Size:    ${o['size_usdc']:.2f} | Volume: ${o['volume']:,.0f} | "
              f"Spread: {o['spread']:.4f}")
        print(f"  Sources: {', '.join(o['signal_sources'])}")
        if o.get("sport_stats"):
            s = o["sport_stats"]
            sport = s.get("sport", "?").upper()
            print(f"  {sport}:     Pos {s.get('position')} | "
                  f"Win% {s.get('win_pct', 0):.3f} | "
                  f"Conf: {s.get('conference', 'N/A')}")
        print(f"  {'─'*56}")

    summary = risk_manager.get_portfolio_summary()
    print(f"\n  Portfolio: {summary['open_positions']} positions | "
          f"${summary['total_exposure']:.2f} exposed | "
          f"Daily PnL: ${summary['daily_pnl']:+.2f}\n")


def main_loop(bankroll=1000.0):
    """
    Continuous scanning loop with dual-speed scanning:
    - Priority scan every 60s (high-volume markets only, catches breaking news)
    - Full scan every 300s (all markets)
    """
    trader = PolymarketTrader()
    risk_manager = RiskManager()

    mode = "DRY RUN" if DRY_RUN else "LIVE"
    logger.info(f"Bot started in {mode} mode | Bankroll: ${bankroll}")
    logger.info(
        f"Full scan every {SCAN_INTERVAL_SECONDS}s | "
        f"Priority scan every {PRIORITY_SCAN_SECONDS}s"
    )

    last_full_scan = 0
    last_priority_scan = 0

    while True:
        now = time.time()
        try:
            # Full scan
            if now - last_full_scan >= SCAN_INTERVAL_SECONDS:
                run_scan_cycle(trader, risk_manager, bankroll)
                last_full_scan = now
                last_priority_scan = now  # no need for priority right after full

            # Priority scan (between full scans)
            elif now - last_priority_scan >= PRIORITY_SCAN_SECONDS:
                run_priority_scan(trader, risk_manager, bankroll)
                last_priority_scan = now

        except KeyboardInterrupt:
            logger.info("Shutting down...")
            break
        except Exception as e:
            logger.error(f"Scan cycle failed: {e}", exc_info=True)

        # Sleep in short intervals so Ctrl+C is responsive
        try:
            time.sleep(5)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            break
