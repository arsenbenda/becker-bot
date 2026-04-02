#!/usr/bin/env python3
"""
POLYMARKET PAPER TRADING BOT v3 - "The Becker Bot"
"""

import requests
import json
import time
import os
import numpy as np
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional

# CONFIG
LIVE_MODE = False
PAPER_BANKROLL = 500.00
KELLY_FRACTION = 0.25
MAX_BET_PCT = 0.05
MIN_EV_THRESHOLD = 0.05
MIN_EDGE_POINTS = 0.05
MAX_CONCURRENT = 30
MIN_LIQUIDITY = 5000
SCAN_INTERVAL = 120
TARGET_ANNUAL_VOL = 0.15
MAX_LEVERAGE = 1.5
MIN_VOL_ALLOCATION = 0.20
EWMA_DECAY = 0.94
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"

CATEGORY_EDGE = {
    "sports": 2.23, "politics": 1.02, "crypto": 2.69,
    "finance": 0.17, "entertainment": 4.79, "media": 7.28,
    "world_events": 7.32, "weather": 2.57, "culture": 4.79,
    "tech": 1.50, "geopolitics": 7.32, "economics": 1.02,
    "default": 1.50,
}

FEE_PARAMS = {
    "crypto":        {"rate": 0.072, "exp": 1,   "rebate": 0.20},
    "sports":        {"rate": 0.030, "exp": 1,   "rebate": 0.25},
    "finance":       {"rate": 0.040, "exp": 1,   "rebate": 0.50},
    "politics":      {"rate": 0.040, "exp": 1,   "rebate": 0.25},
    "economics":     {"rate": 0.030, "exp": 0.5, "rebate": 0.25},
    "culture":       {"rate": 0.050, "exp": 1,   "rebate": 0.25},
    "entertainment": {"rate": 0.050, "exp": 1,   "rebate": 0.25},
    "weather":       {"rate": 0.025, "exp": 0.5, "rebate": 0.25},
    "tech":          {"rate": 0.040, "exp": 1,   "rebate": 0.25},
    "geopolitics":   {"rate": 0.0,   "exp": 1,   "rebate": 0.0},
    "world_events":  {"rate": 0.0,   "exp": 1,   "rebate": 0.0},
    "default":       {"rate": 0.200, "exp": 2,   "rebate": 0.25},
}

# LAYER 1: MARKET DISCOVERY
def fetch_active_markets(limit=100):
    try:
        resp = requests.get(
            f"{GAMMA_API}/markets",
            params={"active":"true","closed":"false",
                    "order":"volume24hr","ascending":"false","limit":limit},
            timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log(f"[ERROR] Gamma API: {e}")
        return []

def parse_market(raw):
    try:
        outcomes = json.loads(raw.get("outcomes","[]"))
        prices = json.loads(raw.get("outcomePrices","[]"))
        token_ids = json.loads(raw.get("clobTokenIds","[]"))
        if len(outcomes)<2 or len(prices)<2 or len(token_ids)<2:
            return None
        yes_price = float(prices[0])
        no_price = float(prices[1])
        liquidity = float(raw.get("liquidity",0))
        if yes_price<=0.01 or yes_price>=0.99:
            return None
        if liquidity<MIN_LIQUIDITY:
            return None
        category = infer_category(raw)
        return {
            "id": raw.get("conditionId",""),
            "question": raw.get("question","Unknown"),
            "slug": raw.get("slug",""),
            "yes_price": yes_price, "no_price": no_price,
            "volume_24h": float(raw.get("volume24hr",0)),
            "liquidity": liquidity, "category": category,
            "token_ids": token_ids,
            "end_date": raw.get("endDate",""),
        }
    except Exception:
        return None

def infer_category(raw):
    tags = raw.get("tags",[])
    if isinstance(tags,str):
        try: tags = json.loads(tags)
        except: tags = []
    tag_names = []
    for t in tags:
        if isinstance(t,dict):
            tag_names.append(t.get("label","").lower())
            tag_names.append(t.get("slug","").lower())
        else:
            tag_names.append(str(t).lower())
    tag_str = " ".join(tag_names)
    for cat in CATEGORY_EDGE:
        if cat in tag_str:
            return cat
    return "default"

# LAYER 2: PROBABILITY ESTIMATION
def estimate_mispricing_adjustment(price):
    if price<=0.01:   return -0.005
    elif price<=0.05: return -0.008
    elif price<=0.10: return -0.006
    elif price<=0.15: return -0.004
    elif price<=0.20: return -0.003
    elif price>=0.95: return +0.008
    elif price>=0.90: return +0.006
    elif price>=0.85: return +0.004
    elif price>=0.80: return +0.003
    else: return 0.0

def estimate_probability(market):
    implied = market["yes_price"]
    adj = estimate_mispricing_adjustment(implied)
    return max(0.01, min(0.99, implied + adj))

# LAYER 3: EDGE ILLUSION FILTER
def edge_is_real(market_price, estimated_prob):
    edge = abs(estimated_prob - market_price)
    if edge < MIN_EDGE_POINTS:
        return {"pass":False,"edge_pp":round(edge*100,1)}
    sensitivity = {}
    for err in [0.01,0.02,0.03,0.04,0.05]:
        degraded = estimated_prob - err if estimated_prob > market_price \
                   else estimated_prob + err
        degraded_ev = (degraded*(1.0-market_price))-((1-degraded)*market_price)
        sensitivity[f"wrong_by_{int(err*100)}pp"] = round(degraded_ev,4)
    return {"pass":True,"edge_pp":round(edge*100,1),"sensitivity":sensitivity}

# LAYER 4: EV WITH FEES
def calculate_taker_fee(price, category):
    params = FEE_PARAMS.get(category.lower(), FEE_PARAMS["default"])
    if params["rate"]==0: return 0.0
    return price * params["rate"] * ((price*(1-price))**params["exp"])

def calculate_ev(market_price, estimated_prob, category):
    gross_yes = (estimated_prob*(1.0-market_price))-((1-estimated_prob)*market_price)
    fee_yes = calculate_taker_fee(market_price, category)
    net_yes = gross_yes - fee_yes
    no_price = 1.0 - market_price
    no_prob = 1.0 - estimated_prob
    gross_no = (no_prob*(1.0-no_price))-((1-no_prob)*no_price)
    fee_no = calculate_taker_fee(no_price, category)
    net_no = gross_no - fee_no
    if net_yes > net_no and net_yes > MIN_EV_THRESHOLD:
        return {"side":"YES","price":market_price,
                "gross_ev":round(gross_yes,4),"fee":round(fee_yes,4),
                "net_ev":round(net_yes,4),"verdict":"BUY YES"}
    elif net_no > MIN_EV_THRESHOLD:
        return {"side":"NO","price":no_price,
                "gross_ev":round(gross_no,4),"fee":round(fee_no,4),
                "net_ev":round(net_no,4),"verdict":"BUY NO"}
    return {"side":None,"price":0,
            "gross_ev":round(max(gross_yes,gross_no),4),
            "fee":round(max(fee_yes,fee_no),4),
            "net_ev":round(max(net_yes,net_no),4),
            "verdict":"SKIP"}

# LAYER 5: KELLY CRITERION
def kelly_size(bankroll, price, estimated_prob, correlated=False):
    if price<=0 or price>=1 or bankroll<=0:
        return {"bet":0,"contracts":0,"pct":0,"warning":None}
    b = (1.0-price)/price
    q = 1.0 - estimated_prob
    full_kelly = (estimated_prob*b - q)/b
    if full_kelly<=0:
        return {"bet":0,"contracts":0,"pct":0,"warning":None}
    adj = full_kelly * KELLY_FRACTION
    if correlated: adj *= 0.5
    adj = min(adj, MAX_BET_PCT)
    bet = round(bankroll*adj, 2)
    contracts = int(bet/price)
    if contracts<1:
        return {"bet":0,"contracts":0,"pct":0,"warning":None}
    potential_return = (1.0-price)/price
    warning = None
    if potential_return>3.0 and adj*100<2.0:
        warning = f"LONGSHOT TRAP: {potential_return:.1f}x payout but Kelly says only {adj*100:.1f}%"
    elif potential_return<0.5 and adj*100>3.0:
        warning = f"BORING-BUT-GOOD: {potential_return:.1f}x payout but Kelly says {adj*100:.1f}%"
    return {"bet":bet,"contracts":contracts,"pct":round(adj*100,2),
            "max_profit":round(contracts*(1.0-price),2),
            "max_loss":round(contracts*price,2),
            "full_kelly_pct":round(full_kelly*100,2),"warning":warning}

# LAYER 6: VOLATILITY ADJUSTMENT
def ewma_vol(prices):
    if len(prices)<5: return None
    arr = np.array(np.clip(prices,0.01,0.99))
    log_ret = np.diff(np.log(arr))
    if len(log_ret)<3: return None
    sq = log_ret**2
    var = sq[0]
    for r2 in sq[1:]:
        var = EWMA_DECAY*var + (1-EWMA_DECAY)*r2
    return float(np.sqrt(var)*np.sqrt(365))

def vol_adjust(kelly_contracts, kelly_bet, price, price_history):
    if kelly_contracts<1:
        return {"contracts":0,"bet":0,"scalar":1.0}
    vol = ewma_vol(price_history)
    if vol is None or vol<=0:
        return {"contracts":kelly_contracts,"bet":kelly_bet,"scalar":1.0}
    raw = TARGET_ANNUAL_VOL/vol
    scalar = min(raw,1.0)
    scalar = min(scalar, MAX_LEVERAGE)
    scalar = max(scalar, MIN_VOL_ALLOCATION)
    adj_c = max(1, int(kelly_contracts*scalar))
    return {"contracts":adj_c,"bet":round(adj_c*price,2),
            "scalar":round(scalar,3),"vol":round(vol,4)}

def fetch_price_history(token_id, days=30):
    try:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        resp = requests.get(f"{CLOB_API}/prices-history",
            params={"market":token_id,
                    "startTs":int(start.timestamp()),
                    "endTs":int(end.timestamp()),
                    "interval":"1d","fidelity":60},timeout=15)
        if resp.status_code!=200: return []
        data = resp.json()
        if isinstance(data,list):
            return [float(p.get("p",p.get("price",0))) for p in data if p]
        return []
    except: return []

# BAYESIAN RE-EVALUATION
def reevaluate_position(position, current_yes_price, category):
    if position.side=="YES":
        current_edge = position.est_prob - current_yes_price
    else:
        current_edge = (1-position.est_prob)-(1-current_yes_price)
    ev = calculate_ev(current_yes_price, position.est_prob, category)
    relevant_ev = ev["net_ev"] if ev["side"]==position.side else -abs(ev["net_ev"])
    if position.side=="YES":
        unrealized = (current_yes_price-position.price)*position.contracts
    else:
        unrealized = ((1-current_yes_price)-position.price)*position.contracts
    action = "HOLD"
    reason = ""
    if current_edge<0:
        action = "EXIT"
        reason = f"Edge flipped: {current_edge*100:+.1f}pp"
    elif current_edge<0.03:
        action = "REDUCE"
        reason = f"Edge thinning: {current_edge*100:.1f}pp"
    elif relevant_ev<MIN_EV_THRESHOLD:
        action = "EXIT"
        reason = f"Net EV dropped to ${relevant_ev:.4f}"
    return {"action":action,"reason":reason,
            "edge_pp":round(current_edge*100,1),
            "net_ev":round(relevant_ev,4),
            "unrealized_pnl":round(unrealized,2)}

# MAKER-EDGE SCORING
def maker_edge_score(category, price):
    gap = CATEGORY_EDGE.get(category.lower(), CATEGORY_EDGE["default"])
    tail = 1.0
    if price<0.10 or price>0.90: tail = 2.5
    elif price<0.20 or price>0.80: tail = 1.5
    yes_asym = 1.5 if price<0.15 else 0.0
    return round(min((gap*tail)+yes_asym, 10.0), 2)

# DATA STRUCTURES
@dataclass
class PaperPosition:
    market_id: str
    question: str
    side: str
    price: float
    contracts: int
    est_prob: float
    category: str
    max_profit: float
    max_loss: float
    net_ev: float
    kelly_pct: float
    maker_score: float
    vol_scalar: float
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat())

# TRADING ENGINE
class BeckerBot:
    def __init__(self, bankroll=PAPER_BANKROLL):
        self.initial_bankroll = bankroll
        self.bankroll = bankroll
        self.positions = []
        self.closed = []
        self.trade_count = 0
        self.scan_count = 0
        self.skipped_edge = 0
        self.skipped_ev = 0
        self.skipped_maker = 0
        self.skipped_kelly = 0

    def evaluate(self, market):
        est_prob = estimate_probability(market)
        edge_check = edge_is_real(market["yes_price"], est_prob)
        if not edge_check["pass"]:
            self.skipped_edge += 1
            return None
        ev = calculate_ev(market["yes_price"], est_prob, market["category"])
        if ev["side"] is None:
            self.skipped_ev += 1
            return None
        side = ev["side"]
        price = ev["price"]
        mscore = maker_edge_score(market["category"], price)
        if mscore < 2.0:
            self.skipped_maker += 1
            return None
        k = kelly_size(self.bankroll, price, est_prob)
        if k["contracts"] < 1:
            self.skipped_kelly += 1
            return None
        if k["warning"]:
            log(f"  BIAS: {k['warning']}")
        token_idx = 0 if side=="YES" else 1
        token_id = market["token_ids"][token_idx] if len(market["token_ids"])>token_idx else ""
        history = fetch_price_history(token_id) if token_id else []
        va = vol_adjust(k["contracts"], k["bet"], price, history)
        if va["contracts"]<1:
            return None
        return PaperPosition(
            market_id=market["id"], question=market["question"][:80],
            side=side, price=price, contracts=va["contracts"],
            est_prob=est_prob, category=market["category"],
            max_profit=round(va["contracts"]*(1.0-price),2),
            max_loss=round(va["contracts"]*price,2),
            net_ev=ev["net_ev"], kelly_pct=k["pct"],
            maker_score=mscore, vol_scalar=va["scalar"])

    def place_paper_trade(self, pos):
        cost = round(pos.contracts*pos.price, 2)
        if cost>self.bankroll or len(self.positions)>=MAX_CONCURRENT:
            return
        self.bankroll -= cost
        self.positions.append(pos)
        self.trade_count += 1
        log(f"\n  +-- PAPER TRADE #{self.trade_count} -------------------------")
        log(f"  | {pos.question}")
        log(f"  | {pos.side} @ ${pos.price:.2f}  |  {pos.contracts} contracts  |  ${cost:.2f}")
        log(f"  | Net EV: ${pos.net_ev:.4f}/contract  |  Kelly: {pos.kelly_pct}%  |  Maker: {pos.maker_score}/10")
        log(f"  | Vol scalar: {pos.vol_scalar}  |  Category: {pos.category}")
        log(f"  | Max profit: ${pos.max_profit:.2f}  |  Max loss: ${cost:.2f}")
        log(f"  +-- Balance: ${self.bankroll:.2f} remaining")

    def reevaluate_positions(self, market_lookup):
        if not self.positions: return
        exits = []
        for pos in self.positions:
            if pos.market_id not in market_lookup: continue
            current = market_lookup[pos.market_id]
            result = reevaluate_position(pos, current["yes_price"], pos.category)
            if result["action"]=="EXIT":
                log(f"  X EXIT: {pos.question[:50]}")
                log(f"         {result['reason']}  |  P&L: ${result['unrealized_pnl']:+.2f}")
                exits.append((pos, result))
            elif result["action"]=="REDUCE":
                log(f"  ! WARN: {pos.question[:50]}")
                log(f"         {result['reason']}")
        for pos, result in exits:
            cost = pos.contracts*pos.price
            pnl = result["unrealized_pnl"]
            self.bankroll += cost + pnl
            self.positions.remove(pos)
            self.closed.append({"question":pos.question,"side":pos.side,
                "entry":pos.price,"pnl":pnl,"reason":result["reason"]})

    def scan(self):
        self.scan_count += 1
        self.skipped_edge = 0
        self.skipped_ev = 0
        self.skipped_maker = 0
        self.skipped_kelly = 0
        now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        log(f"\n{'='*62}")
        log(f"  SCAN #{self.scan_count}  |  {now}  |  "
            f"${self.bankroll:.2f}  |  {len(self.positions)}/{MAX_CONCURRENT} positions")
        log(f"{'='*62}")
        raw_markets = fetch_active_markets(limit=100)
        log(f"  Fetched {len(raw_markets)} markets")
        market_lookup = {}
        parsed_markets = []
        for raw in raw_markets:
            m = parse_market(raw)
            if m:
                market_lookup[m["id"]] = m
                parsed_markets.append(m)
        log(f"  Parsed {len(parsed_markets)} valid markets (liquidity >= ${MIN_LIQUIDITY})")
        self.reevaluate_positions(market_lookup)
        evaluated = 0
        placed = 0
        for market in parsed_markets:
            if any(p.market_id==market["id"] for p in self.positions):
                continue
            evaluated += 1
            pos = self.evaluate(market)
            if pos:
                self.place_paper_trade(pos)
                placed += 1
        log(f"\n  Evaluated: {evaluated}  |  New trades: {placed}")
        log(f"  Filtered -- edge: {self.skipped_edge}  |  "
            f"EV+fees: {self.skipped_ev}  |  "
            f"maker: {self.skipped_maker}  |  "
            f"kelly: {self.skipped_kelly}")

    def dashboard(self):
        capital_deployed = sum(p.contracts*p.price for p in self.positions)
        total_accounted = self.bankroll + capital_deployed
        realized_pnl = sum(c["pnl"] for c in self.closed)
        log(f"\n{'-'*62}")
        log(f"  DASHBOARD")
        log(f"  Starting:     ${self.initial_bankroll:.2f}")
        log(f"  Cash:         ${self.bankroll:.2f}")
        log(f"  Deployed:     ${capital_deployed:.2f}")
        log(f"  Accounted:    ${total_accounted:.2f}")
        log(f"  Realized P&L: ${realized_pnl:+.2f}  ({len(self.closed)} closed)")
        log(f"  Open:         {len(self.positions)} positions  |  {self.trade_count} total trades")
        log(f"{'-'*62}")
        if self.positions:
            log(f"  {'Side':<4} {'$':<6} {'Qty':<5} {'EV':<8} {'K%':<6} "
                f"{'Mkr':<5} {'Vol':<5} {'Cat':<12} Question")
            for p in self.positions:
                log(f"  {p.side:<4} {p.price:<6.2f} {p.contracts:<5} "
                    f"${p.net_ev:<7.4f} {p.kelly_pct:<6} "
                    f"{p.maker_score:<5} {p.vol_scalar:<5} "
                    f"{p.category:<12} {p.question[:35]}")
        if self.closed:
            log(f"\n  Last 5 closed:")
            for c in self.closed[-5:]:
                log(f"    ${c['pnl']:+.2f}  {c['side']}  {c['question'][:40]}  ({c['reason'][:30]})")

# LOGGING
LOG_FILE = "/opt/becker-bot/becker_bot.log"

def log(msg):
    print(msg, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(msg + "\n")
    except: pass

# MAIN
def main():
    log(f"""
================================================================
  POLYMARKET PAPER TRADING BOT v3 - "The Becker Bot"

  Empirical foundations:
    72.1M trades / $18.26B volume (Becker, Jan 2026)
    Maker +1.12% vs Taker -1.12% per trade
    Longshot bias: 1c contracts win 0.43% not 1%
    Fee-adjusted for 2026-03-30 schedule

  6-layer pipeline: Discovery > Mispricing > Edge Filter >
  EV+Fees > Kelly Sizing > Vol Adjustment

  Mode: PAPER TRADE - no real money
  Bankroll: ${PAPER_BANKROLL:.2f}
  Scan interval: {SCAN_INTERVAL}s
================================================================
    """)

    if LIVE_MODE:
        log("  WARNING: LIVE MODE ENABLED")
        confirm = input("  Type 'I ACCEPT THE RISK' to continue: ")
        if confirm != "I ACCEPT THE RISK":
            log("  Aborted.")
            return

    bot = BeckerBot(bankroll=PAPER_BANKROLL)

    try:
        while True:
            bot.scan()
            bot.dashboard()
            log(f"\n  Next scan in {SCAN_INTERVAL}s... (Ctrl+C to stop)\n")
            time.sleep(SCAN_INTERVAL)
    except KeyboardInterrupt:
        log("\n\n  Shutting down...")
        bot.dashboard()
        log(f"\n  Full log saved to {LOG_FILE}")
        log("  No real money was risked.")

if __name__ == "__main__":
    main()
