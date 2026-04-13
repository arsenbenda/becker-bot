# Upgrade Roadmap — Becker Bot

## Evaluation Gate (must pass before Phase 2)

| Metric                  | Target               | Current (2026-04-03)     |
|-------------------------|----------------------|--------------------------|
| Closed trades (real)    | >= 50                | 67 (51W / 16L)           |
| Win rate (excl. prunes) | >= 54%               | 76.1%                    |
| Net P&L                 | Positive after fees   | +$244.22                 |
| Profit factor           | > 1.5                | ~4.0                     |
| Max drawdown            | < 20%                | ~14%                     |
| Learner markets         | >= 50                | 130+                     |
| Profitable categories   | >= 3                 | 5                        |
| Score-card confidence   | >= 25%               | ~30%                     |
| Fee-adjusted expectancy | > $0/trade           | +$3.64                   |

**Gate status: PASSED (2026-04-02).** All metrics exceed thresholds.

---

## Phase 0 — Foundation & Safety [COMPLETE]

- [x] Duplicate-position guard
- [x] Dynamic scan intervals (300s full / 180s open-only)
- [x] 5% daily drawdown breaker (excludes prune + longshot_filter exits)
- [x] Bayesian re-estimation on >3pp moves
- [x] Cross-market spread alerts
- [x] Becker edge sanity filter (with learner override when n>=15, conf>=0.4)
- [x] Dashboard, bankroll persistence, fee model, net P&L display

## Phase 1 — Free Intelligence

- [x] 1.1 Momentum z-scores (7/14/30-day via Gamma API)
- [x] 1.2 Correlation filter (max 3 per cluster, <=15% bankroll)
- [x] 1.2b Cluster over-exposure pruning (force-exit weakest when cluster > 3)
- [ ] 1.3 Logical arbitrage scanner (nested market mispricing)
- [x] 1.4 Live unrealised P&L (CLOB mid-price per position)
- [x] 1.5 Category auto-block (<40% win rate over 20+ trades)
- [ ] 1.6 Adaptive scan intervals (120s volatile / 600s calm)
- [x] 1.7 Auto-retire Layer 1 (when L2 outperforms by >2pp MAE) — P13b: L1 retired for sports/politics
- [ ] 1.8 Geopolitics priority mode — DEFERRED to unified scoring system
- [x] 1.9 Category performance dashboard panel
- [ ] 1.10 Install pmxt library
- [ ] 1.11 Tremor.live webhook
- [x] 1.12 Hybrid exit system (3 tiers + hard stop-loss at -30%)
- [x] 1.13 AI prompt overhaul (anti-hedging rules, extreme probabilities)
- [x] 1.14 Prune separation (close_reason tagging, WR/learner exclude prunes)
- [x] 1.15 CLI win-rate fix (excludes prunes, shows +Xp suffix)
- [x] 1.16 Circuit breaker excludes prune + longshot_filter exits
- [x] 1.17 Dashboard trade log fix (OPEN vs EXIT/PRUNE distinction)
- [x] 1.18 Dashboard Score Card formatting fix
- [x] 1.19 Price-tier filter (Becker longshot bias protection)
      - Sub-15c: blocked (YES and NO) — structural negative EV per 72.1M trade study
      - 15-30c: caution zone — requires confidence >0.6 and edge >10pp
      - 30-80c: unrestricted — bot's sweet spot, minimal structural bias
      - 80-95c: half-Kelly — steamroller risk reduction
- [x] 1.20 Cluster keywords expanded (dem_2028, rep_2028, fifa_wc_2026, us_presidential_2028)
- [x] 1.21 Longshot position cleanup (50 sub-15c YES positions force-closed)

**Phase 1 status:** 19/21 complete. Remaining: 1.3, 1.6, 1.10, 1.11 (1.8 deferred).

## Phase 2 — Execution & Data

- [ ] 2.1 py-clob-client (official SDK, WebSocket streams) — 947 stars
- [ ] 2.2 Maker limit orders (zero fees + rebates)
- [ ] 2.3 Insider-tracker (pselamy, 63 stars) + polyterm (32 stars)
- [ ] 2.4 Backtesting framework — poly_data (warproxxx, 646 stars, 86M+ trades)
- [ ] 2.5 Slippage model (reject if slippage >50% of edge)
- [ ] 2.6 Polygon wallet setup
- [ ] 2.7 Options-chain cross-reference
- [ ] 2.8 Self-learning exit thresholds
- [ ] 2.9 Security audit (.env never committed)

## Phase 3 — Advanced Strategies (after 200+ live trades)

- [ ] 3.1 Market-making (poly-maker)
- [ ] 3.2 News-speed triggers (RSS, no LLM)
- [ ] 3.3 Cross-platform arbitrage (pmxt)
- [ ] 3.4 Mean-reversion signals
- [ ] 3.5 15-min crypto binaries — DEPRIORITISED
- [ ] 3.6 Bayesian probability pipeline
- [ ] 3.8 Geopolitics deep mode (NASA FIRMS, OpenSky, USGS, OSINT)

## Phase 4 — ML & Quantitative (after 500+ trades)

- [ ] 4.1 ML model (XGBoost/LightGBM on poly_data, walk-forward validation)
- [ ] 4.2 NLP sentiment (local TF-IDF)
- [ ] 4.3 Adaptive Kelly (rolling 50-trade window)
- [ ] 4.4 Monte Carlo equity curves (10k simulations, 95% CI)
- [ ] 4.5 Portfolio correlation-aware sizing
- [ ] 4.6 Reinforcement learning — DEFERRED INDEFINITELY (needs 10k+ trades)

## Phase 5 — Dashboard & UX

- [ ] 5.1-5.6 TradingView charts, ticker, notifications, RAM optimisation

## Security Checklist

- [x] .env in .gitignore
- [x] Kill switch: systemctl stop becker-bot
- [x] 5% daily loss breaker (excludes prune/longshot exits)
- [ ] Verify .env never in git history
- [ ] Dedicated wallet, pip audit, token limits, key rotation
