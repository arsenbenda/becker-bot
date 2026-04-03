"""
Dynamic Calibrator — Proper Brier-based calibration that feeds back into the bot.
Runs every learning cycle. Builds correction curves from closed trades.
Replaces the naive mean-correction in self_learner.py.
"""
import json
import math
import numpy as np
from collections import defaultdict
from pathlib import Path

CALIBRATION_FILE = Path("/opt/becker-bot/calibration_state.json")
MIN_TRADES = 5


def load_calibration():
    if not CALIBRATION_FILE.exists():
        return {}
    try:
        with open(CALIBRATION_FILE) as f:
            return json.load(f)
    except:
        return {}


def save_calibration(state):
    with open(CALIBRATION_FILE, "w") as f:
        json.dump(state, f, indent=2)


def compute_calibration(closed_trades):
    """
    Compute calibration corrections from closed trades.
    Returns correction curves by category, layer, and price bucket.
    
    Only uses resolved trades (close_price > 0.90 or < 0.10) for
    accurate outcome data. Early exits contribute to win-rate stats
    but not probability calibration.
    """
    results = {
        "resolved_count": 0,
        "early_exit_count": 0,
        "overall": {},
        "by_category": {},
        "by_layer": {},
        "by_price_bucket": {},
        "brier_scores": {},
    }

    resolved = []
    early_exits = []

    for p in closed_trades:
        cp = float(p.get("close_price", 0.5))
        if cp > 0.90 or cp < 0.10:
            resolved.append(p)
        else:
            early_exits.append(p)

    results["resolved_count"] = len(resolved)
    results["early_exit_count"] = len(early_exits)

    if len(resolved) < MIN_TRADES:
        results["status"] = "insufficient_resolved_trades"
        return results

    # ── Build prediction/outcome arrays ──
    records = []
    for p in resolved:
        est_prob = float(p.get("estimated_prob", 0.5))
        side = p.get("side", "YES")
        cp = float(p.get("close_price", 0.5))
        entry = float(p.get("entry_price", 0.5))
        cat = p.get("category", "unknown")
        src = p.get("estimator_source", "unknown")

        yes_won = cp > 0.90

        if side == "YES":
            bot_conf = est_prob
            mkt_conf = entry
            won = yes_won
        else:
            bot_conf = 1.0 - est_prob
            mkt_conf = entry
            won = not yes_won

        records.append({
            "bot_conf": bot_conf, "mkt_conf": mkt_conf,
            "won": won, "side": side, "entry": entry,
            "cat": cat, "src": src,
            "price_bucket": _price_bucket(entry),
        })

    # ── Overall Brier ──
    preds = np.array([r["bot_conf"] for r in records])
    outs = np.array([1.0 if r["won"] else 0.0 for r in records])
    mkts = np.array([r["mkt_conf"] for r in records])

    results["brier_scores"]["bot"] = round(float(np.mean((preds - outs) ** 2)), 6)
    results["brier_scores"]["market"] = round(float(np.mean((mkts - outs) ** 2)), 6)
    results["brier_scores"]["delta"] = round(
        results["brier_scores"]["bot"] - results["brier_scores"]["market"], 6)

    # ── Correction curves ──
    # For each dimension (category, layer, price_bucket):
    # correction = actual_win_rate - average_bot_confidence
    # positive = bot underestimates (should increase)
    # negative = bot overestimates (should decrease)

    for dim, key in [("by_category", "cat"), ("by_layer", "src"),
                     ("by_price_bucket", "price_bucket")]:
        groups = defaultdict(lambda: {"confs": [], "outs": [], "mkt_confs": []})
        for r in records:
            g = r[key]
            groups[g]["confs"].append(r["bot_conf"])
            groups[g]["outs"].append(1.0 if r["won"] else 0.0)
            groups[g]["mkt_confs"].append(r["mkt_conf"])

        corrections = {}
        for g, data in groups.items():
            n = len(data["confs"])
            if n < MIN_TRADES:
                continue
            avg_conf = float(np.mean(data["confs"]))
            actual_wr = float(np.mean(data["outs"]))
            avg_mkt = float(np.mean(data["mkt_confs"]))
            bot_brier = float(np.mean(
                (np.array(data["confs"]) - np.array(data["outs"])) ** 2))
            mkt_brier = float(np.mean(
                (np.array(data["mkt_confs"]) - np.array(data["outs"])) ** 2))

            # Correction: how much to shift bot's confidence
            correction = actual_wr - avg_conf

            # Confidence in correction scales with sample size
            confidence = min(n / 30.0, 1.0)

            # Effective correction: weighted by confidence, capped at ±10pp
            effective = max(-0.10, min(0.10, correction * confidence))

            corrections[g] = {
                "correction_pp": round(correction, 4),
                "effective_correction": round(effective, 4),
                "confidence": round(confidence, 3),
                "sample_size": n,
                "avg_bot_conf": round(avg_conf, 4),
                "actual_win_rate": round(actual_wr, 4),
                "avg_market_conf": round(avg_mkt, 4),
                "bot_brier": round(bot_brier, 6),
                "mkt_brier": round(mkt_brier, 6),
                "bot_beats_market": bot_brier < mkt_brier,
            }

        results[dim] = corrections

    # ── Reliability diagram (for logging) ──
    bins = defaultdict(lambda: {"preds": [], "outs": []})
    for pred, out in zip(preds, outs):
        bucket = min(int(pred * 5), 4)
        bins[bucket]["preds"].append(float(pred))
        bins[bucket]["outs"].append(float(out))

    reliability = []
    for i in range(5):
        b = bins[i]
        if not b["preds"]:
            continue
        reliability.append({
            "bin": f"{i/5:.1f}-{(i+1)/5:.1f}",
            "avg_predicted": round(float(np.mean(b["preds"])), 3),
            "actual_frequency": round(float(np.mean(b["outs"])), 3),
            "count": len(b["preds"]),
        })
    results["reliability_diagram"] = reliability
    results["status"] = "active"

    return results


def apply_calibration_correction(bot_confidence, side, category, source,
                                  entry_price, cal_state):
    """
    Apply calibration corrections to a bot confidence estimate.
    Called during evaluate() to adjust probability before edge/EV checks.
    
    Returns adjusted confidence and explanation.
    """
    if not cal_state or cal_state.get("status") != "active":
        return bot_confidence, []

    adjustments = []
    adj = 0.0

    # Category correction (highest weight — category is most predictive)
    cat_corr = cal_state.get("by_category", {}).get(category, {})
    if cat_corr and cat_corr.get("sample_size", 0) >= MIN_TRADES:
        c = cat_corr["effective_correction"]
        adj += c * 0.5  # 50% weight to category
        adjustments.append(f"cat[{category}]={c:+.4f}")

    # Layer correction
    layer_corr = cal_state.get("by_layer", {}).get(source, {})
    if layer_corr and layer_corr.get("sample_size", 0) >= MIN_TRADES:
        c = layer_corr["effective_correction"]
        adj += c * 0.3  # 30% weight to layer
        adjustments.append(f"layer[{source[-4:]}]={c:+.4f}")

    # Price bucket correction
    bucket = _price_bucket(entry_price)
    bucket_corr = cal_state.get("by_price_bucket", {}).get(bucket, {})
    if bucket_corr and bucket_corr.get("sample_size", 0) >= MIN_TRADES:
        c = bucket_corr["effective_correction"]
        adj += c * 0.2  # 20% weight to price bucket
        adjustments.append(f"bucket[{bucket}]={c:+.4f}")

    # Clamp total adjustment
    adj = max(-0.08, min(0.08, adj))
    corrected = max(0.01, min(0.99, bot_confidence + adj))

    return corrected, adjustments


def _price_bucket(price):
    if price <= 0.20:
        return "0.00-0.20"
    elif price <= 0.40:
        return "0.20-0.40"
    elif price <= 0.60:
        return "0.40-0.60"
    elif price <= 0.80:
        return "0.60-0.80"
    else:
        return "0.80-1.00"


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "/opt/becker-bot")
    from shared_state import load_positions

    positions = load_positions()
    closed = [p for p in positions if p.get("status") == "closed"
              and p.get("close_reason") not in
              ("cluster_prune", "longshot_filter", "contradiction_filter")]

    print(f"Analyzing {len(closed)} closed trades...\n")
    cal = compute_calibration(closed)

    print(f"Status: {cal['status']}")
    print(f"Resolved: {cal['resolved_count']} | Early exits: {cal['early_exit_count']}")

    if cal.get("brier_scores"):
        bs = cal["brier_scores"]
        print(f"\nBrier: bot={bs['bot']:.4f} market={bs['market']:.4f} "
              f"delta={bs['delta']:+.4f}")

    for dim in ["by_category", "by_layer", "by_price_bucket"]:
        data = cal.get(dim, {})
        if not data:
            continue
        print(f"\n{dim}:")
        for key, vals in sorted(data.items()):
            beats = "+" if vals.get("bot_beats_market") else "-"
            print(f"  {key:25s} corr={vals['effective_correction']:+.4f} "
                  f"n={vals['sample_size']:>3} WR={vals['actual_win_rate']:.1%} "
                  f"conf={vals['confidence']:.2f} [{beats}mkt]")

    if cal.get("reliability_diagram"):
        print(f"\nReliability:")
        for row in cal["reliability_diagram"]:
            gap = row["actual_frequency"] - row["avg_predicted"]
            print(f"  {row['bin']:>10} pred={row['avg_predicted']:.3f} "
                  f"actual={row['actual_frequency']:.3f} gap={gap:+.3f} n={row['count']}")

    save_calibration(cal)
    print(f"\nCalibration saved to {CALIBRATION_FILE}")
