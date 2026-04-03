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
- Sub-15c: BLOCKED (YES and NO). Structural -41% to -16% EV per 72.1M trades.
- 15-30c: Caution zone. Requires confidence >0.6 AND edge >10pp.
- 30-80c: Unrestricted. Bot's sweet spot, minimal structural bias.
- 80-95c: Half-Kelly sizing. Steamroller risk.
- Rationale: takers buying YES at 1-10c win 0.43-4.18% vs implied 1-10%.

## Hybrid Exit System (v4.1.8)
- Tier A (<50c): hold-to-resolution, 8-scan trailing, 48h stale exit
- Tier B (50-84c): active trailing, 5 scans
- Tier C (>=85c): tight trailing, 3 scans
- Hard stop-loss: -30% of position cost (all tiers)

## AI Estimation Rules (v4.1.9)
- GPT: supernatural=0.01-0.02, tournaments=real odds, no 0.50 hedging
- Perplexity: hard data (odds, polls, prices) per category
- Cache clear after prompt changes: rm -f /opt/becker-bot/cache/*.json

## Cluster Filter (v4.1.6-1.7, expanded v4.2.0)
- 19 keyword clusters (includes dem_2028, rep_2028, fifa_wc_2026, us_presidential_2028)
- Max 3 per cluster, max 15% bankroll per cluster
- Prune exits tagged close_reason: "cluster_prune"

## Hard Design Rule — No Standalone Tools
Every data source feeds unified scoring system. Composite score per opportunity.
Implementation: gate (50 trades) -> unified scoring (50-100) -> add sources (100+) -> adaptive weights (200+)

## Tool Integration Priorities
1. poly_data (646 stars) — Phase 2.4/4.1: backtesting + ML
2. insider-tracker (63 stars) — Phase 2.3: wallet signals
3. py-clob-client (947 stars) — Phase 2.1: WebSocket streams
Skip: poly-maker (Phase 3+), Polymarket/agents, arb-bot

## ML Notes (Phase 4)
- Backtest WR (89.6%) likely overfit; live WR (76.1%) is ground truth
- RL (PPO): DEFERRED — needs 10k+ trades, dedicated infra

## Session Startup
Human provides: Project: Becker Bot v4.1 / Repo: github.com/arsenbenda/becker-bot
Assistant requests: tail -30 becker_bot.log + position summary one-liner

## Current Status (2026-04-03, post v4.2.1)

- 42 open (all >15c), 83 real closed (60% WR, PF 1.8), 18 pruned, 50 longshot-filtered
- Bankroll ~$694, Kelly 15%, min edge 10pp
- Price-tier filter, cluster filter, hybrid exit, deviation cap all active
- AI prompt: calibrated probability scale, anchoring rule, 30pp deviation cap
- Learner: decontaminated, absolute Kelly tiers (0.25/0.15/0.10/0.05)
- Gate: PASSED. Next: unified scoring system (50-100 trades)
