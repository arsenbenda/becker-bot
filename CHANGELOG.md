# Changelog — Becker Bot

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
