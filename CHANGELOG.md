# Changelog — Becker Bot

## v4.3.1a + P12 (2026-04-07) — Post-Masters Hardening + Session Fixes

### Fixed
- Duplicate log writes: `log()` was writing directly to `becker_bot.log` AND systemd was capturing stdout to the same file via `StandardOutput=append`. Every line appeared twice. Removed manual file write from `log()` — systemd is now sole writer via `StandardOutput=append`.
- Version banner: both runtime log banner and startup print now correctly display `v4.3.1a — PAPER` (was `v4.1`).

### Added
- P12: Adaptive min-edge — Brier-driven per-category edge threshold inserted before `edge_is_real()` in `evaluate()`. Bot-beats-market categories (geopolitics n=9, crypto n=6) get relaxed edge (base−3pp, floor 0.03). Market-beats-bot categories (politics n=5, sports n=9) get tightened edge (base+5pp, cap 0.15). Categories with n<5 fall back to global `MIN_EDGE_POINTS`. Logs `ADAPTIVE EDGE` on every adjustment.
- P12b: Fee-aware Kelly sizing — `kelly_size()` now accepts `category` param and adjusts `cost` by `calculate_taker_fee()` before computing `b = (1−cost)/cost`. True net odds now reflected in sizing. Particularly impactful for near-zero-fee categories (geopolitics, world_events: 0% taker fee) and high-confidence NO trades where fee is minimised.

### Current State (post-session)
- Bankroll $500 (re-seeded post-Masters), Net P&L +$385.79, Gross +$410.94
- 19/60 open, 99 closed (66.7% overall WR, 85% resolved WR 28/33)
- 34 Masters trades excluded as `deviation_cap_bug`
- Active patches: P11 (Masters fixes) + P12 (adaptive edge) + P12b (fee-aware Kelly)

## v4.3.1 (2026-04-06) — Tier A Entry Filter (Option C)

### Changes
- Price floor raised from 15c to 30c (sub-30c blocked entirely)
- Caution zone expanded from 15-30c to 30-50c
- Caution zone now requires 15pp edge (was 10pp) and 0.70 confidence (was 0.60)

### Data Justification
- Sub-30c trades: 4/19 WR=21%, PnL=-$93.60
- 30-50c trades: 5/16 WR=31%, PnL=-$34.06
- Simulated Option C: 56/67 WR=84%, PnL=+$506.32 (delta +$94.88 vs current)

## v4.3.0 NO-Side Integrity Audit + Calibration Fix (2026-04-03)

### Fixed
- P5: Post-calibration direction guard (line ~763) + hard guard before PaperPosition creation (line ~862). Prevents calibration from flipping trade side. Fixed 11.4% of trades entering against bot's own estimate (-$31.12).
- P6: Reevaluation NO-side fix (line ~497). API returns YES price; now flipped to 1-price for NO positions. Unified P&L formula.
- P7: Self-learner NO-side prediction fix (self_learner.py lines ~113, ~148, ~179). All 3 calibration loops now use side_conf = 1.0-est_prob for NO trades. Corrections dropped from +40-80pp to +0.5-9pp.
- P8: Circuit breaker now uses self.bankroll instead of self.cfg["PAPER_BANKROLL"] (was triggering 20% too early).
- P9: Dual calibration fix — self_learner corrections now diagnostic-only (LEARNER_DIAG logs). calibrator.py is sole correction source (Brier-proper, ±8pp cap). Both systems were correcting on same 3 axes with same trade data.
- P10: Win rate display now shows both overall WR and resolved WR (e.g., "68.5% (resolved: 28/33 85%)").

### Analysis
- Issue 5 (Brier gap): Bot Brier 0.019 vs Market 0.006 — 84% of gap from 3 pre-filter longshot YES trades. Not a calculation bug; historical artifact. Price-tier filter prevents recurrence.
- Issue 4 (L2/L3 dead): Working as designed (fallback chain). L2 enhancement deferred to 300+ trades.

### Tuning
- A1: close_reason now tags "resolved" (close_price >0.90 or <0.10) vs "exit". Backfilled 66 historical trades.
- A2: Tier B trailing stop increased from 5→6 consecutive thin scans (was cutting winners too early, 22% WR on trailing stops).

### Impact
- NO-side positions now correctly handled across entire codebase (evaluate, reevaluate, self_learner)
- Single calibration path eliminates double-correction stacking
- Dashboard win rate no longer misleading
- Clean close_reason taxonomy: resolved (33), exit (48), trailing_stop (9), cluster_prune (25), longshot_filter (50)
- Bankroll ~$755, Net P&L +$279, 28/60 open, 165 closed (resolved WR 85%)

## v4.2.2 — Calibration + Robustness Patches (2026-04-03)

### Fixed
- P0: Trailing stop logs now show actual tier limits (A=8, B=5, C=3) instead of hardcoded "3"
- P1: Removed duplicate 28-line mutual-exclusion filter block in evaluate()

### Added
- P3: Cluster keywords expanded 19→31 (champions_league, europa_league, la_liga, serie_a, epl, epl_relegation, epl_top4, ai_models, hyperliquid, us_midterms_2026, colombia_2026, hungary_politics, james_bond, gta_vi)
- P4: Bid-ask spread gate — rejects entry when spread > 50% of edge magnitude
- Backtester v2: data collector (11.4k resolved markets in SQLite), CLOB history backtest, Brier calibration analysis
- Calibrator: Brier-based dynamic calibration runs every scan cycle, computes correction curves by category/layer/price bucket, feeds adjustments into evaluate()

### Analysis
- Layer 3 (Becker bias) alone yields zero tradeable opportunities at any edge threshold
- Layer 1 (AI) is the sole profit engine: 280 L1 calls vs 6 L2, 0 L3
- Brier scores (33 resolved): Bot 0.0190, Market 0.0060 (bot less calibrated but 84.8% WR)
- Geopolitics + crypto: 100% WR on resolved trades
- 10/88 closed trades entered against bot's own estimate (negative-edge bug) — fix pending

### Known Issues
- Negative-edge entry bug: evaluate() allows YES entry when est_prob < entry_price (11.4% of trades, -$31.12 losses)
- 1 suspicious open position (GPT-6 release: YES entry=0.235, est=0.216)
- L1 confidence clustering at 0.80-0.90 provides low discriminative power

### Impact
- 100% cluster coverage (was 37%)
- Misleading trailing-stop logs corrected for learner accuracy
- Dynamic calibration strengthens with each resolved trade
- Bankroll ~$754, Net P&L +$280, 142 trades


## v4.2.1 — AI Calibration + Learner Decontamination (2026-04-03)

### Fixed
- GPT prompt rewritten: calibrated probability scale with explicit tiers (0.01-0.99)
- Anchoring rule: AI must justify >15pp deviation from market price
- Deviation cap: AI estimates clamped to within 30pp of market price
- self_learner.py: longshot_filter exits now excluded from calibration + adaptive risk
- Kelly logic: absolute tiers (0.25/0.15/0.10/0.05) replace relative multipliers
- Kelly recovered from 0.05 (contaminated by longshot exits) to 0.15

### Impact
- AI estimates now grounded: no more 99% spam on sports markets
- Erdogan removal: 0.08 (was ~0.30+), GPT-6 June: 0.20 (was inflated)
- Learner WR corrected from 24% (contaminated) to 60% (real)
- Bot actively trading again with proper position sizing

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
- Tier B (50-84c): active trailing, 6 scans
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
