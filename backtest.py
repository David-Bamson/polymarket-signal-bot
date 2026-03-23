"""
Backtesting Module
==================
Replays historical signals and compares estimated probabilities
against actual market outcomes to measure signal accuracy.

Usage:
    python backtest.py                        # backtest all logged signals
    python backtest.py --refresh              # update market outcomes first
    python backtest.py --report               # detailed breakdown by signal source
"""

import csv
import os
import sys
import argparse
import requests
from datetime import datetime
from config import GAMMA_API_URL
from logger import logger

SIGNALS_FILE = "signals_log.csv"
BACKTEST_REPORT = "backtest_report.txt"


def load_signals():
    """Load all logged signals from CSV."""
    if not os.path.exists(SIGNALS_FILE):
        print(f"No signals file found at {SIGNALS_FILE}")
        return []

    signals = []
    with open(SIGNALS_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            signals.append(row)

    return signals


def fetch_market_price(question):
    """
    Try to find the current price for a market by searching Gamma API.
    Returns current price or None.
    """
    try:
        resp = requests.get(
            f"{GAMMA_API_URL}/markets",
            params={"limit": 5, "closed": False},
            timeout=10,
        )
        # Search for matching market
        for m in resp.json():
            if m.get("question", "").lower() == question.lower():
                price = m.get("lastTradePrice")
                if price:
                    return float(price)
                return None

        # Also check closed markets
        resp = requests.get(
            f"{GAMMA_API_URL}/markets",
            params={"limit": 5, "closed": True},
            timeout=10,
        )
        for m in resp.json():
            if m.get("question", "").lower() == question.lower():
                outcome = m.get("outcome")
                if outcome == "Yes":
                    return 1.0
                elif outcome == "No":
                    return 0.0
                price = m.get("lastTradePrice")
                if price:
                    return float(price)

    except Exception as e:
        logger.warning(f"Failed to fetch price for '{question[:40]}': {e}")
    return None


def refresh_outcomes(signals):
    """Update signals with current market prices / outcomes."""
    updated = 0
    for sig in signals:
        if sig.get("outcome") and sig["outcome"] not in ("", "pending"):
            continue  # already has outcome

        question = sig.get("market", "")
        current_price = fetch_market_price(question)

        if current_price is not None:
            if current_price >= 0.95:
                sig["outcome"] = "YES"
                sig["exit_price"] = str(current_price)
            elif current_price <= 0.05:
                sig["outcome"] = "NO"
                sig["exit_price"] = str(current_price)
            else:
                sig["outcome"] = "pending"
                sig["exit_price"] = str(current_price)
            updated += 1

    print(f"Updated {updated} signal outcomes")
    return signals


def save_signals(signals):
    """Write updated signals back to CSV."""
    if not signals:
        return

    fieldnames = list(signals[0].keys())
    with open(SIGNALS_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(signals)

    print(f"Saved {len(signals)} signals to {SIGNALS_FILE}")


def compute_pnl(signal_row):
    """Compute theoretical PnL for a signal."""
    try:
        entry_price = float(signal_row.get("price_at_signal", 0))
        exit_price = float(signal_row.get("exit_price", 0))
        signal = signal_row.get("signal", "")

        if not entry_price or not exit_price:
            return None

        if "BUY" in signal:
            # Bought YES at entry_price
            pnl_pct = (exit_price - entry_price) / entry_price
        elif "SELL" in signal:
            # Sold YES / bought NO at entry_price
            pnl_pct = (entry_price - exit_price) / (1 - entry_price) if entry_price < 1 else 0
        else:
            return None

        return round(pnl_pct * 100, 2)
    except (ValueError, ZeroDivisionError):
        return None


def run_backtest(signals):
    """Analyze signal accuracy and profitability."""
    resolved = [s for s in signals if s.get("outcome") in ("YES", "NO")]
    pending = [s for s in signals if s.get("outcome") == "pending"]
    unknown = [s for s in signals if s.get("outcome") in ("", None)]

    print(f"\n{'='*60}")
    print(f"  BACKTEST REPORT")
    print(f"{'='*60}")
    print(f"\n  Total signals:  {len(signals)}")
    print(f"  Resolved:       {len(resolved)}")
    print(f"  Pending:        {len(pending)}")
    print(f"  Unknown:        {len(unknown)}")

    if not resolved:
        print("\n  No resolved markets yet. Run with --refresh to update outcomes.")
        print("  Or wait for markets to close.\n")
        return

    # Accuracy: did our signal direction match the outcome?
    correct = 0
    incorrect = 0
    total_pnl = 0.0
    pnl_list = []

    for s in resolved:
        signal = s.get("signal", "")
        outcome = s.get("outcome", "")
        pnl = compute_pnl(s)

        if "BUY" in signal and outcome == "YES":
            correct += 1
        elif "SELL" in signal and outcome == "NO":
            correct += 1
        else:
            incorrect += 1

        if pnl is not None:
            total_pnl += pnl
            pnl_list.append(pnl)

    accuracy = correct / len(resolved) * 100 if resolved else 0

    print(f"\n  --- Accuracy ---")
    print(f"  Correct calls:  {correct}/{len(resolved)} ({accuracy:.1f}%)")
    print(f"  Incorrect:      {incorrect}")

    if pnl_list:
        avg_pnl = total_pnl / len(pnl_list)
        winners = [p for p in pnl_list if p > 0]
        losers = [p for p in pnl_list if p < 0]
        avg_win = sum(winners) / len(winners) if winners else 0
        avg_loss = sum(losers) / len(losers) if losers else 0

        print(f"\n  --- Profitability ---")
        print(f"  Total PnL:      {total_pnl:+.1f}%")
        print(f"  Avg PnL/trade:  {avg_pnl:+.1f}%")
        print(f"  Winners:        {len(winners)} (avg +{avg_win:.1f}%)")
        print(f"  Losers:         {len(losers)} (avg {avg_loss:.1f}%)")

        if losers and winners:
            win_rate = len(winners) / (len(winners) + len(losers)) * 100
            profit_factor = sum(winners) / abs(sum(losers)) if sum(losers) != 0 else float('inf')
            print(f"  Win rate:       {win_rate:.1f}%")
            print(f"  Profit factor:  {profit_factor:.2f}x")

    # Breakdown by signal type
    print(f"\n  --- By Signal Source ---")
    source_stats = {}
    for s in resolved:
        signal_type = s.get("signal_type", "unknown")
        # Simplify: extract source names
        sources = signal_type.split(" + ")
        for src in sources:
            name = src.split("(")[0].strip()
            if name not in source_stats:
                source_stats[name] = {"correct": 0, "total": 0}
            source_stats[name]["total"] += 1
            signal = s.get("signal", "")
            outcome = s.get("outcome", "")
            if ("BUY" in signal and outcome == "YES") or ("SELL" in signal and outcome == "NO"):
                source_stats[name]["correct"] += 1

    for src, stats in sorted(source_stats.items()):
        acc = stats["correct"] / stats["total"] * 100 if stats["total"] else 0
        print(f"  {src:20s}: {stats['correct']}/{stats['total']} ({acc:.0f}%)")

    # Edge calibration: compare estimated prob vs actual outcome
    print(f"\n  --- Edge Calibration ---")
    buckets = {}  # bucket: [actual_outcomes]
    for s in resolved:
        est_prob = s.get("estimated_prob", "")
        if not est_prob:
            continue
        try:
            prob = float(est_prob)
        except ValueError:
            continue

        # Bucket by 10% intervals
        bucket = round(prob * 10) / 10
        bucket = max(0.0, min(1.0, bucket))
        bucket_key = f"{bucket:.1f}"

        if bucket_key not in buckets:
            buckets[bucket_key] = []
        buckets[bucket_key].append(1.0 if s["outcome"] == "YES" else 0.0)

    if buckets:
        print(f"  {'Predicted':>10s}  {'Actual':>8s}  {'Count':>6s}  {'Calibration':>12s}")
        for bucket_key in sorted(buckets.keys()):
            outcomes = buckets[bucket_key]
            predicted = float(bucket_key)
            actual = sum(outcomes) / len(outcomes)
            cal_error = abs(predicted - actual)
            bar = "***" if cal_error > 0.15 else ""
            print(f"  {predicted:>10.1f}  {actual:>8.2f}  {len(outcomes):>6d}  "
                  f"{cal_error:>+10.2f}  {bar}")

    # Pending markets preview
    if pending:
        print(f"\n  --- Pending Markets ({len(pending)}) ---")
        for s in pending[:5]:
            q = s.get("market", "")[:50]
            ep = s.get("exit_price", "?")
            sig = "BUY" if "BUY" in s.get("signal", "") else "SELL"
            print(f"  {sig:4s} | price now: {ep} | {q}")
        if len(pending) > 5:
            print(f"  ... and {len(pending) - 5} more")

    print(f"\n{'='*60}\n")

    # Save report to file
    _save_report(signals, resolved, correct, accuracy, total_pnl, source_stats, buckets)


def _save_report(signals, resolved, correct, accuracy, total_pnl, source_stats, buckets):
    """Save backtest report to text file."""
    try:
        with open(BACKTEST_REPORT, "w", encoding="utf-8") as f:
            f.write(f"Backtest Report — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
            f.write(f"{'='*60}\n\n")
            f.write(f"Total signals: {len(signals)}\n")
            f.write(f"Resolved: {len(resolved)}\n")
            f.write(f"Accuracy: {correct}/{len(resolved)} ({accuracy:.1f}%)\n")
            f.write(f"Total PnL: {total_pnl:+.1f}%\n\n")

            f.write("Signal Source Accuracy:\n")
            for src, stats in sorted(source_stats.items()):
                acc = stats["correct"] / stats["total"] * 100 if stats["total"] else 0
                f.write(f"  {src}: {stats['correct']}/{stats['total']} ({acc:.0f}%)\n")

            f.write("\nCalibration:\n")
            for bk in sorted(buckets.keys()):
                outcomes = buckets[bk]
                actual = sum(outcomes) / len(outcomes)
                f.write(f"  Predicted {bk} → Actual {actual:.2f} (n={len(outcomes)})\n")

        logger.info(f"Backtest report saved to {BACKTEST_REPORT}")
    except Exception as e:
        logger.warning(f"Failed to save report: {e}")


def main():
    parser = argparse.ArgumentParser(description="Backtest signal accuracy")
    parser.add_argument("--refresh", action="store_true",
                        help="Update market outcomes from Polymarket")
    parser.add_argument("--report", action="store_true",
                        help="Generate detailed report (default)")
    args = parser.parse_args()

    signals = load_signals()
    if not signals:
        print("No signals to backtest. Run the bot first to generate signals.")
        sys.exit(0)

    if args.refresh:
        signals = refresh_outcomes(signals)
        save_signals(signals)

    run_backtest(signals)


if __name__ == "__main__":
    main()
