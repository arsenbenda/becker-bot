"""
API Usage Caps — prevents runaway spending.
Default: 200 calls/day, $2.00/day max.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

CAP_FILE = Path("/opt/becker-bot/api_usage.json")

MAX_CALLS_PER_DAY = 200
MAX_COST_PER_DAY = 2.00

COST_PERPLEXITY = 0.005
COST_OPENAI_MINI = 0.0003

def _today():
    return str(datetime.now(timezone.utc).date())

def load_usage():
    try:
        data = json.loads(CAP_FILE.read_text())
        if data.get("date") != _today():
            return {"date": _today(), "perplexity": 0, "openai": 0, "cost_usd": 0.0}
        return data
    except:
        return {"date": _today(), "perplexity": 0, "openai": 0, "cost_usd": 0.0}

def save_usage(u):
    CAP_FILE.write_text(json.dumps(u, indent=2))

def within_daily_cap():
    u = load_usage()
    return u["perplexity"] < MAX_CALLS_PER_DAY and u["cost_usd"] < MAX_COST_PER_DAY

def record_call(provider="perplexity"):
    u = load_usage()
    u[provider] = u.get(provider, 0) + 1
    if provider == "perplexity":
        u["cost_usd"] += COST_PERPLEXITY
    else:
        u["cost_usd"] += COST_OPENAI_MINI
    save_usage(u)
    return u

def remaining():
    u = load_usage()
    return {
        "calls_used": u["perplexity"],
        "calls_left": max(MAX_CALLS_PER_DAY - u["perplexity"], 0),
        "cost_used": round(u["cost_usd"], 4),
        "budget_left": round(max(MAX_COST_PER_DAY - u["cost_usd"], 0), 4),
    }

if __name__ == "__main__":
    print(f"Cap: {MAX_CALLS_PER_DAY} calls/day, ${MAX_COST_PER_DAY}/day")
    print(f"Today: {remaining()}")
