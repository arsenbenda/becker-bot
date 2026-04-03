"""
Backtester v2 — Uses CLOB price history for resolved markets.
Simulates entry at historical prices, tests estimation + exit against resolution.
"""
import json
import sqlite3
import math
import numpy as np
from pathlib import Path
from collections import defaultdict

import sys
sys.path.insert(0, "/opt/becker-bot")
from becker_bot_v4 import (
    infer_category, edge_is_real,
    calculate_ev, calculate_taker_fee, kelly_size
)
from smart_estimator import becker_bias_adjustment

DB_PATH = Path("/opt/becker-bot/backtest_data.db")


def load_backtestable_markets():
    """Load resolved markets that have CLOB price history."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Get markets with price history and known resolution
    c.execute("""
        SELECT m.market_id, m.question, m.category, m.end_date,
               m.resolved_to, m.volume, m.liquidity, m.clob_yes_token
        FROM markets m
        WHERE m.resolved_to IN ('YES', 'NO')
        AND m.market_id IN (SELECT DISTINCT market_id FROM price_history)
        ORDER BY m.end_date DESC
    """)
    markets = []
    for row in c.fetchall():
        mid = row[0]
        # Get price history
        c.execute("""
            SELECT timestamp, price FROM price_history
            WHERE market_id = ? ORDER BY timestamp ASC
        """, (mid,))
        prices = [(r[0], r[1]) for r in c.fetchall()]
        if len(prices) < 10:
            continue
        markets.append({
            "market_id": mid,
            "question": row[1],
            "category": row[2],
            "end_date": row[3],
            "resolved_to": row[4],
            "volume": row[5],
            "liquidity": row[6],
            "token_id": row[7],
            "price_history": prices,
        })

    conn.close()
    return markets


def sample_entry_points(price_history, n_samples=3):
    """
    Sample entry points from the price series.
    Takes prices from early, mid, and late in the market's life.
    Excludes the last 10% of the series (too close to resolution).
    """
    cutoff = int(len(price_history) * 0.9)
    if cutoff < 5:
        return []

    usable = price_history[:cutoff]
    indices = []

    # Early (10-20%), mid (40-60%), late (70-85%)
    ranges = [(0.10, 0.20), (0.40, 0.60), (0.70, 0.85)]
    for lo, hi in ranges:
        start = int(len(usable) * lo)
        end = int(len(usable) * hi)
        if start < end:
            mid_idx = (start + end) // 2
            indices.append(mid_idx)

    entries = []
    for idx in indices:
        ts, price = usable[idx]
        if 0.15 <= price <= 0.85:
            entries.append({"timestamp": ts, "price": price, "index": idx})

    return entries


def simulate_trade(entry_price, category, resolved_yes, min_edge=0.10,
                   kelly_frac=0.15, max_bet_pct=0.06, bankroll=500.0):
    """Simulate bot's decision at a given entry price."""

    # Becker estimation
    est_prob = becker_bias_adjustment(entry_price, category)

    # Edge check
    edge_check = edge_is_real(entry_price, est_prob, min_edge)
    if not edge_check["passed"]:
        return {"action": "FILTERED", "reason": "insufficient_edge"}

    # EV
    ev = calculate_ev(entry_price, est_prob, category)
    if ev["best_side"] == "SKIP" or ev["best_ev"] < 0.02:
        return {"action": "FILTERED", "reason": "negative_ev"}

    # Price tier filter
    side = ev["best_side"]
    side_price = entry_price if side == "YES" else (1.0 - entry_price)
    if side_price < 0.15:
        return {"action": "FILTERED", "reason": "price_tier"}

    # Half-Kelly for expensive
    kf = kelly_frac
    mb = max_bet_pct
    if side_price >= 0.80:
        kf *= 0.5
        mb *= 0.5

    k = kelly_size(bankroll, entry_price, est_prob, side, kf, mb)
    if k["bet"] <= 0:
        return {"action": "FILTERED", "reason": "kelly_zero"}

    # Resolution outcome
    if side == "YES":
        won = resolved_yes
        cost = entry_price
    else:
        won = not resolved_yes
        cost = 1.0 - entry_price

    if won:
        pnl = (1.0 - cost) * k["contracts"]
    else:
        pnl = -cost * k["contracts"]

    entry_fee = calculate_taker_fee(cost, category)
    exit_fee = calculate_taker_fee(1.0 if won else 0.0, category)
    total_fees = (entry_fee + exit_fee) * k["contracts"]

    return {
        "action": "TRADE",
        "side": side,
        "entry_price": round(cost, 4),
        "est_prob": round(est_prob, 4),
        "edge": round(edge_check["abs_edge"], 4),
        "ev": round(ev["best_ev"], 4),
        "bet": round(k["bet"], 2),
        "contracts": round(k["contracts"], 2),
        "won": won,
        "pnl": round(pnl, 2),
        "net_pnl": round(pnl - total_fees, 2),
        "fees": round(total_fees, 4),
    }


def brier_score(predictions, outcomes):
    if not predictions:
        return None
    return round(np.mean([(p - o) ** 2 for p, o in zip(predictions, outcomes)]), 6)


def calibration_table(predictions, outcomes, n_bins=10):
    bins = defaultdict(lambda: {"predictions": [], "outcomes": []})
    for p, o in zip(predictions, outcomes):
        bucket = min(int(p * n_bins), n_bins - 1)
        bins[bucket]["predictions"].append(p)
        bins[bucket]["outcomes"].append(o)

    table = []
    for i in range(n_bins):
        b = bins[i]
        if not b["predictions"]:
            continue
        table.append({
            "bin": f"{i/n_bins:.1f}-{(i+1)/n_bins:.1f}",
            "avg_predicted": round(np.mean(b["predictions"]), 3),
            "actual_frequency": round(np.mean(b["outcomes"]), 3),
            "gap": round(np.mean(b["outcomes"]) - np.mean(b["predictions"]), 3),
            "count": len(b["predictions"]),
        })
    return table


def run_backtest(min_edge=0.10):
    markets = load_backtestable_markets()
    print(f"Markets with price history + resolution: {len(markets)}")

    if not markets:
        print("No backtestable markets found.")
        return

    # Stats
    trades = []
    filtered = defaultdict(int)
    all_preds = []
    all_outcomes = []
    cat_results = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0,
                                        "net_pnl": 0, "fees": 0})

    for m in markets:
        resolved_yes = m["resolved_to"] == "YES"
        entries = sample_entry_points(m["price_history"])

        # Collect all price points for calibration
        for ts, price in m["price_history"]:
            if 0.05 < price < 0.95:
                est = becker_bias_adjustment(price, m["category"])
                all_preds.append(est)
                all_outcomes.append(1.0 if resolved_yes else 0.0)

        for entry in entries:
            result = simulate_trade(
                entry["price"], m["category"], resolved_yes, min_edge=min_edge
            )
            if result["action"] == "FILTERED":
                filtered[result["reason"]] += 1
                continue

            result["question"] = m["question"][:70]
            result["category"] = m["category"]
            trades.append(result)

            cat = m["category"]
            cat_results[cat]["trades"] += 1
            if result["won"]:
                cat_results[cat]["wins"] += 1
            cat_results[cat]["pnl"] += result["pnl"]
            cat_results[cat]["net_pnl"] += result["net_pnl"]
            cat_results[cat]["fees"] += result["fees"]

    # ── Print Results ──
    print(f"\n{'='*60}")
    print(f"BACKTEST RESULTS (Layer 3 Becker only)")
    print(f"{'='*60}")

    print(f"\nFilter cascade:")
    for reason, count in sorted(filtered.items(), key=lambda x: -x[1]):
        print(f"  {reason:25s} {count:>6}")

    if not trades:
        print("\nNo trades passed filters.")
    else:
        wins = sum(1 for t in trades if t["won"])
        total_pnl = sum(t["pnl"] for t in trades)
        total_net = sum(t["net_pnl"] for t in trades)
        total_fees = sum(t["fees"] for t in trades)
        gross_profit = sum(t["pnl"] for t in trades if t["pnl"] > 0)
        gross_loss = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
        pf = gross_profit / gross_loss if gross_loss > 0 else 999

        running = 0
        peak = 0
        max_dd = 0
        for t in trades:
            running += t["net_pnl"]
            peak = max(peak, running)
            max_dd = max(max_dd, peak - running)

        print(f"\nTrade Summary:")
        print(f"  Total trades:     {len(trades)}")
        print(f"  Win rate:         {wins/len(trades):.1%} ({wins}/{len(trades)})")
        print(f"  Profit factor:    {pf:.2f}")
        print(f"  Gross P&L:        ${total_pnl:+.2f}")
        print(f"  Total fees:       ${total_fees:.2f}")
        print(f"  Net P&L:          ${total_net:+.2f}")
        print(f"  Max drawdown:     ${max_dd:.2f}")
        print(f"  Avg trade (net):  ${total_net/len(trades):+.3f}")

        print(f"\nPer-Category:")
        print(f"  {'Category':20s} {'Trades':>7} {'WR':>7} {'Net P&L':>10} {'Fees':>8}")
        print(f"  {'-'*55}")
        for cat in sorted(cat_results.keys()):
            cr = cat_results[cat]
            if cr["trades"] == 0:
                continue
            wr = cr["wins"] / cr["trades"]
            print(f"  {cat:20s} {cr['trades']:>7} {wr:>6.1%} "
                  f"${cr['net_pnl']:>+9.2f} ${cr['fees']:>7.2f}")

        # Show sample trades
        print(f"\nSample trades (first 10):")
        for t in trades[:10]:
            icon = "W" if t["won"] else "L"
            print(f"  [{icon}] {t['side']:>3} @{t['entry_price']:.2f} "
                  f"est={t['est_prob']:.2f} edge={t['edge']:.2f} "
                  f"pnl=${t['net_pnl']:+.2f} | {t['question']}")

    # ── Calibration ──
    if all_preds:
        bs_becker = brier_score(all_preds, all_outcomes)
        market_prices = [p for _, p in
                         sum([m["price_history"] for m in markets], [])
                         if 0.05 < p < 0.95]
        market_outcomes = []
        for m in markets:
            resolved_yes = 1.0 if m["resolved_to"] == "YES" else 0.0
            for ts, p in m["price_history"]:
                if 0.05 < p < 0.95:
                    market_outcomes.append(resolved_yes)
        bs_market = brier_score(market_prices, market_outcomes)

        print(f"\n{'='*60}")
        print(f"CALIBRATION ANALYSIS")
        print(f"{'='*60}")
        print(f"  Data points:         {len(all_preds)}")
        print(f"  Becker Brier score:  {bs_becker:.6f}")
        print(f"  Market Brier score:  {bs_market:.6f}")
        print(f"  Delta:               {bs_becker - bs_market:+.6f} "
              f"({'Becker worse' if bs_becker > bs_market else 'Becker better'})")

        print(f"\n  Reliability Diagram:")
        cal = calibration_table(all_preds, all_outcomes)
        print(f"  {'Bin':>12} {'Predicted':>10} {'Actual':>10} {'Gap':>8} {'Count':>7}")
        for row in cal:
            print(f"  {row['bin']:>12} {row['avg_predicted']:>10.3f} "
                  f"{row['actual_frequency']:>10.3f} {row['gap']:>+8.3f} "
                  f"{row['count']:>7}")


if __name__ == "__main__":
    edge = 0.10
    for arg in sys.argv[1:]:
        if arg.startswith("--edge="):
            edge = float(arg.split("=")[1])

    print("Becker Bot Backtester v2 (CLOB history)")
    print("=" * 60)
    run_backtest(min_edge=edge)
