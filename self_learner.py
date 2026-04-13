"""
Self-Learner v1 — Calibration, adaptive risk, market memory.
Level 1: Learn from trade outcomes (calibration curves)
Level 2: Adaptive parameter tuning (dynamic risk)
Level 3: Market memory (avoid re-entry at worse prices)
"""
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

from shared_state import (
    load_trades, load_positions, load_config, save_config,
    STATE_FILE, LOG_FILE, BASE_DIR
)

LEARNER_FILE = BASE_DIR / "learner_state.json"
MIN_TRADES_FOR_CALIBRATION = 5
ROLLING_WINDOW = 50  # trades for adaptive risk


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [learner] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ════════════════════════════════════════════════════════
#  PERSISTENT STATE
# ════════════════════════════════════════════════════════

def load_learner_state() -> dict:
    if not LEARNER_FILE.exists():
        return {
            "calibration": {},
            "category_corrections": {},
            "layer_corrections": {},
            "price_bucket_corrections": {},
            "adaptive_risk": {},
            "market_memory": {},
            "trade_outcomes": [],
            "last_update": "",
        }
    try:
        with open(LEARNER_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, KeyError):
        return load_learner_state.__wrapped__() if hasattr(load_learner_state, '__wrapped__') else {
            "calibration": {}, "category_corrections": {},
            "layer_corrections": {}, "price_bucket_corrections": {},
            "adaptive_risk": {}, "market_memory": {},
            "trade_outcomes": [], "last_update": "",
        }


def save_learner_state(state: dict):
    state["last_update"] = datetime.now(timezone.utc).isoformat()
    with open(LEARNER_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


# ════════════════════════════════════════════════════════
#  LEVEL 1: CALIBRATION — learn from outcomes
# ════════════════════════════════════════════════════════

def price_bucket(price: float) -> str:
    """Bucket prices into ranges for calibration."""
    if price <= 0.10:
        return "0.01-0.10"
    elif price <= 0.20:
        return "0.11-0.20"
    elif price <= 0.30:
        return "0.21-0.30"
    elif price <= 0.40:
        return "0.31-0.40"
    elif price <= 0.60:
        return "0.41-0.60"
    elif price <= 0.70:
        return "0.61-0.70"
    elif price <= 0.80:
        return "0.71-0.80"
    elif price <= 0.90:
        return "0.81-0.90"
    else:
        return "0.91-0.99"


def update_calibration(state: dict, positions: list) -> dict:
    """
    Analyze closed trades to build calibration curves.
    Compares estimated probability vs actual win/loss.
    """
    closed = [p for p in positions if p.get("status") == "closed" and p.get("close_reason") not in ("cluster_prune", "longshot_filter", "contradiction_filter", "deviation_cap_bug")]

    if len(closed) < MIN_TRADES_FOR_CALIBRATION:
        return state

    # ── Per-category calibration ───────────────────────
    cat_stats = {}
    for p in closed:
        cat = p.get("category", "default")
        if cat not in cat_stats:
            cat_stats[cat] = {"predictions": [], "outcomes": [], "count": 0}

        est = p.get("estimated_prob", 0.5)
        # P7: Convert to side-confidence (NO trades: confidence = 1 - est_prob)
        side_conf = est if p.get("side", "YES") == "YES" else 1.0 - est
        won = 1 if p.get("pnl", 0) > 0 else 0
        cat_stats[cat]["predictions"].append(side_conf)
        cat_stats[cat]["outcomes"].append(won)
        cat_stats[cat]["count"] += 1

    cat_corrections = {}
    for cat, stats in cat_stats.items():
        if stats["count"] >= MIN_TRADES_FOR_CALIBRATION:
            avg_prediction = sum(stats["predictions"]) / len(stats["predictions"])
            actual_win_rate = sum(stats["outcomes"]) / len(stats["outcomes"])
            # Positive = we underestimate (should bet more)
            # Negative = we overestimate (should bet less)
            correction = round(actual_win_rate - avg_prediction, 4)
            cat_corrections[cat] = {
                "correction_pp": correction,
                "avg_prediction": round(avg_prediction, 4),
                "actual_win_rate": round(actual_win_rate, 4),
                "sample_size": stats["count"],
                "confidence": min(stats["count"] / 30, 1.0),
            }
            log(f"Calibration [{cat}]: predicted {avg_prediction:.3f}, "
                f"actual {actual_win_rate:.3f}, correction {correction:+.4f} "
                f"(n={stats['count']})")

    state["category_corrections"] = cat_corrections

    # ── Per-layer calibration ──────────────────────────
    layer_stats = {}
    for p in closed:
        src = p.get("estimator_source", "unknown")
        if src not in layer_stats:
            layer_stats[src] = {"predictions": [], "outcomes": [], "count": 0}
        est = p.get("estimated_prob", 0.5)
        # P7: Convert to side-confidence (NO trades: confidence = 1 - est_prob)
        side_conf = est if p.get("side", "YES") == "YES" else 1.0 - est
        won = 1 if p.get("pnl", 0) > 0 else 0
        layer_stats[src]["predictions"].append(side_conf)
        layer_stats[src]["outcomes"].append(won)
        layer_stats[src]["count"] += 1

    layer_corrections = {}
    for src, stats in layer_stats.items():
        if stats["count"] >= MIN_TRADES_FOR_CALIBRATION:
            avg_pred = sum(stats["predictions"]) / len(stats["predictions"])
            actual = sum(stats["outcomes"]) / len(stats["outcomes"])
            correction = round(actual - avg_pred, 4)
            layer_corrections[src] = {
                "correction_pp": correction,
                "avg_prediction": round(avg_pred, 4),
                "actual_win_rate": round(actual, 4),
                "sample_size": stats["count"],
            }
            log(f"Calibration [{src}]: correction {correction:+.4f} (n={stats['count']})")

    state["layer_corrections"] = layer_corrections

    # ── Per-price-bucket calibration ───────────────────
    bucket_stats = {}
    for p in closed:
        price = p.get("entry_price", 0.5)
        bucket = price_bucket(price)
        if bucket not in bucket_stats:
            bucket_stats[bucket] = {"predictions": [], "outcomes": [], "count": 0}
        est = p.get("estimated_prob", 0.5)
        # P7: Convert to side-confidence (NO trades: confidence = 1 - est_prob)
        side_conf = est if p.get("side", "YES") == "YES" else 1.0 - est
        won = 1 if p.get("pnl", 0) > 0 else 0
        bucket_stats[bucket]["predictions"].append(side_conf)
        bucket_stats[bucket]["outcomes"].append(won)
        bucket_stats[bucket]["count"] += 1

    bucket_corrections = {}
    for bucket, stats in bucket_stats.items():
        if stats["count"] >= MIN_TRADES_FOR_CALIBRATION:
            avg_pred = sum(stats["predictions"]) / len(stats["predictions"])
            actual = sum(stats["outcomes"]) / len(stats["outcomes"])
            correction = round(actual - avg_pred, 4)
            bucket_corrections[bucket] = {
                "correction_pp": correction,
                "sample_size": stats["count"],
            }

    state["price_bucket_corrections"] = bucket_corrections

    return state


# ════════════════════════════════════════════════════════
#  LEVEL 2: ADAPTIVE RISK — dynamic parameter tuning
# ════════════════════════════════════════════════════════

def update_adaptive_risk(state: dict, positions: list) -> dict:
    """
    Adjust risk parameters based on recent performance.
    Uses rolling window of last N closed trades.
    """
    closed = [p for p in positions if p.get("status") == "closed" and p.get("close_reason") not in ("cluster_prune", "longshot_filter", "contradiction_filter", "deviation_cap_bug")]

    if len(closed) < MIN_TRADES_FOR_CALIBRATION:
        state["adaptive_risk"] = {
            "status": "insufficient_data",
            "closed_count": len(closed),
            "required": MIN_TRADES_FOR_CALIBRATION,
        }
        return state

    # Use last ROLLING_WINDOW trades
    recent = closed[-ROLLING_WINDOW:]

    wins = sum(1 for p in recent if p.get("pnl", 0) > 0)
    losses = len(recent) - wins
    win_rate = wins / len(recent)
    total_pnl = sum(p.get("pnl", 0) for p in recent)
    avg_pnl = total_pnl / len(recent)

    # Profit factor
    gross_profit = sum(p.get("pnl", 0) for p in recent if p.get("pnl", 0) > 0)
    gross_loss = abs(sum(p.get("pnl", 0) for p in recent if p.get("pnl", 0) < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 999

    # Max drawdown in the window
    running_pnl = 0
    peak = 0
    max_dd = 0
    for p in recent:
        running_pnl += p.get("pnl", 0)
        peak = max(peak, running_pnl)
        dd = peak - running_pnl
        max_dd = max(max_dd, dd)

    # ── Compute recommended adjustments ────────────────
    cfg = load_config()
    current_kelly = cfg.get("KELLY_FRACTION", 0.25)
    current_max_bet = cfg.get("MAX_BET_PCT", 0.05)
    current_min_edge = cfg.get("MIN_EDGE_POINTS", 0.02)

    # Kelly adjustment — absolute tiers (not relative to current)
    if win_rate >= 0.70 and profit_factor > 2.0:
        recommended_kelly = 0.25
        kelly_reason = f"Strong performance: {win_rate:.0%} win, PF {profit_factor:.1f}"
    elif win_rate >= 0.55 and profit_factor > 1.3:
        recommended_kelly = 0.15
        kelly_reason = f"Solid performance: {win_rate:.0%} win, PF {profit_factor:.1f}"
    elif win_rate >= 0.40:
        recommended_kelly = 0.10
        kelly_reason = f"Below target: {win_rate:.0%} win, reducing size"
    else:
        recommended_kelly = 0.05
        kelly_reason = f"Poor performance: {win_rate:.0%} win, halving size"

    # Edge threshold adjustment
    if win_rate < 0.45 and total_pnl < 0:
        recommended_edge = min(current_min_edge * 1.5, 0.10)
        edge_reason = "Raising edge bar — too many losing trades"
    elif win_rate > 0.65 and profit_factor > 1.5:
        recommended_edge = max(current_min_edge * 0.8, 0.01)
        edge_reason = "Lowering edge bar — winning consistently"
    else:
        recommended_edge = current_min_edge
        edge_reason = "Edge threshold appropriate"

    # Max bet adjustment based on drawdown
    if max_dd > cfg.get("PAPER_BANKROLL", 500) * 0.15:
        recommended_max_bet = max(current_max_bet * 0.7, 0.01)
        bet_reason = f"Drawdown ${max_dd:.2f} > 15% bankroll, reducing max bet"
    else:
        recommended_max_bet = current_max_bet
        bet_reason = "Drawdown acceptable"

    # ── Category performance ───────────────────────────
    cat_performance = {}
    for p in recent:
        cat = p.get("category", "default")
        if cat not in cat_performance:
            cat_performance[cat] = {"wins": 0, "losses": 0, "pnl": 0}
        if p.get("pnl", 0) > 0:
            cat_performance[cat]["wins"] += 1
        else:
            cat_performance[cat]["losses"] += 1
        cat_performance[cat]["pnl"] += p.get("pnl", 0)

    # Flag underperforming categories
    avoid_categories = []
    for cat, perf in cat_performance.items():
        total = perf["wins"] + perf["losses"]
        if total >= 20 and perf["wins"] / total < 0.40:
            avoid_categories.append(cat)
            log(f"AUTO-BLOCK: '{cat}' — win rate "
                f"{perf['wins']/total:.0%} over {total} trades (<40% over 20+)")

    # P13c: Also check full closed history for categories not yet flagged
    all_closed = [p for p in positions if p.get("status") == "closed"
                  and p.get("close_reason") not in
                  ("cluster_prune", "longshot_filter", "contradiction_filter", "deviation_cap_bug")]
    full_cat_perf = {}
    for p in all_closed:
        cat = p.get("category", "default")
        if cat not in full_cat_perf:
            full_cat_perf[cat] = {"wins": 0, "losses": 0}
        if p.get("pnl", 0) > 0:
            full_cat_perf[cat]["wins"] += 1
        else:
            full_cat_perf[cat]["losses"] += 1

    for cat, perf in full_cat_perf.items():
        if cat in avoid_categories:
            continue
        total = perf["wins"] + perf["losses"]
        if total >= 20 and perf["wins"] / total < 0.40:
            avoid_categories.append(cat)
            wr = perf["wins"] / total
            log(f"AUTO-BLOCK (full history): '{cat}' — win rate "
                f"{wr:.0%} over {total} trades (<40% over 20+)")

    state["adaptive_risk"] = {
        "status": "active",
        "window_size": len(recent),
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 2),
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(avg_pnl, 4),
        "max_drawdown": round(max_dd, 2),
        "wins": wins,
        "losses": losses,
        "recommended_kelly": round(recommended_kelly, 4),
        "kelly_reason": kelly_reason,
        "recommended_edge": round(recommended_edge, 4),
        "edge_reason": edge_reason,
        "recommended_max_bet": round(recommended_max_bet, 4),
        "bet_reason": bet_reason,
        "avoid_categories": avoid_categories,
        "category_performance": cat_performance,
    }

    log(f"Adaptive risk: WR {win_rate:.0%}, PF {profit_factor:.1f}, "
        f"PnL ${total_pnl:+.2f}, DD ${max_dd:.2f}")
    log(f"  Kelly: {current_kelly:.2f} → {recommended_kelly:.2f} ({kelly_reason})")
    if avoid_categories:
        log(f"  Avoid: {avoid_categories}")

    return state


# ════════════════════════════════════════════════════════
#  LEVEL 3: MARKET MEMORY — track seen markets
# ════════════════════════════════════════════════════════

def update_market_memory(state: dict, positions: list) -> dict:
    """
    Remember markets we've traded and their outcomes.
    Prevents re-entry at worse prices, tracks resolution patterns.
    """
    memory = state.get("market_memory", {})

    for p in positions:
        mid = p.get("market_id", "")
        if not mid:
            continue

        if mid not in memory:
            memory[mid] = {
                "question": p.get("question", ""),
                "category": p.get("category", ""),
                "first_seen": p.get("opened_at", ""),
                "entries": [],
                "resolved": False,
                "resolution_pnl": 0,
            }

        # Record each entry
        entry = {
            "side": p.get("side", ""),
            "entry_price": p.get("entry_price", 0),
            "estimated_prob": p.get("estimated_prob", 0),
            "cost": p.get("cost", 0),
            "source": p.get("estimator_source", ""),
            "timestamp": p.get("opened_at", ""),
            "status": p.get("status", "open"),
        }

        if p.get("status") == "closed":
            entry["exit_price"] = p.get("close_price", 0)
            entry["pnl"] = p.get("pnl", 0)
            entry["closed_at"] = p.get("closed_at", "")
            memory[mid]["resolved"] = True
            memory[mid]["resolution_pnl"] += p.get("pnl", 0)

        # Avoid duplicate entries
        existing_timestamps = [e.get("timestamp") for e in memory[mid]["entries"]]
        if entry["timestamp"] not in existing_timestamps:
            memory[mid]["entries"].append(entry)

    state["market_memory"] = memory
    return state


def should_trade_market(state: dict, market_id: str, current_price: float,
                        side: str) -> dict:
    """
    Check market memory before entering a trade.
    Returns: {"allowed": bool, "reason": str, "history": dict}
    """
    memory = state.get("market_memory", {})

    if market_id not in memory:
        return {"allowed": True, "reason": "new_market", "history": None}

    record = memory[market_id]
    entries = record.get("entries", [])

    if not entries:
        return {"allowed": True, "reason": "no_previous_entries", "history": record}

    # Check if we already lost on this market
    closed_entries = [e for e in entries if e.get("status") == "closed"]
    if closed_entries:
        total_pnl = sum(e.get("pnl", 0) for e in closed_entries)
        if total_pnl < 0 and len(closed_entries) >= 2:
            return {
                "allowed": False,
                "reason": f"lost ${abs(total_pnl):.2f} over {len(closed_entries)} entries — avoiding",
                "history": record,
            }

    # Check if re-entering at worse price
    last_entry = entries[-1]
    last_price = last_entry.get("entry_price", 0)

    if side == last_entry.get("side", ""):
        if side == "YES" and current_price > last_price * 1.05:
            return {
                "allowed": False,
                "reason": f"price {current_price:.3f} > previous {last_price:.3f} — worse entry",
                "history": record,
            }
        elif side == "NO" and current_price > last_price * 1.05:
            return {
                "allowed": False,
                "reason": f"price {current_price:.3f} > previous {last_price:.3f} — worse entry",
                "history": record,
            }

    return {"allowed": True, "reason": "memory_check_passed", "history": record}


def should_avoid_category(state: dict, category: str) -> bool:
    """Check if adaptive risk has flagged this category."""
    adaptive = state.get("adaptive_risk", {})
    avoid = adaptive.get("avoid_categories", [])
    return category in avoid


# ════════════════════════════════════════════════════════
#  APPLY CORRECTIONS TO PROBABILITY ESTIMATE
# ════════════════════════════════════════════════════════

def apply_learned_corrections(
    raw_probability: float,
    category: str,
    source_layer: str,
    entry_price: float,
    state: dict,
) -> dict:
    """
    Apply all learned corrections to a raw probability estimate.
    Returns adjusted probability and explanation.
    """
    adjustments = []
    prob = raw_probability

    # ── Category correction ────────────────────────────
    cat_corr = state.get("category_corrections", {}).get(category, {})
    if cat_corr and cat_corr.get("sample_size", 0) >= MIN_TRADES_FOR_CALIBRATION:
        correction = cat_corr["correction_pp"]
        confidence = cat_corr.get("confidence", 0.5)
        # Apply correction weighted by confidence
        adj = correction * confidence
        prob += adj
        adjustments.append(
            f"cat[{category}] {adj:+.4f} (corr={correction:+.4f}, "
            f"conf={confidence:.2f}, n={cat_corr['sample_size']})"
        )

    # ── Layer correction ───────────────────────────────
    layer_corr = state.get("layer_corrections", {}).get(source_layer, {})
    if layer_corr and layer_corr.get("sample_size", 0) >= MIN_TRADES_FOR_CALIBRATION:
        correction = layer_corr["correction_pp"]
        adj = correction * 0.5  # conservative: apply half
        prob += adj
        adjustments.append(
            f"layer[{source_layer[-2:]}] {adj:+.4f} (n={layer_corr['sample_size']})"
        )

    # ── Price bucket correction ────────────────────────
    bucket = price_bucket(entry_price)
    bucket_corr = state.get("price_bucket_corrections", {}).get(bucket, {})
    if bucket_corr and bucket_corr.get("sample_size", 0) >= MIN_TRADES_FOR_CALIBRATION:
        correction = bucket_corr["correction_pp"]
        adj = correction * 0.3  # very conservative for price buckets
        prob += adj
        adjustments.append(f"bucket[{bucket}] {adj:+.4f}")

    # Clamp
    prob = max(0.01, min(0.99, prob))

    return {
        "adjusted_probability": round(prob, 4),
        "raw_probability": raw_probability,
        "total_adjustment": round(prob - raw_probability, 4),
        "adjustments": adjustments,
        "corrections_applied": len(adjustments),
    }


# ════════════════════════════════════════════════════════
#  MASTER UPDATE — called by bot after each scan
# ════════════════════════════════════════════════════════

def run_learning_cycle(positions: list) -> dict:
    """
    Run all learning modules. Called by the bot after each scan.
    Returns the updated learner state.
    """
    state = load_learner_state()
    closed_count = len([p for p in positions if p.get("status") == "closed"])

    log(f"Learning cycle: {len(positions)} positions, {closed_count} closed")

    # Level 1: Calibration
    state = update_calibration(state, positions)

    # Level 2: Adaptive risk
    state = update_adaptive_risk(state, positions)

    # Level 3: Market memory
    state = update_market_memory(state, positions)

    # Summary
    cat_corrections = state.get("category_corrections", {})
    adaptive = state.get("adaptive_risk", {})
    memory_count = len(state.get("market_memory", {}))

    state["summary"] = {
        "calibrated_categories": len(cat_corrections),
        "adaptive_status": adaptive.get("status", "inactive"),
        "markets_remembered": memory_count,
        "avoid_categories": adaptive.get("avoid_categories", []),
        "last_cycle": datetime.now(timezone.utc).isoformat(),
    }

    save_learner_state(state)
    log(f"Learning saved: {len(cat_corrections)} cat corrections, "
        f"{memory_count} markets remembered")

    return state


# ════════════════════════════════════════════════════════
#  SELF-TEST
# ════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n=== Self-Learner Self-Test ===\n")

    state = load_learner_state()
    print(f"Learner state: {len(state.get('market_memory', {}))} markets remembered")
    print(f"Category corrections: {state.get('category_corrections', {})}")
    print(f"Adaptive risk: {state.get('adaptive_risk', {})}")

    # Test correction application
    result = apply_learned_corrections(
        raw_probability=0.85,
        category="sports",
        source_layer="layer2_quantitative",
        entry_price=0.90,
        state=state,
    )
    print(f"\nCorrection test: 0.85 → {result['adjusted_probability']}")
    print(f"Adjustments: {result['adjustments']}")

    # Run learning cycle on current positions
    positions = load_positions()
    if positions:
        state = run_learning_cycle(positions)
        print(f"\nLearning cycle complete:")
        print(f"  Summary: {json.dumps(state.get('summary', {}), indent=2)}")
    else:
        print("\nNo positions to learn from yet")

    print("\nDone.")
