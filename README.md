# Becker Bot v4.1 — Polymarket Paper-Trading Bot

Autonomous prediction-market trading bot targeting Polymarket. Currently in **paper-trading mode** validating edge before live deployment. Named after the Becker study (72.1M trades analysis of prediction market inefficiencies).

## Quick Start

SSH into the VPS, then:

    systemctl status becker-bot
    tail -50 /opt/becker-bot/becker_bot.log
    systemctl status becker-dashboard   # dashboard at http://<VPS_IP>:8501
    systemctl restart becker-bot        # restart bot
    systemctl restart becker-dashboard  # restart dashboard

## Current Performance (as of 2026-04-02)

| Metric | Value |
|---|---|
| Mode | Paper Trading |
| Scan count | 1,045+ |
| Open positions | 60/60 (max capacity) |
| Closed trades | 43 |
| Win rate | 95.3% (41W / 2L) |
| Gross P&L | +$388.32 |
| Net P&L (after fees) | +$382.53 |
| Total fees | $5.79 |
| Fee drag | 1.49% |
| Starting bankroll | $500.00 |
| Current total value | $1,115.59 (+123.1%) |
| Profit factor | 17.13 |
| Max drawdown | 3.7% |
| Expectancy per trade | +$9.04 (net) |
| API cost | ~$0.69/day |
| Categories | geopolitics, sports, crypto, politics, entertainment |

## How It Works

The bot runs a continuous scan loop every ~300 seconds:

1. **Fetch** — pulls active markets from Polymarket Gamma API (binary, open, volume > threshold).
2. **Filter** — eligibility rules: min volume, valid price range (5c-95c), not already held, not avoided category.
3. **Estimate** — 3-layer probability engine produces a true probability for each market.
4. **Evaluate** — computes Expected Value (EV) and Kelly criterion sizing. Min edge 2pp, min EV $0.02.
5. **Execute** — paper-trades qualifying markets. Records entry price, contracts, cost, fees. Max 60 concurrent positions, max 6% bankroll per bet.
6. **Re-evaluate** — checks open positions for edge thinning. 3 consecutive scans below threshold triggers trailing-stop exit.
7. **Learn** — self-learner calibrates accuracy per category, adjusts risk, remembers prices.

## 3-Layer Estimation Engine (smart_estimator.py)

**Layer 1 - AI:** Perplexity Sonar + GPT-4o mini. Costs ~$0.005/call. Used for 94/96 markets. Will retire when Layer 2 outperforms.

**Layer 2 - Quantitative (free):** CLOB orderbook midpoint, price momentum, volume profile, learner corrections. Used for 2/96 markets.

**Layer 3 - Becker heuristic (free):** Category base rates from 72.1M-trade study. Fallback, not yet triggered.

## Fee Model (Phase 0.12)

Exact Polymarket taker fee formula: fee = contracts x feeRate x price x (1 - price)

| Category | Fee Rate | Peak (50c) | At 95c |
|---|---|---|---|
| Crypto | 0.072 | 1.80% | 0.34% |
| Economics | 0.050 | 1.50% | 0.24% |
| Culture | 0.050 | 1.25% | 0.24% |
| Weather | 0.050 | 1.25% | 0.24% |
| Finance | 0.040 | 1.00% | 0.19% |
| Politics | 0.040 | 1.00% | 0.19% |
| Tech | 0.040 | 1.00% | 0.19% |
| Sports | 0.030 | 0.75% | 0.14% |
| **Geopolitics** | **0.000** | **0%** | **0%** |

## Self-Learner (self_learner.py)

**Level 1 - Calibration:** Tracks predicted vs actual per category. After 20+ trades, applies corrections.

**Level 2 - Adaptive risk:** Adjusts Kelly fraction (started 25%, now 40%) based on rolling performance.

**Level 3 - Market memory:** Remembers 96 markets. Prevents re-entry at worse prices.

## Safety Systems

- Duplicate position guard
- 5% daily drawdown breaker
- Trailing-stop thinning (3-scan exit)
- Cross-market spread alerts (>0.3 spread)
- Max 60 concurrent positions
- Max 6% bankroll per position
- Category auto-block (<40% win rate over 20+ trades)
- Bayesian re-estimation on >3pp price moves

## File Structure

    /opt/becker-bot/
    +-- becker_bot_v4.py       # Main bot engine (scan loop, trading, positions)
    +-- dashboard.py            # Streamlit dashboard (Radar, Risk, Score Card)
    +-- shared_state.py         # Config, paths, fee calculations, I/O helpers
    +-- smart_estimator.py      # 3-layer probability estimation engine
    +-- self_learner.py         # Calibration, adaptive risk, market memory
    +-- api_caps.py             # API rate limiting and daily cap tracking
    +-- positions.json          # All positions (open + closed) with full trade data
    +-- bot_state.json          # Runtime state (bankroll, scans, layers, history)
    +-- learner_state.json      # Learner calibration data and market memory
    +-- trades.json             # Append-only trade log (entries + exits)
    +-- api_usage.json          # API call tracking for cost monitoring
    +-- cache/                  # Per-market JSON cache (Gamma API responses)
    +-- .env                    # API keys — NOT in git
    +-- venv/                   # Python 3.11 virtual env — NOT in git

## Key Data Schemas

### Position Object (positions.json)

    market_id, question, side, entry_price, contracts, cost,
    estimated_prob, category, ev, kelly_pct, maker_score, vol_scalar,
    estimator_source, estimator_confidence, opened_at,
    yes_token_id, no_token_id, status, edge_thin_count,
    entry_fee, exit_fee, total_fees, close_price, pnl, net_pnl, closed_at

### Bot State (bot_state.json)

    scan_count, bankroll, open_positions, total_trades, winning_trades,
    realized_pnl, layer_stats, learner, scan_history[]

## Environment Variables (.env)

    PERPLEXITY_API_KEY=pplx-xxx     # Layer 1 AI estimator
    OPENAI_API_KEY=sk-xxx           # Layer 1 fallback

No blockchain keys yet (paper trading). Phase 2 adds CLOB + wallet keys.

## Systemd Services

    # /etc/systemd/system/becker-bot.service
    WorkingDirectory=/opt/becker-bot
    ExecStart=/opt/becker-bot/venv/bin/python3 becker_bot_v4.py

    # /etc/systemd/system/becker-dashboard.service
    WorkingDirectory=/opt/becker-bot
    ExecStart=/opt/becker-bot/venv/bin/streamlit run dashboard.py --server.port 8501

## Upgrade Roadmap

See [ROADMAP.md](ROADMAP.md) for full phased plan (Phases 0-5).

## Development Workflow

1. All code on VPS at /opt/becker-bot/
2. After changes: git add -A && git commit -m "Phase X.Y: desc" && git push
3. New sessions: share repo URL + latest log for context continuity.

## LLM Context Block

When starting a new AI development session, paste:

    Project: Becker Bot v4.1 — Polymarket paper-trading bot
    Repo: https://github.com/arsenbenda/becker-bot (private)
    VPS: /opt/becker-bot, systemd services: becker-bot, becker-dashboard
    Stack: Python 3.11, Streamlit, systemd, Gamma API, Perplexity/OpenAI APIs
    Key files: becker_bot_v4.py, dashboard.py, shared_state.py, smart_estimator.py, self_learner.py
    Data: positions.json, bot_state.json, learner_state.json, trades.json
    Status: Phase 0 complete, Phase 1 pending (gate at 43/50 trades)
    Read README.md, ARCHITECTURE.md, ROADMAP.md, CHANGELOG.md for full context.
    Latest log: tail -30 /opt/becker-bot/becker_bot.log
