import csv
import os
from datetime import datetime

LOG_FILE = "signals_log.csv"

def log_signal(question, price, volume, spread, signal ,score, signal_type, nhl_stats=None):
    file_exists = os.path.exists(LOG_FILE)

    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        if not file_exists:
            writer.writerow([
              "timestamp", "market", "price_at_signal", "volume", 
                "spread", "signal", "score", "signal_type",
                "nhl_position", "nhl_points", "nhl_win_pct", "nhl_playoffs",
                "outcome", "exit_price", "profit_loss"  
            ])

            nhl_position = nhl_stats["position"] if nhl_stats else""
            nhl_points = nhl_stats["points"] if nhl_stats else""
            nhl_win_pct = nhl_stats["win_pct"] if nhl_stats else""
            nhl_playoffs = nhl_stats["made_playoffs"] if nhl_stats else""

            print(f"Writing row for: {question}")

            writer.writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                question,
                price,
                volume,
                spread,
                signal,
                score,
                signal_type,
                nhl_position,
                nhl_points,
                nhl_win_pct,
                nhl_playoffs,
                "",
                "",
                "",
            ])

            print(f"✅ Signal logged: {question}")