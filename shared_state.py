"""
Shared state, paths, and config for Becker Bot v4
"""
import os
import json
import threading
from pathlib import Path
from dotenv import load_dotenv, set_key

# ── Paths ──────────────────────────────────────────────
BASE_DIR = Path("/opt/becker-bot")
ENV_FILE = BASE_DIR / ".env"
LOG_FILE = BASE_DIR / "becker_bot.log"
TRADES_FILE = BASE_DIR / "trades.json"
POSITIONS_FILE = BASE_DIR / "positions.json"
STATE_FILE = BASE_DIR / "bot_state.json"
CACHE_DIR = BASE_DIR / "cache"
CACHE_DIR.mkdir(exist_ok=True)

# ── Create .env if missing ─────────────────────────────
if not ENV_FILE.exists():
    ENV_FILE.touch()

load_dotenv(ENV_FILE)

# ── Thread-safe file lock ──────────────────────────────
_file_lock = threading.Lock()

# ── API key management ─────────────────────────────────
def get_api_key(name: str) -> str:
    """Read key from .env, return empty string if missing."""
    load_dotenv(ENV_FILE, override=True)
    return os.getenv(name, "").strip()

def set_api_key(name: str, value: str):
    """Write key to .env file (persists across restarts)."""
    set_key(str(ENV_FILE), name, value.strip())

def api_keys_available() -> dict:
    """Check which API keys are configured."""
    return {
        "openai": bool(get_api_key("OPENAI_API_KEY")),
        "perplexity": bool(get_api_key("PERPLEXITY_API_KEY")),
    }

# ── Bot configuration (editable from dashboard) ───────
DEFAULT_CONFIG = {
    "LIVE_MODE": False,
    "PAPER_BANKROLL": 500.0,
    "KELLY_FRACTION": 0.25,
    "MAX_BET_PCT": 0.05,
    "MIN_EV_THRESHOLD": 0.05,
    "MIN_EDGE_POINTS": 0.05,
    "MAX_CONCURRENT": 30,
    "MIN_LIQUIDITY": 5000,
    "SCAN_INTERVAL": 120,
    "TARGET_ANNUAL_VOL": 0.15,
    "MAX_LEVERAGE": 1.5,
    "MIN_VOL_ALLOCATION": 0.20,
    "EWMA_DECAY": 0.94,
}

def load_config() -> dict:
    """Load config from state file, merge with defaults."""
    cfg = DEFAULT_CONFIG.copy()
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r") as f:
                saved = json.load(f)
            if "config" in saved:
                cfg.update(saved["config"])
        except (json.JSONDecodeError, KeyError):
            pass
    return cfg

def save_config(cfg: dict):
    """Persist config to state file."""
    state = {}
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
        except (json.JSONDecodeError, KeyError):
            state = {}
    state["config"] = cfg
    with _file_lock:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)

# ── Trade/position logging ─────────────────────────────
def append_trade(trade: dict):
    """Append a trade record to trades.json."""
    with _file_lock:
        trades = []
        if TRADES_FILE.exists():
            try:
                with open(TRADES_FILE, "r") as f:
                    trades = json.load(f)
            except (json.JSONDecodeError, ValueError):
                trades = []
        trades.append(trade)
        with open(TRADES_FILE, "w") as f:
            json.dump(trades, f, indent=2)

def load_trades() -> list:
    """Load all trade records."""
    if not TRADES_FILE.exists():
        return []
    try:
        with open(TRADES_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError):
        return []

def save_positions(positions: list):
    """Overwrite current open positions."""
    with _file_lock:
        with open(POSITIONS_FILE, "w") as f:
            json.dump(positions, f, indent=2, default=str)

def load_positions() -> list:
    """Load current open positions."""
    if not POSITIONS_FILE.exists():
        return []
    try:
        with open(POSITIONS_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError):
        return []

def save_bot_status(status: dict):
    """Save bot runtime status (last scan, markets found, etc)."""
    state = {}
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
        except (json.JSONDecodeError, KeyError):
            state = {}
    state["status"] = status
    with _file_lock:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2, default=str)

def load_bot_status() -> dict:
    """Load bot runtime status."""
    if not STATE_FILE.exists():
        return {}
    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
        return state.get("status", {})
    except (json.JSONDecodeError, KeyError):
        return {}

# ── Estimator cache (for Perplexity rate/cost control) ─
def get_cached_estimate(market_id: str, max_age_sec: int = 1800) -> dict | None:
    """Return cached probability estimate if fresh enough."""
    cache_file = CACHE_DIR / f"{market_id}.json"
    if not cache_file.exists():
        return None
    try:
        with open(cache_file, "r") as f:
            data = json.load(f)
        import time
        if time.time() - data.get("timestamp", 0) < max_age_sec:
            return data
    except (json.JSONDecodeError, KeyError):
        pass
    return None

def set_cached_estimate(market_id: str, estimate: dict):
    """Cache a probability estimate."""
    import time
    estimate["timestamp"] = time.time()
    cache_file = CACHE_DIR / f"{market_id}.json"
    with open(cache_file, "w") as f:
        json.dump(estimate, f, indent=2)

# ── Category edge data (Becker 72.1M trades) ──────────
CATEGORY_EDGE = {
    "sports": 2.23, "politics": 1.02, "crypto": 2.69,
    "finance": 0.17, "entertainment": 4.79, "world_events": 7.32,
    "culture": 3.50, "science": 2.80, "weather": 1.50,
    "tech": 2.10, "economics": 1.80, "geopolitics": 0.0,
    "default": 2.50,
}

# ── Fee parameters (effective 2026-03-30) ──────────────
FEE_PARAMS = {
    "crypto":        {"rate": 0.072, "exponent": 1, "maker_rebate": 0.20},
    "sports":        {"rate": 0.030, "exponent": 1, "maker_rebate": 0.25},
    "finance":       {"rate": 0.040, "exponent": 1, "maker_rebate": 0.50},
    "politics":      {"rate": 0.040, "exponent": 1, "maker_rebate": 0.25},
    "economics":     {"rate": 0.030, "exponent": 0.5, "maker_rebate": 0.25},
    "culture":       {"rate": 0.050, "exponent": 1, "maker_rebate": 0.25},
    "entertainment": {"rate": 0.050, "exponent": 1, "maker_rebate": 0.25},
    "weather":       {"rate": 0.025, "exponent": 0.5, "maker_rebate": 0.25},
    "tech":          {"rate": 0.040, "exponent": 1, "maker_rebate": 0.25},
    "geopolitics":   {"rate": 0.0,   "exponent": 1, "maker_rebate": 0.0},
    "world_events":  {"rate": 0.0,   "exponent": 1, "maker_rebate": 0.0},
    "default":       {"rate": 0.200, "exponent": 2, "maker_rebate": 0.25},
}

print("[shared_state] Loaded OK — base dir:", BASE_DIR)

# ── API endpoints ──────────────────────────────────────
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"


# ── Polymarket Fee Model (March 30, 2026) ──────────────────
POLYMARKET_FEE_RATES = {
    "crypto": 0.072,
    "sports": 0.030,
    "finance": 0.040,
    "politics": 0.040,
    "economics": 0.050,
    "culture": 0.050,
    "entertainment": 0.050,
    "weather": 0.050,
    "tech": 0.040,
    "geopolitics": 0.0,
    "world": 0.0,
    "other": 0.050,
}

def calc_polymarket_fee(contracts: float, price: float, category: str) -> float:
    """Polymarket taker fee: C * feeRate * p * (1-p). Makers pay 0."""
    rate = POLYMARKET_FEE_RATES.get(category.lower(), 0.050)
    if rate == 0 or contracts == 0:
        return 0.0
    fee = contracts * rate * price * (1.0 - price)
    return round(fee, 5)

def calc_round_trip_fees(contracts: float, entry_price: float, exit_price: float, category: str) -> dict:
    """Calculate entry + exit taker fees for a complete trade."""
    entry_fee = calc_polymarket_fee(contracts, entry_price, category)
    exit_fee = calc_polymarket_fee(contracts, exit_price, category)
    return {"entry_fee": entry_fee, "exit_fee": exit_fee, "total_fee": round(entry_fee + exit_fee, 5)}

