"""
Backtest Data Collector — Pull resolved Polymarket markets + CLOB history
Stores in SQLite for fast backtesting queries.
"""
import json
import time
import sqlite3
import requests
from datetime import datetime
from pathlib import Path

DB_PATH = Path("/opt/becker-bot/backtest_data.db")
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"

# Rate limiting
GAMMA_DELAY = 0.4
CLOB_DELAY = 0.3


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS markets (
            market_id TEXT PRIMARY KEY,
            question TEXT,
            event_title TEXT,
            category TEXT,
            end_date TEXT,
            outcome_yes_price TEXT,
            outcome_no_price TEXT,
            clob_yes_token TEXT,
            clob_no_token TEXT,
            volume REAL,
            liquidity REAL,
            resolved_to TEXT,
            tags TEXT,
            collected_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            market_id TEXT,
            token_id TEXT,
            timestamp REAL,
            price REAL,
            PRIMARY KEY (market_id, token_id, timestamp)
        )
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_markets_end_date ON markets(end_date)
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_markets_category ON markets(category)
    """)
    conn.commit()
    return conn


def infer_category_simple(question, tags_str, event_title):
    """Lightweight category inference for backtesting."""
    text = f"{question} {tags_str} {event_title}".lower()
    rules = [
        ("geopolitics", ["nato", "sanctions", "ceasefire", "treaty", "invasion",
                         "military", "russia", "ukraine", "china", "taiwan",
                         "israel", "palestine", "iran"]),
        ("politics", ["president", "election", "trump", "democrat", "republican",
                       "congress", "senate", "governor", "primary", "presidential"]),
        ("crypto", ["bitcoin", "btc", "eth", "ethereum", "crypto", "solana",
                     "token", "defi", "coin"]),
        ("sports", ["nba", "nfl", "mlb", "nhl", "soccer", "football", "basketball",
                     "tennis", "ufc", "stanley cup", "championship", "premier league",
                     "world cup", "fifa", "mvp", "playoffs"]),
        ("finance", ["stock", "s&p", "nasdaq", "fed ", "interest rate", "gdp",
                      "inflation", "earnings"]),
        ("entertainment", ["oscar", "grammy", "movie", "film", "tv show",
                           "gta", "taylor swift", "celebrity"]),
    ]
    for cat, keywords in rules:
        if any(kw in text for kw in keywords):
            return cat
    return "default"


def determine_resolution(market):
    """Determine if market resolved YES or NO."""
    outcome_prices = market.get("outcomePrices", [])
    if isinstance(outcome_prices, str):
        try:
            outcome_prices = json.loads(outcome_prices)
        except:
            return "unknown"
    if not outcome_prices or len(outcome_prices) < 2:
        return "unknown"
    
    yes_price = float(outcome_prices[0])
    no_price = float(outcome_prices[1])
    
    if yes_price > 0.95:
        return "YES"
    elif no_price > 0.95:
        return "NO"
    else:
        return "unknown"


def collect_markets(conn, max_events=5000):
    """Pull resolved events from Gamma API."""
    c = conn.cursor()
    
    # Check existing count
    c.execute("SELECT COUNT(*) FROM markets")
    existing = c.fetchone()[0]
    print(f"Existing markets in DB: {existing}")
    
    new_count = 0
    skip_count = 0
    
    for offset in range(0, max_events, 100):
        try:
            r = requests.get(f"{GAMMA_API}/events", params={
                'closed': 'true',
                'limit': 100,
                'offset': offset,
                'order': 'endDate',
                'ascending': 'false',
            }, timeout=15)
            
            if r.status_code != 200:
                print(f"  HTTP {r.status_code} at offset {offset}")
                break
            
            events = r.json()
            if not events:
                print(f"  Empty response at offset {offset} — done")
                break
            
            for event in events:
                event_title = event.get("title", "")
                event_tags = []
                for t in event.get("tags", []):
                    if isinstance(t, dict):
                        event_tags.append(t.get("label", ""))
                    elif isinstance(t, str):
                        event_tags.append(t)
                tags_str = ",".join(event_tags)
                
                for m in event.get("markets", []):
                    market_id = m.get("id", m.get("conditionId", ""))
                    if not market_id:
                        continue
                    
                    # Skip if already collected
                    c.execute("SELECT 1 FROM markets WHERE market_id=?", (market_id,))
                    if c.fetchone():
                        skip_count += 1
                        continue
                    
                    question = m.get("question", "")
                    if not question:
                        continue
                    
                    clob_ids = m.get("clobTokenIds", [])
                    if isinstance(clob_ids, str):
                        try:
                            clob_ids = json.loads(clob_ids)
                        except:
                            clob_ids = []
                    
                    outcome_prices = m.get("outcomePrices", [])
                    if isinstance(outcome_prices, str):
                        try:
                            outcome_prices = json.loads(outcome_prices)
                        except:
                            outcome_prices = []
                    
                    yes_price = str(outcome_prices[0]) if len(outcome_prices) > 0 else ""
                    no_price = str(outcome_prices[1]) if len(outcome_prices) > 1 else ""
                    
                    category = infer_category_simple(question, tags_str, event_title)
                    resolution = determine_resolution(m)
                    
                    c.execute("""
                        INSERT OR IGNORE INTO markets 
                        (market_id, question, event_title, category, end_date,
                         outcome_yes_price, outcome_no_price,
                         clob_yes_token, clob_no_token,
                         volume, liquidity, resolved_to, tags, collected_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        market_id, question, event_title, category,
                        m.get("endDate", ""),
                        yes_price, no_price,
                        clob_ids[0] if len(clob_ids) > 0 else "",
                        clob_ids[1] if len(clob_ids) > 1 else "",
                        float(m.get("volume", 0) or 0),
                        float(m.get("liquidity", 0) or 0),
                        resolution, tags_str,
                        datetime.utcnow().isoformat(),
                    ))
                    new_count += 1
            
            conn.commit()
            
            if offset % 500 == 0:
                print(f"  offset={offset}: +{new_count} new, {skip_count} skipped")
            
            time.sleep(GAMMA_DELAY)
            
        except Exception as e:
            print(f"  Error at offset {offset}: {e}")
            time.sleep(2)
    
    conn.commit()
    print(f"\nMarket collection done: +{new_count} new, {skip_count} skipped")
    
    c.execute("SELECT COUNT(*) FROM markets")
    total = c.fetchone()[0]
    print(f"Total markets in DB: {total}")
    return new_count


def collect_price_history(conn, limit=None):
    """Pull CLOB price history for markets that don't have it yet."""
    c = conn.cursor()
    
    # Find markets with CLOB tokens but no price history
    c.execute("""
        SELECT m.market_id, m.clob_yes_token, m.question
        FROM markets m
        WHERE m.clob_yes_token != ''
        AND m.market_id NOT IN (SELECT DISTINCT market_id FROM price_history)
        ORDER BY m.end_date DESC
    """)
    rows = c.fetchall()
    
    total = len(rows)
    if limit:
        rows = rows[:limit]
    
    print(f"Markets needing price history: {total} (processing {len(rows)})")
    
    fetched = 0
    empty = 0
    errors = 0
    
    for i, (market_id, token_id, question) in enumerate(rows):
        try:
            r = requests.get(f"{CLOB_API}/prices-history", params={
                'market': token_id,
                'interval': 'max',
                'fidelity': 60,
            }, timeout=10)
            
            if r.status_code == 200:
                data = r.json()
                hist = data.get('history', data) if isinstance(data, dict) else data
                
                if hist and len(hist) > 0:
                    for point in hist:
                        ts = float(point.get('t', 0))
                        price = float(point.get('p', 0))
                        if ts > 0 and price > 0:
                            c.execute("""
                                INSERT OR IGNORE INTO price_history
                                (market_id, token_id, timestamp, price)
                                VALUES (?, ?, ?, ?)
                            """, (market_id, token_id, ts, price))
                    fetched += 1
                else:
                    empty += 1
            else:
                errors += 1
            
            if (i + 1) % 50 == 0:
                conn.commit()
                print(f"  Progress: {i+1}/{len(rows)} — fetched={fetched}, empty={empty}, errors={errors}")
            
            time.sleep(CLOB_DELAY)
            
        except Exception as e:
            errors += 1
            if errors < 5:
                print(f"  Error for {market_id}: {e}")
            time.sleep(1)
    
    conn.commit()
    print(f"\nPrice history done: fetched={fetched}, empty={empty}, errors={errors}")
    
    c.execute("SELECT COUNT(DISTINCT market_id) FROM price_history")
    total_with = c.fetchone()[0]
    print(f"Total markets with price history: {total_with}")


def summary(conn):
    """Print database summary."""
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM markets")
    total = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM markets WHERE resolved_to IN ('YES', 'NO')")
    resolved = c.fetchone()[0]
    
    c.execute("SELECT COUNT(DISTINCT market_id) FROM price_history")
    with_history = c.fetchone()[0]
    
    c.execute("SELECT category, COUNT(*) FROM markets GROUP BY category ORDER BY COUNT(*) DESC")
    cats = c.fetchall()
    
    c.execute("SELECT MIN(end_date), MAX(end_date) FROM markets WHERE end_date != ''")
    date_range = c.fetchone()
    
    print(f"\n{'='*50}")
    print(f"BACKTEST DATABASE SUMMARY")
    print(f"{'='*50}")
    print(f"Total markets:      {total}")
    print(f"Resolved (YES/NO):  {resolved}")
    print(f"With price history: {with_history}")
    print(f"Date range:         {date_range[0][:10]} to {date_range[1][:10]}")
    print(f"\nCategories:")
    for cat, count in cats:
        print(f"  {cat:20s} {count:>6}")


if __name__ == "__main__":
    import sys
    
    conn = init_db()
    
    if len(sys.argv) > 1 and sys.argv[1] == "summary":
        summary(conn)
    elif len(sys.argv) > 1 and sys.argv[1] == "history":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 500
        collect_price_history(conn, limit=limit)
        summary(conn)
    else:
        print("Phase 1: Collecting resolved markets...")
        collect_markets(conn, max_events=3000)
        print("\nPhase 2: Collecting price history (first 500)...")
        collect_price_history(conn, limit=500)
        summary(conn)
    
    conn.close()
