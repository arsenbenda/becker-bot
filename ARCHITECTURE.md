# Architecture — Becker Bot v4.1

## System Overview

    +-----------------------------------------------------+
    |                    VPS (Coolify)                     |
    |                                                     |
    |  becker-bot (systemd)  ----->  positions.json       |
    |  scan loop ~300s       ----->  bot_state.json       |
    |       |                ----->  trades.json          |
    |       |                ----->  learner_state.json   |
    |       v                           |                 |
    |  Gamma API                        | reads           |
    |  Perplexity API                   v                 |
    |  OpenAI API             becker-dashboard (Streamlit)|
    |                         port 8501                   |
    +-----------------------------------------------------+

## Scan Loop (becker_bot_v4.py)

    scan()
    |-- fetch_markets()            # Gamma API: binary, open, volume > min
    |-- filter_eligible()          # Price range, not held, not avoided
    |-- evaluate()                   # Full decision pipeline
    |   |-- AI Estimation (v4.1.9)
    |   |   |-- Perplexity Sonar: web search for hard data (odds, polls, prices)
    |   |   |-- GPT-4o-mini: calibrated probability with anti-hedging rules
    |   |   |-- Rules: supernatural=0.01, tournaments=real odds, no 0.50 default
    |   |   |-- Cache: per-market in /opt/becker-bot/cache/
    |   |-- Learner corrections, sanity filter, edge/EV calc, Kelly sizing
    |-- reevaluate_positions()     # Hybrid exit system (v4.1.8)
    |   |-- Hard stop-loss (-30% of position cost)
    |   |-- Tier A (<50c entry): Hold-to-resolution, 8-scan trailing, 48h stale exit
    |   |-- Tier B (50-84c entry): Active trailing, 5-scan threshold
    |   |-- Tier C (>=85c entry): Tight trailing, 3-scan threshold
    |   |-- Cluster over-exposure pruning (max 3 per cluster, 15% bankroll)

    |   |-- if price moved >3pp    --> Bayesian re-estimation
    |   +-- spread alerts for correlated positions
    |-- run_learning_cycle()       # Calibrate, adapt, remember
    +-- save_state()               # Persist all JSON files

## Position Lifecycle

    SCAN -> ELIGIBLE -> EVALUATED -> OPENED -> MONITORING -> CLOSED
                                                  |
                                                  |-- Market resolves -> P&L
                                                  |-- Hybrid exit     -> Tier A/B/C trailing or hard stop
                                                  +-- Drawdown breaker -> Halt new trades

## Estimation Pipeline (smart_estimator.py)

    estimate_probability(question, category, market_data)
    |
    |-- Layer 1: AI (if within daily cap)
    |   |-- Perplexity Sonar (primary)
    |   |-- GPT-4o mini (fallback)
    |   +-- Returns: probability, confidence, reasoning
    |
    |-- Layer 2: Quantitative (if L1 unavailable)
    |   |-- CLOB midpoint price
    |   |-- Price momentum (7/14/30 day)
    |   +-- Learner correction per category
    |
    +-- Layer 3: Becker heuristic (last resort)
        |-- Category base rate from 72.1M trade study
        +-- Known inefficiency margins

## Fee Calculation (shared_state.py)

    POLYMARKET_FEE_RATES = {
        crypto: 0.072, sports: 0.030, finance: 0.040,
        politics: 0.040, economics: 0.050, culture: 0.050,
        weather: 0.050, tech: 0.040, geopolitics: 0.0,
        entertainment: 0.050, other: 0.050
    }
    fee = contracts * rate * price * (1 - price)

Bell-curved: max at 50c, minimal at extremes. Bot trades mostly <50c so fees are moderate.

## Self-Learner (self_learner.py)

    run_learning_cycle(positions, bot_state)
    |-- Level 1: Calibration (predicted vs actual per category)
    |-- Level 2: Adaptive Risk (Kelly adjustment, drawdown tracking)
    +-- Level 3: Market Memory (96 markets remembered, block worse re-entry)

## Dashboard Layout (dashboard.py)

    +-----------------------------------------------------------+
    | P&L (net) | Win Rate | Capacity | Edge | Layers           |
    +-----------------------------------------------------------+
    | MARKET RADAR                                               |
    | Position Health | Recent Closes | Correlation Clusters     |
    +-----------------------------------------------------------+
    | RISK MONITOR                                               |
    | Category Exposure | P&L Timeline | Risk Metrics            |
    +-----------------------------------------------------------+
    | SCORE CARD                                                 |
    | Expectancy & Edge | Risk Profile | Robustness              |
    +-----------------------------------------------------------+
    | OPEN POSITIONS (table)                                     |
    +-----------------------------------------------------------+
    | CLOSED TRADES (table)                                      |
    +-----------------------------------------------------------+
    | RECENT ACTIVITY                                            |
    +-----------------------------------------------------------+

Dashboard reads JSON files directly (no DB, no API between bot and dashboard).

## Known Limitations

- Paper trading only: assumes perfect fills at displayed prices
- No slippage model: real execution faces 0.5-2% slippage
- Layer 1 dominance: ~95% of evaluations use paid AI calls (Layer 2 activates at API cap)
- Positions now priced via CLOB mid-price every scan (Phase 1.4)
- Scan history unbounded: bot_state.json grows (cap at 200 in Phase 5.6)
- Single-threaded scan: sequential evaluation
