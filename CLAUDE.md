# CLAUDE.md — AI Assistant Instructions

## Mandatory Workflow
1. Every change: git add -A && git commit -m "desc" && git push
2. After milestones: update CHANGELOG.md
3. Weekly: update README.md performance table
4. Before editing: read file first (cat/sed -n). Never assume from history.
5. After patches: python3 -m py_compile <file>.py
6. After restart: tail -20 /opt/becker-bot/becker_bot.log
7. CLAUDE.md must stay under 200 lines.

## Code Conventions
- /opt/becker-bot/, Python 3.11, venv, 4-space indent
- Services: becker-bot, becker-dashboard (:8501)
- Secrets in .env (never committed), state in JSON files
- Fee: contracts * rate * price * (1 - price)
- Always use /opt/becker-bot/venv/bin/python3 for scripts needing project imports

## Key Gotchas
- Heredocs break with markdown fences — use python3 scripts
- shared_state import is multi-line with parens
- Fee/P&L restored from positions.json, NOT bot_state.json
- Prune (cluster_prune) and longshot (longshot_filter) exits excluded from: WR, learner, circuit breaker, dashboard
- Circuit breaker: close_reason not in ("cluster_prune", "longshot_filter")
- Dashboard: 12-space indent inside column blocks

## Price-Tier Filter (v4.2.0) — Becker Longshot Bias Protection
- Sub-30c: BLOCKED (YES and NO). v4.3.1 raised from 15c. Tier A data: 21% WR, -$93.60.
- 30-50c: Caution zone. Requires confidence >0.70 AND edge >12pp (v4.3.1a).
- 30-80c: Unrestricted. Bot's sweet spot, minimal structural bias.
- 80-95c: Half-Kelly sizing. Steamroller risk.
- Rationale: takers buying YES at 1-10c win 0.43-4.18% vs implied 1-10%.

## Hybrid Exit System (v4.1.8)
- Tier A (<50c): hold-to-resolution, 8-scan trailing, 48h stale exit
- Tier B (50-84c): active trailing, 6 scans
- Tier C (>=85c): tight trailing, 3 scans
- Hard stop-loss: -30% of position cost (all tiers)

## AI Estimation Rules (v4.1.9)
- GPT: supernatural=0.01-0.02, tournaments=real odds, no 0.50 hedging
- Perplexity: hard data (odds, polls, prices) per category
- Cache clear after prompt changes: rm -f /opt/becker-bot/cache/*.json

## Cluster Filter (v4.1.6-1.7, expanded v4.2.2)
- 31 keyword clusters (added: champions_league, europa_league, la_liga, serie_a, epl, epl_relegation, epl_top4, us_midterms_2026, colombia_2026, hungary_politics, ai_models, hyperliquid, james_bond)
- Max 5 per cluster (temp, was 3), max 15% bankroll per cluster
- 100% open position coverage (was 37% with 19 clusters)
- Prune exits tagged close_reason: "cluster_prune"

## Hard Design Rule — No Standalone Tools
Every data source feeds unified scoring system. Composite score per opportunity.
Implementation: gate (50 trades) -> unified scoring (50-100) -> add sources (100+) -> adaptive weights (200+)

## Tool Integration Priorities
1. poly_data (646 stars) — Phase 2.4/4.1: backtesting + ML
2. insider-tracker (63 stars) — Phase 2.3: wallet signals
3. py-clob-client (947 stars) — Phase 2.1: WebSocket streams
Skip: poly-maker (Phase 3+), Polymarket/agents, arb-bot

## L2 Enhancement (TODO — target: 300+ trades)
- Goal: Promote L2 from fallback to parallel signal, enabling L1 reduction/removal
- Current: L2 replaces L1 (fallback chain). Starts from Becker baseline, discards AI estimate.
- Plan: Run L2 alongside L1, blend orderbook/momentum into L1 output (or standalone)
- Signals: orderbook imbalance (±3pp), z-score momentum (±4pp), volume spikes
- Prerequisite: validate L2 alpha with backtest_data.db before going live

## ML Notes (Phase 4)
- Backtest WR (89.6%) likely overfit; live WR (76.1%) is ground truth
- RL (PPO): DEFERRED — needs 10k+ trades, dedicated infra

## Session Startup
Human provides: Project: Becker Bot v4.3.1 / Repo: github.com/arsenbenda/becker-bot
Assistant requests: tail -30 becker_bot.log + position summary one-liner

## Current Status (2026-04-06, v4.3.1a)

- 21 open, ~97 closed (85% resolved WR 28/33, 67% overall), bankroll $873
- Net P&L +$275, total value $1,077 (+115% from $500 seed)
- Kelly 0.10 (adaptive), price floor 30c, caution zone 30-50c (12pp edge + 0.70 conf)
- Cluster cap temporarily 5 (was 3) — testing post-v4.3.1 entry flow
- All filters active: price-tier, cluster (31), hybrid exit, deviation cap, spread gate
- P9: Self-learner diagnostic-only; calibrator.py sole correction source
- Brier: bot=0.019 mkt=0.006. Learner: sports -0.001, crypto +0.057, entertainment -0.198
- Diagnostic logging: EDGE FAIL, EV FAIL added to evaluate() silent zone
- No post-P9/v4.3.1 entries yet — market lacks qualifying opportunities
- Gate: PASSED. Next: unified scoring system

## Key Gotcha — Calibration (v4.3.1)
- Only calibrator.py modifies est_prob (Brier-proper, ±8pp cap). self_learner logs only (LEARNER_DIAG).
