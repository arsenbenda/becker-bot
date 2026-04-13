# Becker Bot v4.3.1a — Polymarket Paper-Trading Bot

Autonomous prediction-market trading bot targeting Polymarket. Currently in **paper-trading mode** validating edge before live deployment. Named after the Becker study (72.1M trades analysis of prediction market inefficiencies).

## Quick Start

SSH into the VPS, then:

    systemctl status becker-bot
    tail -50 /opt/becker-bot/becker_bot.log
    systemctl status becker-dashboard   # dashboard at http://<VPS_IP>:8501
    systemctl restart becker-bot        # restart bot
    systemctl restart becker-dashboard  # restart dashboard

## Current Performance (as of 2026-04-07, v4.3.1a + P12b)

| Metric | Value |
| --- | --- |
| Mode | Paper Trading |
| Open positions | 19/60 |
| Closed trades | 99 (excl. 34 Masters deviation_cap_bug) |
| Win rate (overall) | 66.7% |
| Win rate (resolved) | 85% (28/33) |
| Net P&L (after fees) | +$385.79 |
| Gross P&L | +$410.94 |
| Total fees | ~$26.16 |
| Bankroll | $500.00 (re-seeded post-Masters) |
| Total value | ~$675 |
| API cost | ~$0.69/day |
| Kelly fraction | 0.10 (adaptive) |
| Brier score | Bot 0.019, Market 0.006 (n=33) |
| Tier B WR | 82% (+$117.58) |
| Tier C WR | 97% (+$421.52) |
| Active patches | P11 (Masters fixes) + P12 (adaptive edge) + P12b (fee-aware Kelly) + P13 (layer routing + default block) |
| Categories | geopolitics, sports, crypto, politics, entertainment |

## How It Works

The bot runs a continuous scan loop every ~180s (300s at full capacity):

1. **Fetch** -- active markets from Polymarket Gamma API (binary, open, volume > threshold).
2. **Filter** -- min volume, valid price range, not already held, not avoided category, cluster cap (max 3 per cluster, 15% bankroll per cluster).
3. **Estimate** -- 3-layer probability engine with anti-hedging AI prompts (v4.1.9).
4. **Evaluate** -- Expected Value (EV) and Kelly criterion sizing. Min edge 2pp, min EV $0.02.
5. **Execute** -- paper-trades qualifying markets. Max 60 concurrent positions, max 6% bankroll per bet.
6. **Re-evaluate** -- hybrid exit system checks open positions with tier-aware logic.
7. **Learn** -- self-learner calibrates accuracy per category, adjusts risk, remembers prices.

## 3-Layer Estimation Engine (smart_estimator.py)

**Layer 1 - AI (v4.1.9):** Perplexity Sonar searches for hard data (odds, polls, prices, rankings). GPT-4o-mini converts research into calibrated probability with anti-hedging rules: supernatural events = 0.01-0.02, tournament longshots = real odds, no 0.50 default. Costs ~$0.005/call. **P13b: Retired for sports and politics** (46.4% / 38.5% WR). Active for crypto (78.6% WR), geopolitics, entertainment, tech.

**Layer 2 - Quantitative (free, primary for sports/politics):** CLOB orderbook midpoint, momentum z-scores (7/14/30-day windows), volume profile, learner corrections. **P13b: Now primary estimator for sports and politics** (100% WR, n=15). Fallback for other categories when L1 hits API cap.

**Layer 3 - Becker heuristic (free):** Category base rates from 72.1M-trade study. Fallback when both Layer 1 and 2 are unavailable.


## Smart Categorizer (P13d)

Two-stage market classification:

1. **Keywords (free, instant):** Pattern-matching against 10 category keyword lists. Handles ~95% of markets.
2. **LLM fallback (GPT-4o-mini, ~$0.001/call):** Classifies markets that keywords miss. Eliminates `default` category leaks.

Markets that fail both stages are blocked at the entry gate (P13a). This prevents trades from bypassing category-specific edge thresholds, fee models, and learner corrections.

## Hybrid Exit System (v4.1.8)

Replaced uniform 3-scan trailing stop with tier-aware exits:

**Tier A (entry < 50c):** Hold-to-resolution bias. 8 consecutive thin scans required for trailing stop. Exit only after 48h with collapsed edge. Covers 90% of positions (avg entry 17c).

**Tier B (entry 50-84c):** Active trailing stop, 6 consecutive thin scans.

**Tier C (entry >= 85c):** Tight trailing stop, 3 consecutive thin scans.

**Hard stop-loss:** -30% of position cost triggers immediate exit on all tiers.

## Cluster Correlation Filter (v4.1.6)

Prevents concentrated exposure across correlated markets:

- 15 keyword-based cluster groups (russia_ukraine, bitcoin_crypto, nhl_hockey, nba_basketball, gta_vi, etc.)
- Max 3 positions per cluster
- Max 15% of bankroll per cluster
- Entry gate blocks new trades that would breach caps
- Pruning engine force-exits weakest positions in over-exposed clusters

## Fee Model

Exact Polymarket taker fee formula: fee = contracts x feeRate x price x (1 - price)

| Category | Fee Rate | Peak (50c) | At 95c |
|----------|----------|------------|--------|
| Crypto | 0.072 | 1.80% | 0.34% |
| Economics | 0.050 | 1.50% | 0.24% |
| Sports | 0.030 | 0.75% | 0.14% |
| **Geopolitics** | **0.000** | **0%** | **0%** |

## Self-Learner (self_learner.py)

**Level 1 - Calibration:** Tracks predicted vs actual per category. After 20+ trades, applies corrections. Excludes cluster prunes from calculations.

**Level 2 - Adaptive risk:** Adjusts Kelly fraction based on rolling 50-trade window. Currently at 15% (absolute tiers).

**Level 3 - Market memory:** Remembers 96+ markets. Prevents re-entry at worse prices.

## Safety Systems

- Duplicate position guard
- 5% daily drawdown circuit breaker (excludes prune rebalancing)
- Hybrid tier-aware trailing stop (replaces uniform 3-scan)
- Hard stop-loss at -30% position cost
- Cluster correlation filter (max 3 per cluster, 15% bankroll)
- Cross-market spread alerts (>0.3 spread)
- Max 60 concurrent positions, max 6% bankroll per position
- Category auto-block (<40% win rate over 20+ trades)
- Bayesian re-estimation on >3pp price moves (persisted across scans)
- Sanity filter with learner override (n>=15, confidence>=0.4)

## Dashboard (Streamlit)

Available at http://<VPS_IP>:8501 with pages:

- **Dashboard** -- equity curve (hybrid: historical trades + live mark-to-market), bankroll, deployed, unrealised P&L, capacity/deployed/health gauges, recent activity
- **Positions** -- all open positions with current price, unrealised P&L, entry details
- **Trades** -- full trade log distinguishing OPEN vs EXIT/PRUNE with P&L and reasons
- **Risk Monitor** -- category exposure, P&L timeline, risk metrics, category performance panel (v4.1.4)
- **Settings** -- bot configuration
- **Logs** -- live log viewer

## File Structure

    /opt/becker-bot/
    |-- becker_bot_v4.py       # Main bot engine (scan loop, trading, positions)
    |-- dashboard.py            # Streamlit dashboard
    |-- shared_state.py         # Config, paths, fee calculations, I/O helpers
    |-- smart_estimator.py      # 3-layer probability estimation engine
    |-- self_learner.py         # Calibration, adaptive risk, market memory
    |-- api_caps.py             # API rate limiting and daily cap tracking
    |-- positions.json          # All positions (open + closed) with full trade data
    |-- bot_state.json          # Runtime state (bankroll, scans, layers, history)
    |-- learner_state.json      # Learner calibration data and market memory
|-- calibrator.py           # Brier-based calibration corrections (sole correction source)
|-- backtest_data.db        # SQLite: 11.4k resolved markets for backtesting
    |-- trades.json             # Append-only trade log (entries + exits)
    |-- api_usage.json          # API call tracking for cost monitoring
    |-- cache/                  # Per-market probability cache (cleared on prompt changes)
    |-- .env                    # API keys -- NOT in git
    |-- venv/                   # Python 3.11 virtual env -- NOT in git

## Key Data Schemas

### Position Object (positions.json)

    market_id, question, side, entry_price, contracts, cost,
    estimated_prob, category, ev, kelly_pct, maker_score, vol_scalar,
    estimator_source, estimator_confidence, opened_at,
    yes_token_id, no_token_id, status, edge_thin_count,
    entry_fee, exit_fee, total_fees, close_price, pnl, net_pnl, closed_at,
    close_reason, current_price, unrealised_pnl, price_updated_at

## Environment Variables (.env)

    PERPLEXITY_API_KEY=pplx-xxx     # Layer 1 AI estimator
    OPENAI_API_KEY=sk-xxx           # Layer 1 probability extraction

No blockchain keys yet (paper trading). Phase 2 adds CLOB + wallet keys.

## Systemd Services

    # /etc/systemd/system/becker-bot.service
    WorkingDirectory=/opt/becker-bot
    ExecStart=/opt/becker-bot/venv/bin/python3 becker_bot_v4.py

    # /etc/systemd/system/becker-dashboard.service
    WorkingDirectory=/opt/becker-bot
    ExecStart=/opt/becker-bot/venv/bin/streamlit run dashboard.py --server.port 8501

## Design Decisions (see CLAUDE.md)

- **Unified scoring system** (post-gate): all signals feed one composite score, no standalone hacks
- **Hard design rule**: every new data source must integrate into unified scorer with learnable weights
- **AI anti-hedging rules**: GPT prompt forces extreme probabilities when warranted (v4.1.9)
- **Prune separation**: cluster prunes tracked separately from real wins/losses in all metrics

## Upgrade Roadmap

See [ROADMAP.md](ROADMAP.md) for full phased plan (Phases 0-5).

## Development Workflow

1. All code on VPS at /opt/becker-bot/
2. After changes: git add -A && git commit -m "Phase X.Y: desc" && git push
3. New sessions: share repo URL + latest log for context continuity.

## LLM Context Block

When starting a new AI development session, paste:

    Project: Becker Bot v4.3 -- Polymarket paper-trading bot
    Repo: https://github.com/arsenbenda/becker-bot (public)
    VPS: /opt/becker-bot, systemd services: becker-bot, becker-dashboard
    Stack: Python 3.11, Streamlit, systemd, Gamma API, Perplexity/OpenAI APIs
    Key files: becker_bot_v4.py, dashboard.py, shared_state.py, smart_estimator.py, self_learner.py
    Data: positions.json, bot_state.json, learner_state.json, trades.json
    Status: v4.3.0, 164 closed trades (85% resolved WR), bankroll $755, P&L +$279
    Read CLAUDE.md, README.md, ARCHITECTURE.md, ROADMAP.md, CHANGELOG.md
    Latest log: tail -30 /opt/becker-bot/becker_bot.log
