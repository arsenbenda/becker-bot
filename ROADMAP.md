# Upgrade Roadmap — Becker Bot

## Evaluation Gate (must pass before Phase 2)

| Metric | Target | Current (2026-04-02) |
|---|---|---|
| Closed trades | >= 50 | 43 |
| Win rate | >= 54% | 95.3% |
| Net P&L | Positive after fees | +$382.53 |
| Profit factor | > 1.5 | 17.13 |
| Max drawdown | < 20% | 3.7% |
| Learner markets | >= 50 | 96 |
| Profitable categories | >= 3 | 5 |
| Score-card confidence | >= 25% | 21.5% |
| Fee-adjusted expectancy | > $0/trade | +$9.04 |

---

## Phase 0 — Foundation & Safety [COMPLETE]

- [x] Duplicate-position guard
- [x] Dynamic scan intervals (300s full / 180s open-only)
- [x] Trailing-stop thinning (3-scan exit)
- [x] 5% daily drawdown breaker
- [x] Bayesian re-estimation on >3pp moves
- [x] Cross-market spread alerts
- [x] Becker edge sanity filter
- [x] Dashboard reads from positions.json
- [x] Bankroll persistence across restarts
- [x] Counter sync fix
- [x] Market Radar panels
- [x] Risk Monitor panels
- [x] Score Card panels
- [x] Phase 0.12: Polymarket fee model (category-based taker fees)
- [x] Net P&L display (primary), gross + fees subtitle
- [x] Fee data persisted per position, restored on restart

## Phase 1 — Free Intelligence (zero API cost)

- [ ] 1.1 Momentum z-scores (7/14/30-day via Gamma API)
- [ ] 1.2 Correlation filter (max 2 per cluster, <=15% bankroll)
- [ ] 1.3 Logical arbitrage scanner (nested market mispricing)
- [x] 1.4 Live unrealised P&L (CLOB mid-price per position)
- [ ] 1.5 Category auto-block (<40% win rate over 20+ trades)
- [ ] 1.6 Adaptive scan intervals (120s volatile / 600s calm)
- [ ] 1.7 Auto-retire Layer 1 (when L2 outperforms by >2pp MAE)
- [ ] 1.8 Geopolitics priority mode (25% bankroll, zero fees)
- [ ] 1.9 Category performance dashboard panel
- [ ] 1.10 Install pmxt library (Polymarket/Kalshi/Limitless API)
- [ ] 1.11 Tremor.live webhook (anomaly alerts)

## Phase 2 — Execution & Data (new deps, free-tier infra)

- [ ] 2.1 py-clob-client integration (real-time order book)
- [ ] 2.2 Maker limit orders (zero fees + rebates)
- [ ] 2.3 Insider-tracker integration (flag opposing wallets)
- [ ] 2.4 Backtesting framework (pmxt archive + poly_data)
- [ ] 2.5 Slippage model (reject if slippage >50% of edge)
- [ ] 2.6 Polygon wallet setup (USDC + MATIC, free RPC)
- [ ] 2.7 Options-chain cross-reference (CME/CBOE vs Polymarket)
- [ ] 2.8 Self-learning exit thresholds (adaptive trailing-stop)

## Phase 3 — Advanced Strategies (after 200+ live trades)

- [ ] 3.1 Market-making exploration (poly-maker)
- [ ] 3.2 News-speed triggers (RSS keyword, no LLM)
- [ ] 3.3 Cross-platform arbitrage (via pmxt)
- [ ] 3.4 Mean-reversion signals (>10pp without news)
- [ ] 3.5 15-min crypto binaries — DEPRIORITISED (Moltbook: -8.4%)
- [ ] 3.6 Bayesian probability pipeline
- [ ] 3.8 Geopolitics deep mode (majorexploiter study, satellite watchlist)

## Phase 4 — ML & Quantitative (after 500+ trades)

- [ ] 4.1 ML probability model (XGBoost/LightGBM on poly_data)
- [ ] 4.2 NLP sentiment scoring (local TF-IDF)
- [ ] 4.3 Adaptive Kelly recalibration (rolling 50-trade window)
- [ ] 4.4 Monte Carlo equity curves (10k simulations)
- [ ] 4.5 Portfolio correlation-aware sizing

## Phase 5 — Dashboard & UX

- [ ] 5.1 TradingView-style equity curve
- [ ] 5.2 Scrolling ticker tape
- [ ] 5.3 Expandable position cards
- [ ] 5.4 Push/Telegram notifications
- [ ] 5.5 Performance comparison (bot vs benchmarks)
- [ ] 5.6 RAM optimisation (cap history, lazy-load)

## Security Checklist

- [ ] Dedicated wallet only
- [ ] Audit pip dependencies
- [ ] Limit token approvals
- [ ] Start live with $100-300
- [ ] Kill switch: systemctl stop becker-bot
- [ ] 5% daily loss breaker always active
- [ ] Rotate API keys monthly
- [ ] Private keys in .env only
- [ ] Verify GitHub repos (Dec 2025 incident)
