"""
Becker Bot v4.1 — Polymarket Paper-Trading Bot
Fixed: Gamma API params, outcomePrices parsing, dashboard charts.
"""
import time
import json
import math
import requests
import numpy as np
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict

from shared_state import (
    load_config, save_config, save_bot_status,
    append_trade, save_positions, load_positions,
    CATEGORY_EDGE, FEE_PARAMS, GAMMA_API, CLOB_API, LOG_FILE,
    calc_polymarket_fee, calc_round_trip_fees, POLYMARKET_FEE_RATES
)
from smart_estimator import estimate_probability, fetch_price_history
from self_learner import (
    run_learning_cycle, apply_learned_corrections,
    should_trade_market, should_avoid_category,
    load_learner_state
)


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [bot] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


@dataclass
class PaperPosition:
    market_id: str = ""
    question: str = ""
    side: str = "YES"
    entry_price: float = 0.0
    contracts: float = 0.0
    cost: float = 0.0
    estimated_prob: float = 0.0
    category: str = ""
    ev: float = 0.0
    kelly_pct: float = 0.0
    maker_score: float = 0.0
    vol_scalar: float = 1.0
    estimator_source: str = ""
    estimator_confidence: float = 0.0
    opened_at: str = ""
    yes_token_id: str = ""
    no_token_id: str = ""
    status: str = "open"
    close_price: float = 0.0
    pnl: float = 0.0
    closed_at: str = ""


# ════════════════════════════════════════════════════════
#  MARKET DISCOVERY (FIXED)
# ════════════════════════════════════════════════════════

def fetch_active_markets(limit: int = 100) -> list:
    """Fetch active markets from Gamma API."""
    try:
        r = requests.get(
            f"{GAMMA_API}/events",
            params={
                "active": "true",
                "closed": "false",
                "limit": limit,
            },
            timeout=15,
        )
        if r.status_code == 200:
            events = r.json()
            markets = []
            for event in events:
                event_tags = []
                for t in event.get("tags", []):
                    if isinstance(t, dict):
                        event_tags.append(t.get("label", t.get("slug", "")).lower())
                    elif isinstance(t, str):
                        event_tags.append(t.lower())

                for m in event.get("markets", []):
                    # Skip closed markets inside open events
                    if m.get("closed", False):
                        continue
                    if not m.get("active", True):
                        continue
                    m["_event_title"] = event.get("title", "")
                    m["_event_tags"] = event_tags
                    m["_event_volume24hr"] = event.get("volume24hr", 0)
                    m["_event_liquidity"] = event.get("liquidity", 0)
                    markets.append(m)
            return markets
        else:
            log(f"Gamma API error: HTTP {r.status_code}")
            return []
    except Exception as e:
        log(f"Gamma API exception: {e}")
        return []


def parse_market(raw: dict) -> dict | None:
    """Extract relevant fields — handles string-encoded JSON."""
    try:
        question = raw.get("question", "")
        if not question:
            return None

        # clobTokenIds can be string or list
        clob_ids = raw.get("clobTokenIds", [])
        if isinstance(clob_ids, str):
            try:
                clob_ids = json.loads(clob_ids)
            except json.JSONDecodeError:
                clob_ids = []
        if not clob_ids or len(clob_ids) < 2:
            return None

        # outcomePrices can be string or list
        outcome_prices = raw.get("outcomePrices", [])
        if isinstance(outcome_prices, str):
            try:
                outcome_prices = json.loads(outcome_prices)
            except json.JSONDecodeError:
                outcome_prices = []
        if not outcome_prices or len(outcome_prices) < 2:
            return None

        yes_price = float(outcome_prices[0])
        no_price = float(outcome_prices[1])

        if yes_price <= 0.01 or yes_price >= 0.99:
            return None

        # Liquidity: try market-level first, fall back to event-level
        liquidity = float(raw.get("liquidity", 0) or 0)
        if liquidity == 0:
            liquidity = float(raw.get("_event_liquidity", 0) or 0)

        volume_24h = float(raw.get("volume24hr", 0) or 0)
        if volume_24h == 0:
            volume_24h = float(raw.get("_event_volume24hr", 0) or 0)

        return {
            "id": raw.get("id", raw.get("conditionId", "")),
            "question": question,
            "yes_price": yes_price,
            "no_price": no_price,
            "yes_token_id": clob_ids[0],
            "no_token_id": clob_ids[1],
            "volume_24h": volume_24h,
            "liquidity": liquidity,
            "event_title": raw.get("_event_title", ""),
            "tags": raw.get("_event_tags", []),
            "end_date": raw.get("endDate", ""),
        }
    except (ValueError, IndexError, KeyError) as e:
        return None


def infer_category(market: dict) -> str:
    tags = market.get("tags", [])
    question = market.get("question", "").lower()
    event = market.get("event_title", "").lower()
    text = " ".join(tags + [question, event])

    # Order matters: more specific categories first to avoid misclassification
    # e.g. "president" must match politics before "win the" matches sports
    category_rules = [
        ("geopolitics", ["nato", "sanctions", "ceasefire", "treaty", "invasion",
                         "military", "troops", "capture", "sovereignty",
                         "invade", "clash", "russia", "ukraine", "china",
                         "taiwan", "syria", "israel", "palestine", "iran"]),
        ("politics", ["president", "election", "trump", "biden", "democrat",
                       "republican", "congress", "senate", "governor", "vote",
                       "speaker", "party", "primary", "nominee", "presidential",
                       "out as", "vance", "desantis", "newsom", "shapiro",
                       "rubio", "ocasio", "buttigieg", "pritzker", "whitmer",
                       "beshear", "ossoff", "carlson", "harris", "obama",
                       "macron", "starmer", "putin", "xi jinping",
                       "balance of power", "scotus"]),
        ("crypto", ["bitcoin", "btc", "eth", "ethereum", "crypto", "solana",
                     "sol", "defi", "token", "usdc", "usdt", "xrp", "doge",
                     "coin", "megaeth", "airdrop", "market cap (fdv)"]),
        ("sports", ["nba", "nfl", "mlb", "nhl", "soccer", "football",
                     "basketball", "tennis", "ufc", "stanley cup",
                     "championship", "premier league", "la liga", "fifa",
                     "world cup", "qualify", "mvp", "rookie of the",
                     "conference finals", "playoffs", "stanley cup",
                     "hurricanes", "stars", "oilers", "avalanche",
                     "thunder", "cavaliers", "celtics", "knicks",
                     "rockets", "nuggets", "spurs", "lakers", "warriors"]),
        ("finance", ["stock", "s&p", "nasdaq", "dow", "fed ", "interest rate",
                      "gdp", "inflation", "earnings", "ipo"]),
        ("entertainment", ["oscar", "grammy", "movie", "film", "album",
                           "tv show", "emmy", "box office", "celebrity",
                           "gta vi", "gta 6", "rihanna", "drake",
                           "playboi carti", "streaming", "netflix",
                           "weinstein", "bitboy", "epstein",
                           "taylor swift", "pregnant", "kardashian",
                           "beyonce", "kanye", "selena gomez", "justin bieber",
                           "travis kelce", "engaged", "married", "divorce"]),
        ("tech", ["openai", "gpt-", "microsoft", "nvidia", "semiconductor",
                  "software launch"]),
        ("weather", ["weather", "temperature", "rain", "hurricane", "snow",
                     "climate"]),
        ("economics", ["unemployment", "cpi", "jobs report", "trade deficit",
                       "housing", "recession", "tariff", "capital gains tax"]),
        ("world_events", ["earthquake", "disaster", "pandemic", "outbreak",
                          "volcano", "tsunami", "somaliland"]),
    ]

    for cat, keywords in category_rules:
        if any(kw in text for kw in keywords):
            return cat
    return "default"


# ════════════════════════════════════════════════════════
#  FEE CALCULATION
# ════════════════════════════════════════════════════════

def calculate_taker_fee(price: float, category: str) -> float:
    params = FEE_PARAMS.get(category, FEE_PARAMS["default"])
    rate = params["rate"]
    exp = params["exponent"]
    if rate == 0:
        return 0.0
    p = min(price, 1.0 - price)
    fee = rate * (p ** exp)
    return round(fee, 6)


# ════════════════════════════════════════════════════════
#  EDGE & EV
# ════════════════════════════════════════════════════════

def edge_is_real(market_price: float, estimated_prob: float, min_edge: float) -> dict:
    edge = estimated_prob - market_price
    abs_edge = abs(edge)
    passed = abs_edge >= min_edge

    sensitivity = {}
    for error_pp in [0.01, 0.02, 0.03, 0.05]:
        degraded_prob = estimated_prob - (error_pp if edge > 0 else -error_pp)
        degraded_edge = abs(degraded_prob - market_price)
        sensitivity[f"{int(error_pp*100)}pp_error"] = round(degraded_edge, 4)

    return {"passed": passed, "edge": round(edge, 4), "abs_edge": round(abs_edge, 4),
            "sensitivity": sensitivity}


def calculate_ev(market_price: float, estimated_prob: float, category: str) -> dict:
    fee_yes = calculate_taker_fee(market_price, category)
    fee_no = calculate_taker_fee(1.0 - market_price, category)

    cost_yes = market_price + fee_yes
    ev_yes = estimated_prob * 1.0 - cost_yes

    cost_no = (1.0 - market_price) + fee_no
    ev_no = (1.0 - estimated_prob) * 1.0 - cost_no

    if ev_yes >= ev_no and ev_yes > 0:
        best_side, best_ev, best_cost = "YES", ev_yes, cost_yes
    elif ev_no > 0:
        best_side, best_ev, best_cost = "NO", ev_no, cost_no
    else:
        best_side, best_ev, best_cost = "SKIP", max(ev_yes, ev_no), 0

    return {"ev_yes": round(ev_yes, 4), "ev_no": round(ev_no, 4),
            "fee_yes": round(fee_yes, 4), "fee_no": round(fee_no, 4),
            "best_side": best_side, "best_ev": round(best_ev, 4),
            "best_cost": round(best_cost, 4)}


# ════════════════════════════════════════════════════════
#  KELLY SIZING
# ════════════════════════════════════════════════════════

def kelly_size(bankroll, price, estimated_prob, side, kelly_fraction, max_bet_pct):
    if side == "YES":
        p, cost = estimated_prob, price
    else:
        p, cost = 1.0 - estimated_prob, 1.0 - price

    if cost <= 0 or cost >= 1:
        return {"bet": 0, "contracts": 0, "kelly_pct": 0, "warning": "invalid_price"}

    b = (1.0 - cost) / cost
    q = 1.0 - p
    full_kelly = (b * p - q) / b if b > 0 else 0
    if full_kelly <= 0:
        return {"bet": 0, "contracts": 0, "kelly_pct": 0, "warning": "negative_kelly"}

    adj_kelly = full_kelly * kelly_fraction
    capped = min(adj_kelly, max_bet_pct)
    bet = round(bankroll * capped, 2)
    contracts = round(bet / cost, 2) if cost > 0 else 0

    warning = ""
    if b > 5 and full_kelly < 0.15:
        warning = "long_shot_trap"
    elif b < 0.5 and full_kelly > 0.3:
        warning = "boring_but_good"

    return {"bet": bet, "contracts": contracts, "kelly_pct": round(capped * 100, 2),
            "full_kelly_pct": round(full_kelly * 100, 2), "warning": warning}


# ════════════════════════════════════════════════════════
#  VOLATILITY ADJUSTMENT
# ════════════════════════════════════════════════════════

def ewma_vol(prices, decay=0.94):
    if len(prices) < 3:
        return 0.0
    arr = np.array(prices, dtype=float)
    returns = np.diff(arr) / np.maximum(arr[:-1], 0.001)
    if len(returns) < 2:
        return 0.0
    var = returns[0] ** 2
    for r in returns[1:]:
        var = decay * var + (1 - decay) * r ** 2
    return round(math.sqrt(var) * math.sqrt(365), 4)


def vol_adjust(kelly_bet, kelly_contracts, token_id, cfg):
    target_vol = cfg.get("TARGET_ANNUAL_VOL", 0.15)
    max_lev = cfg.get("MAX_LEVERAGE", 1.5)
    min_alloc = cfg.get("MIN_VOL_ALLOCATION", 0.20)

    history = fetch_price_history(token_id)
    if not history:
        return {"bet": kelly_bet, "contracts": kelly_contracts,
                "vol_scalar": 1.0, "reason": "no_history"}

    prices = []
    for h in history:
        p = h.get("p", h.get("price", None))
        if p is not None:
            prices.append(float(p))

    if len(prices) < 5:
        return {"bet": kelly_bet, "contracts": kelly_contracts,
                "vol_scalar": 1.0, "reason": "insufficient_history"}

    vol = ewma_vol(prices, cfg.get("EWMA_DECAY", 0.94))
    if vol <= 0:
        return {"bet": kelly_bet, "contracts": kelly_contracts,
                "vol_scalar": 1.0, "reason": "zero_vol"}

    scalar = min(target_vol / vol, 1.0, max_lev)
    scalar = max(scalar, min_alloc)

    return {"bet": round(kelly_bet * scalar, 2),
            "contracts": round(kelly_contracts * scalar, 2),
            "vol_scalar": round(scalar, 3),
            "vol_annual": vol,
            "reason": f"vol={vol:.3f} → {scalar:.2f}x"}


# ════════════════════════════════════════════════════════
#  MAKER EDGE SCORE
# ════════════════════════════════════════════════════════

def maker_edge_score(market_price, category):
    cat_edge = CATEGORY_EDGE.get(category, CATEGORY_EDGE["default"])
    p = market_price

    if p <= 0.10 or p >= 0.90:
        tail = 3.0
    elif p <= 0.20 or p >= 0.80:
        tail = 2.0
    elif p <= 0.30 or p >= 0.70:
        tail = 1.0
    else:
        tail = 0.5

    if p < 0.20:
        yes_asym = 1.5
    elif p > 0.80:
        yes_asym = 0.5
    else:
        yes_asym = 1.0

    return round(min((cat_edge / 2.0) + tail + yes_asym, 10.0), 2)


# ════════════════════════════════════════════════════════
#  POSITION RE-EVALUATION
# ════════════════════════════════════════════════════════

def reevaluate_position(pos, cfg):
    market_price = pos.get("entry_price", 0.5)
    est_prob = pos.get("estimated_prob", 0.5)
    min_edge = cfg.get("MIN_EDGE_POINTS", 0.05)

    token_id = pos.get("yes_token_id", "")
    current_price = market_price
    if token_id:
        try:
            r = requests.get(f"{CLOB_API}/price",
                             params={"token_id": token_id, "side": "buy"}, timeout=5)
            if r.status_code == 200:
                current_price = float(r.json().get("price", market_price))
        except Exception:
            pass

    # Phase 0.5: Bayesian re-estimation — adjust probability toward market if price moved significantly
    price_move = abs(current_price - market_price)
    bayesian_updated = False
    if price_move > 0.03:  # >3pp price movement = new information
        # Bayesian blend: weight market signal by magnitude of move
        blend_weight = min(price_move * 2, 0.4)  # max 40% market weight
        est_prob = est_prob * (1 - blend_weight) + current_price * blend_weight
        bayesian_updated = True

    edge = abs(est_prob - current_price)

    if edge < min_edge * 0.5:
        return {"action": "EXIT", "reason": f"Edge collapsed: {edge:.3f}",
                "current_price": round(current_price, 4), "remaining_edge": round(edge, 4),
                "bayesian_updated": bayesian_updated, "new_est_prob": round(est_prob, 4)}
    elif edge < min_edge:
        # Phase 0.3: Track consecutive thin scans for trailing stop
        return {"action": "REDUCE", "reason": f"Edge thinning: {edge:.3f}",
                "current_price": round(current_price, 4), "remaining_edge": round(edge, 4),
                "edge_thin": True, "bayesian_updated": bayesian_updated, "new_est_prob": round(est_prob, 4)}
    else:
        return {"action": "HOLD", "reason": f"Edge intact: {edge:.3f}",
                "current_price": round(current_price, 4), "remaining_edge": round(edge, 4),
                "bayesian_updated": bayesian_updated, "new_est_prob": round(est_prob, 4)}


# ════════════════════════════════════════════════════════
#  MAIN BOT CLASS
# ════════════════════════════════════════════════════════

class BeckerBot:
    def __init__(self):
        self.cfg = load_config()
        self.bankroll = self.cfg["PAPER_BANKROLL"]  # default, overridden below
        self.positions: list[dict] = load_positions()
        # Restore counters from saved state (survive restarts)
        try:
            import json
            _raw = json.loads(open("/opt/becker-bot/bot_state.json").read())
            _saved = _raw.get("status", _raw)  # handle nested or flat
        except:
            _saved = {}
        _closed = [p for p in self.positions if p.get("status") == "closed"]
        self.total_trades = int(_saved.get("total_trades", len(_closed)))
        self.winning_trades = int(_saved.get("winning_trades",
            sum(1 for p in _closed if float(p.get("pnl", 0)) > 0)))
        self.realized_pnl = float(_saved.get("realized_pnl",
            sum(float(p.get("pnl", 0)) for p in _closed)))
        _closed_fees = sum(float(p.get("total_fees", 0)) for p in self.positions if p.get("status") == "closed")
        _closed_net = sum(float(p.get("net_pnl", p.get("pnl", 0))) for p in self.positions if p.get("status") == "closed")
        self.realized_pnl_net = _closed_net
        self.total_fees = _closed_fees
        log(f"  Restored fees: ${self.total_fees:.4f} | Net P&L: ${self.realized_pnl_net:+.2f}")
        self.scan_count = int(_saved.get("scan_count", 0))
        self.markets_scanned_total = int(_saved.get("markets_scanned_total", 0))
        self.layer_stats = _saved.get("layer_stats",
            {"layer1_ai": 0, "layer2_quantitative": 0, "layer3_becker": 0})
        # Restore bankroll from saved state (bot tracks it correctly during trading)
        _state_bankroll = _saved.get("bankroll", None)
        if _state_bankroll is not None and _state_bankroll != self.cfg["PAPER_BANKROLL"]:
            self.bankroll = float(_state_bankroll)
        log(f"  Restored: bankroll=${self.bankroll:.2f} P&L=${self.realized_pnl:+.2f} wins={self.winning_trades}/{self.total_trades}")
        # Restore scan_history from saved state
        self.scan_history = _saved.get("scan_history", [])
        if not self.scan_history:
            try:
                import json as _j
                _st = _j.loads(open("/opt/becker-bot/bot_state.json").read())
                self.scan_history = _st.get("status", {}).get("scan_history", [])
            except:
                self.scan_history = []
        self.learner_state = load_learner_state()
        log("BeckerBot v4.1 initialized — self-learner loaded")
        log(f"  Mode: {'LIVE' if self.cfg['LIVE_MODE'] else 'PAPER'}")
        log(f"  Bankroll: ${self.bankroll:.2f}")
        log(f"  Kelly: {self.cfg['KELLY_FRACTION']*100:.0f}% | "
            f"Max bet: {self.cfg['MAX_BET_PCT']*100:.0f}% | "
            f"Min edge: {self.cfg['MIN_EDGE_POINTS']*100:.0f}pp | "
            f"Min EV: ${self.cfg['MIN_EV_THRESHOLD']:.2f}")

    def reload_config(self):
        self.cfg = load_config()

    def evaluate(self, market: dict) -> PaperPosition | None:
        cfg = self.cfg
        question = market["question"]
        yes_price = market["yes_price"]
        category = infer_category(market)

        # Step 0: Market memory check
        mem_check = should_trade_market(
            self.learner_state, market["id"],
            yes_price, "YES"
        )
        if not mem_check["allowed"]:
            return None

        # Step 0b: Category avoidance check
        if should_avoid_category(self.learner_state, category):
            return None

        # Step 1: Smart probability estimation
        est = estimate_probability(
            question=question, market_price=yes_price, category=category,
            market_id=market["id"],
            yes_token_id=market.get("yes_token_id", ""),
            no_token_id=market.get("no_token_id", ""),
        )
        est_prob = est["probability"]
        source = est["source"]
        confidence = est["confidence"]
        self.layer_stats[source] = self.layer_stats.get(source, 0) + 1

        # Step 1b: Apply learned calibration corrections
        corrected = apply_learned_corrections(
            raw_probability=est_prob,
            category=category,
            source_layer=source,
            entry_price=yes_price,
            state=self.learner_state,
        )
        if corrected["corrections_applied"] > 0:
            est_prob = corrected["adjusted_probability"]

        # Step 2: Edge filter
        # Phase 0.7: Category edge sanity filter (Becker study averages)
        BECKER_CAT_INEFFICIENCY = {
            "finance": 0.0017, "politics": 0.0102, "sports": 0.0223,
            "entertainment": 0.0479, "world": 0.0732, "geopolitics": 0.0732,
            "crypto": 0.03, "science": 0.04, "other": 0.03,
        }
        _cat_avg = BECKER_CAT_INEFFICIENCY.get(category, 0.03)
        _raw_edge = abs(est_prob - yes_price)
        # Check if learner has high-confidence data for this category
        _learner_cat = self.learner_state.get("category_corrections", {}).get(category, {})
        _learner_conf = _learner_cat.get("confidence", 0)
        _learner_n = _learner_cat.get("sample_size", 0)
        if _raw_edge > _cat_avg * 3:
            if _learner_n >= 15 and _learner_conf >= 0.4:
                # Learner has enough evidence — trust it over static heuristic
                log(f"SANITY OVERRIDE: {question[:50]} edge {_raw_edge:.3f} > 3x avg, but learner has n={_learner_n} conf={_learner_conf:.2f} — trusting learner")
            else:
                log(f"SANITY: {question[:50]} edge {_raw_edge:.3f} > 3x category avg {_cat_avg:.3f} — skeptical (learner n={_learner_n})")
                est_prob = est_prob * 0.7 + yes_price * 0.3  # Shrink toward market

        edge_check = edge_is_real(yes_price, est_prob, cfg["MIN_EDGE_POINTS"])
        if not edge_check["passed"]:
            return None

        # Step 3: EV with fees
        ev = calculate_ev(yes_price, est_prob, category)
        if ev["best_side"] == "SKIP" or ev["best_ev"] < cfg["MIN_EV_THRESHOLD"]:
            return None

        # Step 4: Maker edge score
        m_score = maker_edge_score(yes_price, category)

        # Step 5: Kelly sizing
        k = kelly_size(self.bankroll, yes_price, est_prob,
                       ev["best_side"], cfg["KELLY_FRACTION"], cfg["MAX_BET_PCT"])
        if k["bet"] <= 0 or k["contracts"] <= 0:
            return None

        # Step 6: Volatility adjustment
        token_id = (market["yes_token_id"] if ev["best_side"] == "YES"
                    else market["no_token_id"])
        va = vol_adjust(k["bet"], k["contracts"], token_id, cfg)
        if va["bet"] < 1.0:
            return None

        entry_price = yes_price if ev["best_side"] == "YES" else (1.0 - yes_price)

        return PaperPosition(
            market_id=market["id"], question=question[:120], side=ev["best_side"],
            entry_price=entry_price, contracts=va["contracts"], cost=va["bet"],
            estimated_prob=est_prob, category=category, ev=ev["best_ev"],
            kelly_pct=k["kelly_pct"], maker_score=m_score,
            vol_scalar=va["vol_scalar"], estimator_source=source,
            estimator_confidence=confidence,
            opened_at=datetime.now(timezone.utc).isoformat(),
            yes_token_id=market.get("yes_token_id", ""),
            no_token_id=market.get("no_token_id", ""),
        )

    def place_paper_trade(self, pos: PaperPosition):
        self.bankroll -= pos.cost
        _pos_dict = asdict(pos)
        _entry_fee = calc_polymarket_fee(pos.contracts, pos.entry_price, pos.category)
        _pos_dict["entry_fee"] = round(_entry_fee, 5)
        _pos_dict["exit_fee"] = 0.0
        _pos_dict["total_fees"] = round(_entry_fee, 5)
        _pos_dict["net_pnl"] = 0.0
        self.positions.append(_pos_dict)
        log(f"  Fee: ${_entry_fee:.4f} (rate={POLYMARKET_FEE_RATES.get(pos.category.lower(), 0.05)})")
        self.total_trades += 1

        append_trade({
            "action": "OPEN", "market_id": pos.market_id,
            "question": pos.question, "side": pos.side,
            "price": pos.entry_price, "contracts": pos.contracts,
            "cost": pos.cost, "ev": pos.ev, "kelly_pct": pos.kelly_pct,
            "maker_score": pos.maker_score, "vol_scalar": pos.vol_scalar,
            "source": pos.estimator_source, "confidence": pos.estimator_confidence,
            "category": pos.category,
            "timestamp": pos.opened_at,
        })
        save_positions(self.positions)

        log(f"TRADE: {pos.side} {pos.question[:60]}")
        log(f"  Price: {pos.entry_price:.3f} | Contracts: {pos.contracts:.1f} | "
            f"Cost: ${pos.cost:.2f}")
        log(f"  EV: ${pos.ev:.3f} | Kelly: {pos.kelly_pct:.1f}% | "
            f"Maker: {pos.maker_score:.1f} | Vol: {pos.vol_scalar:.2f}x")
        log(f"  Source: {pos.estimator_source} (conf {pos.estimator_confidence:.2f})")

    def reevaluate_positions(self):
        if not self.positions:
            return
        # Phase 0.6: Cross-market spread z-score monitoring
        _open = [p for p in self.positions if p.get("status") == "open"]
        _questions = {}
        for p in _open:
            base_q = p.get("question", "")[:30]  # Group by question prefix
            _questions.setdefault(base_q, []).append(p)
        for base_q, group in _questions.items():
            if len(group) > 1:
                prices = [p.get("entry_price", 0.5) for p in group]
                spread = max(prices) - min(prices)
                if spread > 0.15:
                    log(f"SPREAD ALERT: '{base_q}...' — {len(group)} related positions, spread={spread:.3f}")
        updated = []
        for pos in self.positions:
            if pos.get("status") != "open":
                updated.append(pos)
                continue

            reeval = reevaluate_position(pos, self.cfg)
            if reeval["action"] == "EXIT":
                pos["status"] = "closed"
                pos["close_price"] = reeval["current_price"]
                pos["closed_at"] = datetime.now(timezone.utc).isoformat()
                if pos["side"] == "YES":
                    pnl = (reeval["current_price"] - pos["entry_price"]) * pos["contracts"]
                else:
                    pnl = (pos["entry_price"] - reeval["current_price"]) * pos["contracts"]
                pos["pnl"] = round(pnl, 2)
                _exit_fee = calc_polymarket_fee(pos["contracts"], reeval["current_price"], pos.get("category", "other"))
                pos["exit_fee"] = round(_exit_fee, 5)
                pos["entry_fee"] = pos.get("entry_fee", calc_polymarket_fee(pos["contracts"], pos["entry_price"], pos.get("category", "other")))
                pos["total_fees"] = round(pos["entry_fee"] + pos["exit_fee"], 5)
                pos["net_pnl"] = round(pnl - pos["total_fees"], 2)
                self.realized_pnl += pnl  # gross
                self.realized_pnl_net = getattr(self, "realized_pnl_net", 0) + pos["net_pnl"]
                self.total_fees = getattr(self, "total_fees", 0) + pos["total_fees"]
                self.bankroll += pos["cost"] + pnl
                if pnl > 0:
                    self.winning_trades += 1
                log(f"EXIT: {pos['question'][:60]} — {reeval['reason']} — Gross: ${pnl:+.2f} Net: ${pos['net_pnl']:+.2f} (fees: ${pos['total_fees']:.4f})")
                append_trade({"action": "CLOSE", "market_id": pos["market_id"],
                              "question": pos["question"], "reason": reeval["reason"],
                              "pnl": pos["pnl"], "timestamp": pos["closed_at"]})
            elif reeval["action"] == "REDUCE":
                # Phase 0.3: Trailing stop — count consecutive thin scans
                pos["edge_thin_count"] = pos.get("edge_thin_count", 0) + 1
                if pos["edge_thin_count"] >= 3:
                    pos["status"] = "closed"
                    pos["close_price"] = reeval["current_price"]
                    pos["closed_at"] = datetime.now(timezone.utc).isoformat()
                    if pos["side"] == "YES":
                        pnl = (reeval["current_price"] - pos["entry_price"]) * pos["contracts"]
                    else:
                        pnl = (pos["entry_price"] - reeval["current_price"]) * pos["contracts"]
                    pos["pnl"] = round(pnl, 2)
                    _exit_fee = calc_polymarket_fee(pos["contracts"], reeval["current_price"], pos.get("category", "other"))
                    pos["exit_fee"] = round(_exit_fee, 5)
                    pos["entry_fee"] = pos.get("entry_fee", calc_polymarket_fee(pos["contracts"], pos["entry_price"], pos.get("category", "other")))
                    pos["total_fees"] = round(pos["entry_fee"] + pos["exit_fee"], 5)
                    pos["net_pnl"] = round(pnl - pos["total_fees"], 2)
                    self.realized_pnl += pnl  # gross
                    self.realized_pnl_net = getattr(self, "realized_pnl_net", 0) + pos["net_pnl"]
                    self.total_fees = getattr(self, "total_fees", 0) + pos["total_fees"]
                    self.bankroll += pos["cost"] + pnl
                    if pnl > 0:
                        self.winning_trades += 1
                    log(f"TRAILING STOP: {pos['question'][:60]} — 3 scans — Gross: ${pnl:+.2f} Net: ${pos['net_pnl']:+.2f} (fees: ${pos['total_fees']:.4f})")
                    append_trade({"action": "TRAILING_STOP", "market_id": pos["market_id"],
                                  "question": pos["question"], "reason": "3x edge thinning",
                                  "pnl": pos["pnl"], "net_pnl": pos["net_pnl"], "fees": pos["total_fees"],
                                  "timestamp": pos["closed_at"]})
                else:
                    log(f"WARN: {pos['question'][:60]} — {reeval['reason']} ({pos['edge_thin_count']}/3)")
            else:
                pos["edge_thin_count"] = 0  # Reset counter if edge recovers
            # Fix 2: Persist Bayesian-blended estimate so next scan builds on it
            if pos.get("status") == "open" and reeval.get("bayesian_updated"):
                pos["estimated_prob"] = reeval["new_est_prob"]
            # Phase 1.4: Persist live price + unrealised P&L for dashboard
            if pos.get("status") == "open" and reeval.get("current_price"):
                pos["current_price"] = reeval["current_price"]
                if pos["side"] == "YES":
                    pos["unrealised_pnl"] = round(
                        (reeval["current_price"] - pos["entry_price"]) * pos["contracts"], 2)
                else:
                    pos["unrealised_pnl"] = round(
                        (pos["entry_price"] - reeval["current_price"]) * pos["contracts"], 2)
                pos["price_updated_at"] = datetime.now(timezone.utc).isoformat()
            updated.append(pos)

        self.positions = updated
        save_positions(self.positions)

    def scan(self):
        self.scan_count += 1
        self.reload_config()
        cfg = self.cfg

        log(f"═══ Scan #{self.scan_count} ═══")

        # Re-evaluate
        self.reevaluate_positions()

        open_positions = [p for p in self.positions if p.get("status") == "open"]
        if len(open_positions) >= cfg["MAX_CONCURRENT"]:
            log(f"At max concurrent ({cfg['MAX_CONCURRENT']}), skipping new trades")

        # Fetch (skip if at max capacity)
        skip_new = len(open_positions) >= cfg["MAX_CONCURRENT"]
        raw_markets = [] if skip_new else fetch_active_markets(limit=100)
        log(f"Fetched {len(raw_markets)} raw markets")

        # Parse & filter
        existing_ids = {p["market_id"] for p in self.positions}  # Phase 0.1: block ALL dupes (open + closed)
        parsed = []
        for rm in raw_markets:
            m = parse_market(rm)
            if m and m["liquidity"] >= cfg["MIN_LIQUIDITY"] and m["id"] not in existing_ids:
                parsed.append(m)

        log(f"Parsed {len(parsed)} eligible markets (liq >= ${cfg['MIN_LIQUIDITY']})")
        self.markets_scanned_total += len(parsed)

        # Phase 0.4: Daily drawdown circuit breaker
        _today_closed = [p for p in self.positions if p.get("status") == "closed"
                         and p.get("closed_at", "")[:10] == datetime.now(timezone.utc).strftime("%Y-%m-%d")]
        _today_losses = sum(float(p.get("pnl", 0)) for p in _today_closed if float(p.get("pnl", 0)) < 0)
        _drawdown_limit = self.cfg["PAPER_BANKROLL"] * 0.05
        _circuit_breaker = abs(_today_losses) >= _drawdown_limit
        if _circuit_breaker:
            log(f"CIRCUIT BREAKER: Daily loss ${_today_losses:.2f} exceeds 5% limit (${_drawdown_limit:.2f}). Pausing new trades.")

        # Evaluate
        new_trades = 0
        evaluated = 0
        for market in parsed:
            if _circuit_breaker or len(open_positions) + new_trades >= cfg["MAX_CONCURRENT"]:
                break
            evaluated += 1
            pos = self.evaluate(market)
            if pos:
                self.place_paper_trade(pos)
                new_trades += 1

        log(f"Evaluated: {evaluated} | New trades: {new_trades} | "
            f"Open: {len(open_positions) + new_trades}")

        # Save for dashboard
        scan_record = {
            "scan": self.scan_count,
            "time": datetime.now(timezone.utc).isoformat(),
            "bankroll": round(self.bankroll, 2),
            "open": len([p for p in self.positions if p.get("status") == "open"]),
            "pnl": round(self.realized_pnl, 2),
            "fetched": len(raw_markets),
            "eligible": len(parsed),
            "new_trades": new_trades,
            "deployed": round(sum(p.get("cost", 0) for p in self.positions if p.get("status") == "open"), 2),
            "total_value": round(self.bankroll + sum(p.get("cost", 0) for p in self.positions if p.get("status") == "open") + sum(float(p.get("unrealised_pnl", 0)) for p in self.positions if p.get("status") == "open"), 2),
            "unrealised_pnl": round(sum(float(p.get("unrealised_pnl", 0)) for p in self.positions if p.get("status") == "open"), 2),
        }
        self.scan_history.append(scan_record)
        if len(self.scan_history) > 500:
            self.scan_history = self.scan_history[-500:]

        # Run self-learning cycle
        self.learner_state = run_learning_cycle(self.positions)

        # Apply adaptive risk recommendations (auto-tune)
        adaptive = self.learner_state.get("adaptive_risk", {})
        if adaptive.get("status") == "active":
            rec_kelly = adaptive.get("recommended_kelly")
            rec_edge = adaptive.get("recommended_edge")
            rec_bet = adaptive.get("recommended_max_bet")
            changed = False
            if rec_kelly and abs(rec_kelly - cfg["KELLY_FRACTION"]) > 0.01:
                log(f"Auto-tune Kelly: {cfg['KELLY_FRACTION']:.3f} → {rec_kelly:.3f}")
                cfg["KELLY_FRACTION"] = rec_kelly
                changed = True
            if rec_edge and abs(rec_edge - cfg["MIN_EDGE_POINTS"]) > 0.005:
                log(f"Auto-tune Edge: {cfg['MIN_EDGE_POINTS']:.3f} → {rec_edge:.3f}")
                cfg["MIN_EDGE_POINTS"] = rec_edge
                changed = True
            if rec_bet and abs(rec_bet - cfg["MAX_BET_PCT"]) > 0.005:
                log(f"Auto-tune MaxBet: {cfg['MAX_BET_PCT']:.3f} → {rec_bet:.3f}")
                cfg["MAX_BET_PCT"] = rec_bet
                changed = True
            if changed:
                save_config(cfg)
                self.cfg = cfg

        save_bot_status({
            "scan_count": self.scan_count,
            "last_scan": datetime.now(timezone.utc).isoformat(),
            "bankroll": round(self.bankroll, 2),
            "open_positions": len([p for p in self.positions if p.get("status") == "open"]),
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "realized_pnl": round(self.realized_pnl, 2),
            "markets_fetched": len(raw_markets),
            "markets_eligible": len(parsed),
            "markets_evaluated": evaluated,
            "markets_scanned_total": self.markets_scanned_total,
            "new_trades": new_trades,
            "layer_stats": self.layer_stats,
            "scan_history": self.scan_history[-100:],
            "learner": self.learner_state.get("summary", {}),
        })

    def dashboard(self):
        open_pos = [p for p in self.positions if p.get("status") == "open"]
        deployed = sum(p.get("cost", 0) for p in open_pos)
        # Always compute from actual positions — single source of truth
        _closed = [p for p in self.positions if p.get("status") == "closed"]
        _wins = sum(1 for p in _closed if float(p.get("pnl", 0)) > 0)
        _total = len(_closed)
        win_rate = f"{_wins/_total*100:.1f}%" if _total > 0 else "N/A"
        self.total_trades = _total  # keep counters in sync
        self.winning_trades = _wins

        log("\n" + "=" * 65)
        log(f"  BECKER BOT v4.1 — {'PAPER' if not self.cfg['LIVE_MODE'] else 'LIVE'}")
        log("=" * 65)
        log(f"  Bankroll:  ${self.bankroll:>10.2f}")
        log(f"  Deployed:  ${deployed:>10.2f}")
        _unrealised = sum(float(p.get("unrealised_pnl", 0)) for p in open_pos)
        log(f"  Unreal:    ${_unrealised:>+10.2f}")
        log(f"  Total:     ${self.bankroll + deployed + _unrealised:>10.2f}")
        log(f"  P&L Gross: ${self.realized_pnl:>+10.2f}")
        log(f"  P&L Net:   ${getattr(self, 'realized_pnl_net', self.realized_pnl):>+10.2f}  (fees: ${getattr(self, 'total_fees', 0):.4f})")
        log(f"  Trades:    {self.total_trades} (win rate: {win_rate})")
        log(f"  Open:      {len(open_pos)}/{self.cfg['MAX_CONCURRENT']}")
        log(f"  Layers:    L1={self.layer_stats.get('layer1_ai',0)} "
              f"L2={self.layer_stats.get('layer2_quantitative',0)} "
              f"L3={self.layer_stats.get('layer3_becker',0)}")
        log("=" * 65)


def main():
    bot = BeckerBot()
    print("\n" + "█" * 65)
    print("  BECKER BOT v4.1 — Polymarket Paper Trading")
    print("  Becker 72.1M trades | Dunik filters | Noisy vol | 3-layer AI")
    print("█" * 65 + "\n")

    try:
        while True:
            bot.scan()
            bot.dashboard()
            # Phase 0.2: Dynamic scan interval — slower when full
            _open = len([p for p in bot.positions if p.get("status") == "open"])
            _interval = 300 if _open >= bot.cfg["MAX_CONCURRENT"] else bot.cfg["SCAN_INTERVAL"]
            log(f"Next scan in {_interval}s... ({'full capacity' if _interval == 300 else 'slots open'})")
            time.sleep(_interval)
    except KeyboardInterrupt:
        log("Bot stopped by user")
        bot.dashboard()


if __name__ == "__main__":
    main()
