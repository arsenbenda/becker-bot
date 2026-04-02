# Changelog — Becker Bot

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
