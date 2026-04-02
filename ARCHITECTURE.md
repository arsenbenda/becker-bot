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
    |-- evaluate_markets()         # For each eligible:
    |   |-- estimate_probability()   # smart_estimator: Layer 1/2/3
    |   |-- compute_ev()             # EV = P_true*(1-P_market) - (1-P_true)*P_market
    |   |-- kelly_size()             # Kelly fraction * bankroll, cap 6%
    |   +-- apply_filters()          # Min edge 2pp, min EV $0.02
    |-- execute_trades()           # Record positions, deduct bankroll
    |-- reevaluate_positions()     # Check edge thinning, trailing stops
    |   |-- if edge < threshold 3x --> TRAILING STOP (close)
    |   |-- if price moved >3pp    --> Bayesian re-estimation
    |   +-- spread alerts for correlated positions
    |-- run_learning_cycle()       # Calibrate, adapt, remember
    +-- save_state()               # Persist all JSON files

## Position Lifecycle

    SCAN -> ELIGIBLE -> EVALUATED -> OPENED -> MONITORING -> CLOSED
                                                  |
                                                  |-- Market resolves -> P&L
                                                  |-- Edge thins 3x   -> Trailing stop
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

Bell-curved: max at 50c, minimal at extremes. Bot trades mostly 90c+ so fees ~1.5%.

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
- Layer 1 dominance: 94/96 evaluations use paid AI calls
- No real-time prices: positions valued at entry until resolution
- Scan history unbounded: bot_state.json grows (cap at 200 in Phase 5.6)
- Single-threaded scan: sequential evaluation
