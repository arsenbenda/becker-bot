from api_caps import within_daily_cap, record_call
"""
Smart Estimator v4 — 3-layer probability engine
Layer 1: Perplexity Sonar + GPT-4o mini (best, costs money)
Layer 2: CLOB orderbook + price momentum + volume (free)
Layer 3: Becker statistical bias model (free, always runs)
"""
import time
import json
import math
import re
import requests
import numpy as np
from datetime import datetime

from shared_state import (
    get_api_key, get_cached_estimate, set_cached_estimate,
    CATEGORY_EDGE, CLOB_API, LOG_FILE
)

# suppress import if not needed
CLOB_API_URL = "https://clob.polymarket.com"
GAMMA_API_URL = "https://gamma-api.polymarket.com"


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [estimator] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ════════════════════════════════════════════════════════
#  LAYER 3: Becker Statistical Model (always available)
# ════════════════════════════════════════════════════════

def becker_bias_adjustment(market_price: float, category: str) -> float:
    """
    Adjust implied probability using Becker's long-shot bias curve.
    Low-price contracts are overpriced (optimism tax).
    High-price contracts are slightly underpriced.
    Returns adjusted probability estimate.
    """
    p = market_price
    if p <= 0.01 or p >= 0.99:
        return p

    # Becker's calibration: actual win rate vs implied odds
    # 1c contracts win 0.43% (implied 1%) → ratio 0.43
    # 5c contracts win 4.18% (implied 5%) → ratio 0.836
    # 10c contracts win ~8.5% (implied 10%) → ratio 0.85
    # 50c contracts win ~50% → ratio 1.0
    # 95c contracts win 95.83% (implied 95%) → ratio 1.009
    if p < 0.50:
        # Long-shot: actual prob is LOWER than price implies
        # Interpolate bias factor
        if p <= 0.01:
            bias = 0.43
        elif p <= 0.05:
            bias = 0.43 + (p - 0.01) / (0.05 - 0.01) * (0.836 - 0.43)
        elif p <= 0.10:
            bias = 0.836 + (p - 0.05) / (0.10 - 0.05) * (0.85 - 0.836)
        elif p <= 0.50:
            bias = 0.85 + (p - 0.10) / (0.50 - 0.10) * (1.0 - 0.85)
        else:
            bias = 1.0
        adjusted = p * bias
    else:
        # Favorite: actual prob is slightly HIGHER than price implies
        if p <= 0.90:
            bias = 1.0 + (p - 0.50) / (0.90 - 0.50) * (1.005 - 1.0)
        elif p <= 0.95:
            bias = 1.005 + (p - 0.90) / (0.95 - 0.90) * (1.009 - 1.005)
        else:
            bias = 1.009 + (p - 0.95) / (0.99 - 0.95) * (1.012 - 1.009)
        adjusted = min(p * bias, 0.99)

    return round(adjusted, 4)


def layer3_estimate(market_price: float, category: str) -> dict:
    """Pure Becker statistical model."""
    est_prob = becker_bias_adjustment(market_price, category)
    cat_edge = CATEGORY_EDGE.get(category, CATEGORY_EDGE["default"])

    return {
        "probability": est_prob,
        "confidence": 0.3,  # low confidence — no real-world info
        "source": "layer3_becker",
        "reasoning": f"Becker bias: price {market_price:.2f} → est prob {est_prob:.4f}, "
                     f"category '{category}' edge {cat_edge:.2f}pp",
    }


# ════════════════════════════════════════════════════════
#  LAYER 2: Free Quantitative Signals
# ════════════════════════════════════════════════════════

def fetch_orderbook(token_id: str) -> dict | None:
    """Fetch CLOB order book for a token."""
    try:
        r = requests.get(f"{CLOB_API_URL}/book", params={"token_id": token_id}, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log(f"Orderbook fetch failed for {token_id}: {e}")
    return None


def orderbook_imbalance(book: dict) -> float:
    """
    Calculate buy/sell imbalance from order book.
    Returns value between -1.0 (all sell pressure) and +1.0 (all buy pressure).
    """
    if not book:
        return 0.0

    bids = book.get("bids", [])
    asks = book.get("asks", [])

    bid_volume = sum(float(b.get("size", 0)) for b in bids[:10])
    ask_volume = sum(float(a.get("size", 0)) for a in asks[:10])

    total = bid_volume + ask_volume
    if total == 0:
        return 0.0

    return round((bid_volume - ask_volume) / total, 4)


def fetch_price_history(token_id: str, interval: str = "1d", fidelity: int = 60) -> list:
    """Fetch price history from CLOB API."""
    try:
        r = requests.get(
            f"{CLOB_API_URL}/prices-history",
            params={"market": token_id, "interval": interval, "fidelity": fidelity},
            timeout=10
        )
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict) and "history" in data:
                return data["history"]
            elif isinstance(data, list):
                return data
    except Exception as e:
        log(f"Price history fetch failed for {token_id}: {e}")
    return []


def price_momentum(history: list) -> dict:
    """
    Analyze price momentum from history.
    Returns momentum signal and statistics.
    """
    if len(history) < 3:
        return {"signal": 0.0, "trend": "insufficient_data", "volatility": 0.0}

    prices = []
    for h in history:
        p = h.get("p", h.get("price", None))
        if p is not None:
            prices.append(float(p))

    if len(prices) < 3:
        return {"signal": 0.0, "trend": "insufficient_data", "volatility": 0.0}

    prices = np.array(prices[-20:])  # last 20 points

    # Short-term momentum (last 3 vs previous 3)
    if len(prices) >= 6:
        recent = np.mean(prices[-3:])
        earlier = np.mean(prices[-6:-3])
        momentum = (recent - earlier) / max(earlier, 0.01)
    else:
        momentum = (prices[-1] - prices[0]) / max(prices[0], 0.01)

    # Volatility (std of returns)
    if len(prices) >= 2:
        returns = np.diff(prices) / np.maximum(prices[:-1], 0.001)
        vol = float(np.std(returns))
    else:
        vol = 0.0

    # Trend classification
    if momentum > 0.02:
        trend = "up"
    elif momentum < -0.02:
        trend = "down"
    else:
        trend = "flat"

    return {
        "signal": round(float(momentum), 4),
        "trend": trend,
        "volatility": round(vol, 4),
        "last_price": round(float(prices[-1]), 4),
        "points": len(prices),
    }


def momentum_zscores(history: list) -> dict:
    """
    Phase 1.1: Compute z-scores across 7/14/30-day windows.
    Z-score = (current_price - window_mean) / window_std
    Positive z = price above average (trending up)
    Negative z = price below average (trending down)
    |z| > 2 = extreme move, potential mean-reversion
    """
    prices = []
    for h in history:
        p = h.get("p", h.get("price", None))
        if p is not None:
            prices.append(float(p))

    if len(prices) < 7:
        return {"available": False, "reason": "insufficient_data"}

    arr = np.array(prices)
    current = arr[-1]

    windows = {"7d": 7, "14d": 14, "30d": 30}
    zscores = {}
    signals = {}

    for label, w in windows.items():
        if len(arr) < w:
            continue
        window = arr[-w:]
        mean = float(np.mean(window))
        std = float(np.std(window, ddof=1)) if len(window) > 1 else 0.001
        std = max(std, 0.001)  # prevent division by zero
        z = (current - mean) / std
        zscores[label] = round(float(z), 3)

        # Classify signal
        if z > 2.0:
            signals[label] = "overbought"
        elif z > 1.0:
            signals[label] = "bullish"
        elif z < -2.0:
            signals[label] = "oversold"
        elif z < -1.0:
            signals[label] = "bearish"
        else:
            signals[label] = "neutral"

    if not zscores:
        return {"available": False, "reason": "no_valid_windows"}

    # Composite signal: weighted average (shorter = more weight)
    weights = {"7d": 0.5, "14d": 0.3, "30d": 0.2}
    weighted_z = 0.0
    total_weight = 0.0
    for label, z in zscores.items():
        w = weights.get(label, 0.2)
        weighted_z += z * w
        total_weight += w
    composite = weighted_z / total_weight if total_weight > 0 else 0.0

    # Trend alignment: all windows agree = strong signal
    z_vals = list(zscores.values())
    all_positive = all(z > 0 for z in z_vals)
    all_negative = all(z < 0 for z in z_vals)
    aligned = all_positive or all_negative

    # Mean-reversion flag: short-term extreme vs long-term calm
    mean_reversion = False
    if "7d" in zscores and "30d" in zscores:
        if abs(zscores["7d"]) > 2.0 and abs(zscores["30d"]) < 1.0:
            mean_reversion = True

    return {
        "available": True,
        "zscores": zscores,
        "signals": signals,
        "composite_z": round(composite, 3),
        "aligned": aligned,
        "mean_reversion": mean_reversion,
        "current_price": round(current, 4),
        "points": len(prices),
    }


def volume_signal(history: list) -> float:
    """
    Detect unusual volume from price history timestamps.
    Returns a multiplier: >1.5 = unusual activity.
    """
    if len(history) < 10:
        return 1.0

    timestamps = []
    for h in history:
        t = h.get("t", h.get("timestamp", None))
        if t is not None:
            timestamps.append(float(t))

    if len(timestamps) < 10:
        return 1.0

    timestamps = sorted(timestamps)
    intervals = np.diff(timestamps[-20:])

    if len(intervals) < 2:
        return 1.0

    mean_interval = np.mean(intervals)
    recent_interval = np.mean(intervals[-3:]) if len(intervals) >= 3 else intervals[-1]

    if recent_interval <= 0:
        return 1.0

    # Shorter intervals = more activity
    ratio = mean_interval / recent_interval
    return round(float(min(ratio, 5.0)), 2)


def layer2_estimate(
    market_price: float,
    category: str,
    yes_token_id: str = "",
    no_token_id: str = "",
) -> dict:
    """
    Free quantitative signals: orderbook imbalance + momentum + volume.
    Adjusts the Becker baseline with market microstructure data.
    """
    base = becker_bias_adjustment(market_price, category)
    adjustments = []
    confidence = 0.4  # slightly better than pure Becker

    # ── Order book imbalance ───────────────────────────
    imbalance = 0.0
    if yes_token_id:
        book = fetch_orderbook(yes_token_id)
        if book:
            imbalance = orderbook_imbalance(book)
            # Strong buy imbalance → probability may be higher than price
            # Strong sell imbalance → probability may be lower
            adjustment = imbalance * 0.03  # max ±3pp shift
            base += adjustment
            adjustments.append(f"orderbook_imbalance={imbalance:+.3f} → {adjustment:+.4f}")
            confidence += 0.05

    # ── Price momentum + z-scores (Phase 1.1) ─────────
    if yes_token_id:
        history = fetch_price_history(yes_token_id)

        # Phase 1.1: Multi-timeframe z-scores
        zs = momentum_zscores(history)
        if zs.get("available"):
            composite = zs["composite_z"]

            # Z-score probability adjustment:
            # Aligned trend = follow momentum (max +/-3pp)
            # Mean-reversion signal = counter-momentum (max +/-2pp)
            if zs["mean_reversion"]:
                # Price spiked short-term but stable long-term → fade it
                z_adj = -composite * 0.015  # counter-trend, conservative
                adjustments.append(
                    f"zscore_reversion z={composite:+.3f} {zs['zscores']} → {z_adj:+.4f}"
                )
            elif zs["aligned"]:
                # All timeframes agree → strong trend, follow it
                z_adj = composite * 0.02  # max ~4pp for extreme z
                adjustments.append(
                    f"zscore_aligned z={composite:+.3f} {zs['zscores']} → {z_adj:+.4f}"
                )
            else:
                # Mixed signals → mild adjustment
                z_adj = composite * 0.01
                adjustments.append(
                    f"zscore_mixed z={composite:+.3f} {zs['zscores']} → {z_adj:+.4f}"
                )

            z_adj = max(-0.04, min(0.04, z_adj))  # hard cap +/-4pp
            base += z_adj
            confidence += 0.10 if zs["aligned"] else 0.05

        # Legacy momentum (fallback if z-scores unavailable)
        elif history:
            mom = price_momentum(history)
            if mom["trend"] != "insufficient_data":
                mom_adj = mom["signal"] * 0.02
                base += mom_adj
                adjustments.append(
                    f"momentum={mom['signal']:+.4f} ({mom['trend']}) → {mom_adj:+.4f}"
                )
                confidence += 0.05

        # ── Volume signal (applies to both paths) ─────
        if history:
            vol_mult = volume_signal(history)
            if vol_mult > 1.5:
                last_adj = float(adjustments[-1].split("→")[-1]) if adjustments else 0.0
                extra = last_adj * (vol_mult - 1.0) * 0.5
                base += extra
                adjustments.append(f"volume_spike={vol_mult:.1f}x → {extra:+.4f}")
                confidence += 0.05

    # Clamp probability
    base = max(0.01, min(0.99, base))

    return {
        "probability": round(base, 4),
        "confidence": round(min(confidence, 0.7), 2),
        "source": "layer2_quantitative",
        "reasoning": f"Becker base + quant signals: {'; '.join(adjustments) if adjustments else 'no signals available'}",
    }


# ════════════════════════════════════════════════════════
#  LAYER 1: Perplexity Sonar + GPT-4o mini
# ════════════════════════════════════════════════════════

def call_perplexity(question: str, context: str = "") -> str | None:
    """Call Perplexity Sonar API for web-grounded research."""
    api_key = get_api_key("PERPLEXITY_API_KEY")
    if not api_key:
        return None

    prompt = (
        f"Research this prediction market question and provide factual analysis "
        f"of how likely it is to resolve YES. Include recent news, data, and "
        f"expert opinions. Be specific with numbers and dates.\n\n"
        f"Market question: {question}\n"
    )
    if context:
        prompt += f"Additional context: {context}\n"

    try:
        r = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "sonar",
                "messages": [
                    {"role": "system", "content": "You are a prediction market analyst. Provide factual, data-driven analysis."},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 500,
                "temperature": 0.1,
            },
            timeout=30,
        )
        if r.status_code == 200:
            data = r.json()
            return data["choices"][0]["message"]["content"]
        elif r.status_code in (401, 403):
            log(f"Perplexity auth failed (HTTP {r.status_code}) — falling back")
            return None
        elif r.status_code == 429:
            log("Perplexity rate limited — falling back")
            return None
        else:
            log(f"Perplexity error HTTP {r.status_code}: {r.text[:200]}")
            return None
    except requests.exceptions.Timeout:
        log("Perplexity timeout — falling back")
        return None
    except Exception as e:
        log(f"Perplexity exception: {e}")
        return None


def extract_probability_gpt(question: str, research: str, market_price: float) -> dict | None:
    """Use GPT-4o mini to extract a probability from Perplexity research."""
    api_key = get_api_key("OPENAI_API_KEY")
    if not api_key:
        return None

    prompt = (
        f"You are a calibrated probability estimator for prediction markets.\n\n"
        f"Market question: {question}\n"
        f"Current market price (implied probability): {market_price:.2f}\n\n"
        f"Research from web search:\n{research}\n\n"
        f"Based on this research, estimate the TRUE probability that this market "
        f"resolves YES. Consider:\n"
        f"1. Base rates for similar events\n"
        f"2. Specific evidence for/against\n"
        f"3. Time remaining and conditions needed\n"
        f"4. Potential for surprise outcomes\n\n"
        f"Respond ONLY with valid JSON (no markdown):\n"
        f'{{"probability": 0.XX, "confidence": 0.X, "reasoning": "brief explanation"}}'
    )

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Output only valid JSON. No markdown fences."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=200,
            temperature=0.1,
        )
        text = response.choices[0].message.content.strip()

        # Clean potential markdown fences
        text = re.sub(r'^```json\s*', '', text)
        text = re.sub(r'\s*```$', '', text)

        result = json.loads(text)
        prob = float(result.get("probability", 0))
        conf = float(result.get("confidence", 0.5))
        reasoning = result.get("reasoning", "")

        if 0.0 < prob < 1.0:
            return {
                "probability": round(prob, 4),
                "confidence": round(min(conf, 0.95), 2),
                "reasoning": reasoning,
            }
        else:
            log(f"GPT returned out-of-range probability: {prob}")
            return None

    except json.JSONDecodeError as e:
        log(f"GPT JSON parse error: {e} — text: {text[:200]}")
        return None
    except Exception as e:
        error_str = str(e)
        if "401" in error_str or "invalid_api_key" in error_str:
            log("OpenAI auth failed — falling back")
        elif "429" in error_str or "rate_limit" in error_str:
            log("OpenAI rate limited — falling back")
        else:
            log(f"GPT exception: {e}")
        return None


def layer1_estimate(
    question: str,
    market_price: float,
    category: str,
    market_id: str = "",
    context: str = "",
) -> dict | None:
    """
    Full AI-powered estimate: Perplexity research → GPT probability extraction.
    Returns None if APIs unavailable (triggers fallback).
    """
    # Check cache first (30-min window)
    if market_id:
        cached = get_cached_estimate(market_id, max_age_sec=1800)
        if cached and cached.get("source") == "layer1_ai":
            log(f"Cache hit for {market_id}")
            return cached

    # Step 1: Perplexity web research
    research = call_perplexity(question, context)
    if not research:
        return None

    # Step 2: GPT probability extraction
    gpt_result = extract_probability_gpt(question, research, market_price)
    if not gpt_result:
        return None

    estimate = {
        "probability": gpt_result["probability"],
        "confidence": gpt_result["confidence"],
        "source": "layer1_ai",
        "reasoning": f"AI: {gpt_result['reasoning']} | Research: {research[:300]}",
    }

    record_call("perplexity")
    record_call("openai")

    # Cache it
    if market_id:
        set_cached_estimate(market_id, estimate)

    return estimate


# ════════════════════════════════════════════════════════
#  MAIN ESTIMATOR: cascading 3-layer fallback
# ════════════════════════════════════════════════════════

def estimate_probability(
    question: str,
    market_price: float,
    category: str,
    market_id: str = "",
    yes_token_id: str = "",
    no_token_id: str = "",
    context: str = "",
) -> dict:
    """
    Master estimator with automatic fallback:
    Layer 1 (AI) → Layer 2 (quant) → Layer 3 (Becker).

    Always returns a dict with: probability, confidence, source, reasoning.
    """
    # ── Try Layer 1: AI-powered (if keys available) ────
    keys = api_keys_available_quick()
    _within_cap = within_daily_cap()
    if _within_cap and keys["openai"] and keys["perplexity"]:
        try:
            result = layer1_estimate(question, market_price, category, market_id, context)
            if result:
                log(f"L1 estimate for '{question[:50]}': {result['probability']:.3f} "
                    f"(conf {result['confidence']:.2f})")
                return result
        except Exception as e:
            log(f"Layer 1 failed: {e}")

    # ── Try Layer 2: Free quantitative signals ─────────
    if yes_token_id:
        try:
            result = layer2_estimate(market_price, category, yes_token_id, no_token_id)
            if result and result.get("confidence", 0) > 0.3:
                log(f"L2 estimate for '{question[:50]}': {result['probability']:.3f} "
                    f"(conf {result['confidence']:.2f})")
                return result
        except Exception as e:
            log(f"Layer 2 failed: {e}")

    # ── Layer 3: Becker baseline (always works) ────────
    result = layer3_estimate(market_price, category)
    log(f"L3 estimate for '{question[:50]}': {result['probability']:.3f}")
    return result


def api_keys_available_quick() -> dict:
    """Quick check without reloading .env every time."""
    return {
        "openai": bool(get_api_key("OPENAI_API_KEY")),
        "perplexity": bool(get_api_key("PERPLEXITY_API_KEY")),
    }


# ════════════════════════════════════════════════════════
#  SELF-TEST
# ════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n=== Smart Estimator Self-Test ===\n")

    # Test Layer 3
    print("Layer 3 (Becker bias):")
    for price in [0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95]:
        r = layer3_estimate(price, "crypto")
        print(f"  Price {price:.2f} → est prob {r['probability']:.4f} "
              f"(bias: {r['probability'] - price:+.4f})")

    # Test Layer 2 (will make real API calls to public CLOB)
    print("\nLayer 2 (quantitative — needs a real token ID):")
    print("  Skipping — no token ID in self-test")

    # Test Layer 1 (only if keys set)
    keys = api_keys_available_quick()
    print(f"\nAPI keys: OpenAI={keys['openai']}, Perplexity={keys['perplexity']}")
    if keys["openai"] and keys["perplexity"]:
        print("\nLayer 1 (AI-powered):")
        r = layer1_estimate(
            "Will Bitcoin exceed $100,000 by end of April 2026?",
            0.45, "crypto", "test_btc_100k"
        )
        if r:
            print(f"  Prob: {r['probability']:.3f}, Conf: {r['confidence']:.2f}")
            print(f"  Reasoning: {r['reasoning'][:200]}")
        else:
            print("  Layer 1 returned None — check API keys")
    else:
        print("Layer 1 skipped — no API keys configured")

    print("\n=== Cascading test ===")
    r = estimate_probability(
        "Will it rain in London tomorrow?",
        0.60, "weather", "test_rain"
    )
    print(f"Final: prob={r['probability']:.3f}, source={r['source']}, "
          f"conf={r['confidence']:.2f}")
    print(f"Reasoning: {r['reasoning'][:200]}")
    print("\nDone.")
