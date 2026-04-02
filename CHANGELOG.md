# Changelog — Becker Bot

## v4.1.7 — Phase 1.2b: Cluster Pruning (2026-04-02)

### Added
- Cluster over-exposure pruning in reevaluate_positions()
- Force-exits weakest positions (by unrealised P&L) when cluster exceeds 3-position cap
- Expanded GTA cluster keywords to catch "before GTA" pattern
- CLUSTER PRUNE log messages with per-position and total counts

### Impact
- 17 over-exposed positions force-closed on first run
- Clusters reduced: GTA 7->3, NBA 8->3, NHL 8->3
- Unrealised loss reduced from -$32 to -$10
- Freed 17 slots for better-diversified trades
- Cost: ~$32 realized loss (correlated risk premium)

## v4.1.9 — AI Prompt Overhaul + Circuit Breaker Fix (2026-04-02)

### Changed
- GPT-4o-mini probability prompt: added CRITICAL RULES forcing extreme probabilities
  for supernatural events (0.01-0.02), tournament winners (real odds), political events
  (base rates). Explicitly bans hedging toward 0.50.
- Perplexity research prompt: now requests HARD DATA (rankings, betting odds, polling,
  prices) instead of vague "factual analysis". Asks for specifics per category.
- Circuit breaker: excludes cluster_prune exits from daily loss calculation

### Context
- 53% of Layer 1 positions had estimates in 0.35-0.65 hedging zone
- AI estimated 50% for Jesus Christ returning, 50% for Argentina winning World Cup
- Colombia World Cup: AI said 47%, real probability ~1.7%
- Caused systematic undersizing via Kelly on high-conviction trades
- This was the single biggest performance leak in the system

### Fixed
- Cleared all cached estimates to force re-evaluation with new prompts
- Circuit breaker no longer blocked by prune rebalancing costs

## v4.1.8 — Hybrid Exit System (2026-04-02)

### Changed
- Replaced uniform 3-scan trailing stop with tier-aware hybrid exit system
- Tier A (<50c entry): Hold-to-resolution bias, 8 scans for trailing stop, exit only after 48h with dead edge
- Tier B (50-84c entry): Active trailing, 5 consecutive thin scans required (was 3)
- Tier C (>=85c entry): Original tight trailing, 3 scans
- Added hard stop-loss at -30% of position cost (catches disasters regardless of tier)
- Position age calculated from opened_at timestamp

### Context
- 27 of 32 open positions are Tier A (<50c), avg entry 17.4c
- Old system would exit on 9 min of noise; new Tier A requires 40+ min of sustained edge collapse
- Research: profitable Polymarket bots hold cheap contracts to resolution, not trailing-stop on volatility
- Asymmetry at 17c entry: 5.7x upside vs 1x downside favors holding

### Performance
- Hard stop immediately caught a -36% UK election position
- Tier B correctly held Jesus Christ/GTA VI at 3/5 (old system would have exited at 3/3)

## v4.1.6 — Dashboard: Recent Activity formatting fix (2026-04-02)

### Fixed
- Recent Activity table now distinguishes OPEN and EXIT trades
- OPEN trades show: blue icon, cost, EV, estimator source
- EXIT trades show: green/red icon based on P&L, exit reason, P&L amount
- Previously: EXIT trades showed ? side, $0 cost, no source — confusing

## v4.1.6 — Phase 1.2: Correlation Filter (2026-04-02)

### Added
- Keyword-based cluster detection across 15 cluster groups
- Hard cap: max 3 positions per cluster
- Bankroll cap: max 15% of bankroll deployed per cluster
- Cluster gate runs before API calls (Step 0c in evaluate pipeline)
- CLUSTER CAP and CLUSTER $CAP log messages for rejected trades

### Context
- Russia/Kostyantynivka cluster caused -$36.08 loss (63% of daily losses on 2026-04-02)
- Filter would have blocked the 3rd entry, limiting loss to ~$24

## v4.1.5 — Conflict Fixes: Sanity Filter + Bayesian Persistence (2026-04-02)

### Fixed
- Sanity filter now respects learner corrections when learner has strong data (n>=15, conf>=0.4)
- Previously: learner pushed estimate up, sanity filter pulled it back — directly contradicting each other
- Now: learner wins when it has evidence, sanity filter only applies for low-data categories
- Bayesian re-estimation now persists blended estimate back to position (estimated_prob updated)
- Previously: each scan re-blended from the original stale estimate, never learning from price moves
- Now: estimates evolve scan-over-scan as market prices change

### Notes
- Both fixes activate when bot has open capacity and positions experience >3pp price moves
- Currently at 60/60 — fixes will be visible when slots open and new trades enter
- These are prerequisite fixes for the unified scoring system (post-gate)

## v4.1.4 — Phase 1.9: Category Performance Panel (2026-04-02)

### Added
- Category Performance section on dashboard (between Risk Monitor and Score Card)
- Category P&L bar chart: horizontal bars, green/red by net P&L, sorted by performance
- Category Breakdown table: trades, win rate, net P&L, avg P&L per trade, fees
- Status icons: green (>=60% WR), yellow (>=40%), red (<40%)

### Notes
- Pure dashboard addition — no bot logic changes
- All data computed from closed trades in positions.json
- Updates automatically as new trades close

## v4.1.3 — Phase 1.1: Momentum Z-Scores (2026-04-02)

### Added
- momentum_zscores() function: 7/14/30-day z-scores with composite signal
- Three signal types: zscore_aligned (trend following), zscore_reversion (mean reversion), zscore_mixed
- Trend alignment detection (all windows agree = strong signal)
- Mean-reversion flag (short-term spike + long-term calm)
- Hard cap +/-4pp on z-score adjustments
- Confidence boost: +0.10 for aligned signals, +0.05 for mixed

### Changed
- layer2_estimate() upgraded: z-scores primary, legacy momentum as fallback
- Volume signal now applies to both z-score and fallback paths

### Notes
- Z-scores activate when Layer 2 is used (currently 2/96 markets)
- Will become primary signal when Layer 1 is retired (Phase 1.7)
- Zero additional API cost — uses existing CLOB price history endpoint

## v4.1.2 — Phase 1.5: Category Auto-Block (2026-04-02)

### Changed
- Category auto-block threshold tightened: 5 trades/35% WR -> 20 trades/40% WR
- Log message upgraded to AUTO-BLOCK with explicit criteria display
- Matches roadmap spec: block categories with <40% win rate over 20+ trades

### Notes
- No categories currently blocked (all above 40% WR)
- Safety net activates automatically as trade count grows per category

## v4.1.1 — Phase 1.4: Live Unrealised P&L (2026-04-02)

### Added
- Live CLOB mid-price fetched per open position every scan
- Unrealised P&L computed and persisted to positions.json (current_price, unrealised_pnl, price_updated_at)
- Mark-to-market total_value in scan_record (equity curve reflects real portfolio value)
- Unrealised P&L line in CLI log summary
- Unrealised metric card on dashboard (with priced/total count)
- Curr Price and Unrl P&L columns in Positions table

### Changed
- Total Value now reflects bankroll + deployed + unrealised (was bankroll + deployed)
- scan_history records include unrealised_pnl field

### Performance
- 60/60 positions priced via CLOB on first scan
- Unrealised: -$11.98 (1.6% of deployed — normal for hold period)
- No additional API cost (CLOB price endpoint is free)

## v4.1.1 — Phase 1.4: Live Unrealised P&L (2026-04-02)

### Added
- Live CLOB mid-price fetched per open position every scan
- Unrealised P&L computed and persisted to positions.json (current_price, unrealised_pnl, price_updated_at)
- Mark-to-market total_value in scan_record (equity curve reflects real portfolio value)
- Unrealised P&L line in CLI log summary
- Unrealised metric card on dashboard (with priced/total count)
- Curr Price and Unrl P&L columns in Positions table

### Changed
- Total Value now reflects bankroll + deployed + unrealised (was bankroll + deployed)
- scan_history records include unrealised_pnl field

### Performance
- 60/60 positions priced via CLOB on first scan
- Unrealised: -$11.98 (1.6% of deployed — normal for hold period)
- No additional API cost (CLOB price endpoint is free)

## v4.1 — Phase 0 Complete (2026-04-01)

### Added
- Polymarket fee model (Phase 0.12): category-based taker fees
- Net P&L tracking: entry_fee, exit_fee, total_fees, net_pnl per position
- Dashboard: net P&L primary, gross + fees subtitle
- Market Radar: Position Health, Recent Closes, Correlation Clusters
- Risk Monitor: Category Exposure, P&L Timeline, Risk Metrics
- Score Card: Expectancy, Risk Profile (Sharpe/Sortino/Calmar), Robustness
- Trailing-stop thinning (3-scan exit)
- 5% daily drawdown circuit breaker
- Bayesian re-estimation on >3pp moves
- Cross-market spread alerts
- Becker edge sanity filter
- Duplicate position guard
- Dynamic scan intervals (300s/180s)
- Bankroll persistence and fee restore on restart
- Git repo with documentation

### Fixed
- Dashboard P&L reads from positions.json
- UnboundLocalError in reevaluate_positions
- IndentationError in fee calculation block
- Dashboard metric truncation (vertical layout)
- Import syntax errors in shared_state

### Performance
- 43 closed trades, 95.3% win rate (41W / 2L)
- Gross +$388.32, Net +$382.53, Fees $5.79
- $500 -> $1,115.59 (+123.1%)
- Fee drag: 1.49%

## v4.0 — Initial Deployment (2026-03-28)

### Added
- 3-layer estimation engine
- Paper trading engine
- Self-learner (calibration, adaptive risk, market memory)
- Streamlit dashboard
- Gamma API integration
- Kelly criterion sizing
- API cost tracking

## v3.0 — Legacy (deprecated)

- Single-layer bot (becker_bot.py)
- Basic market scanning
- No fees, no learning, no dashboard panels
