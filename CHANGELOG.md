# Changelog — Becker Bot

## v4.2.0 — Price-Tier Filter + Longshot Cleanup (2026-04-03)

### Added
- Price-tier filter based on Becker 72.1M trade study (longshot bias protection)
  - Sub-15c: blocked entirely (YES at 1c has -41% EV, YES at 5c has -16% EV)
  - 15-30c: caution zone (requires confidence >0.6 AND edge >10pp)
  - 30-80c: unrestricted (minimal structural bias, bot's sweet spot)
  - 80-95c: half-Kelly sizing (steamroller risk reduction)
- New cluster keywords: dem_2028_primary, rep_2028_primary, fifa_wc_2026, us_presidential_2028
- Circuit breaker now excludes longshot_filter exits from daily loss calculation

### Impact
- 50 sub-15c YES positions force-closed (cost: $-21.71 P&L, freed $758.81 capital)
- Bankroll recovered from $118.55 to $878.11
- First scan after deployment: 191 markets parsed, PRICE FILTER blocked dozens of longshots
- Bot correctly placed trades only above 15c (Cooper Flagg 25c, GPT-6 83c, Claude 5, etc.)

### Context
- Becker study: takers buying YES at 1-10c win only 0.43-4.18% vs implied 1-10%
- NO contracts at 1c return +23% EV vs YES at -41% — 64pp gap
- Bot was acting as textbook losing taker: buying YES longshots with inflated AI estimates
- 87% of Polymarket traders lose money; this filter aligns bot with structural winners

## v4.1.9 — AI Prompt Overhaul + Circuit Breaker Fix (2026-04-02)

### Changed
- GPT-4o-mini prompt: anti-hedging rules, extreme probabilities for supernatural/tournament/political events
- Perplexity prompt: hard data requests per category
- Circuit breaker excludes cluster_prune exits
- Prune separation: close_reason tagging, WR/learner/dashboard exclude prunes
- CLI win-rate excludes prunes, shows "+Xp" suffix

## v4.1.8 — Hybrid Exit System (2026-04-02)

### Changed
- Tier A (<50c): hold-to-resolution, 8-scan trailing, 48h stale exit
- Tier B (50-84c): active trailing, 5 scans
- Tier C (>=85c): tight trailing, 3 scans
- Hard stop-loss at -30% of position cost

## v4.1.7 — Cluster Pruning (2026-04-02)

### Added
- Force-exit weakest positions when cluster exceeds 3-position cap
- 17 over-exposed positions closed (GTA 7->3, NBA 8->3, NHL 8->3)

## v4.1.6 — Correlation Filter (2026-04-02)

### Added
- 15 keyword clusters, max 3 positions per cluster, 15% bankroll cap

## v4.1.5 — Sanity Filter + Bayesian Persistence (2026-04-02)

### Fixed
- Learner overrides sanity filter when n>=15 and conf>=0.4
- Bayesian estimates persist across scans

## v4.1.4 — Category Performance Panel (2026-04-02)
## v4.1.3 — Momentum Z-Scores (2026-04-02)
## v4.1.2 — Category Auto-Block (2026-04-02)
## v4.1.1 — Live Unrealised P&L (2026-04-02)
## v4.1 — Phase 0 Complete (2026-04-01)
## v4.0 — Initial Deployment (2026-03-28)
## v3.0 — Legacy (deprecated)
