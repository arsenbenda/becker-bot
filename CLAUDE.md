# CLAUDE.md — AI Assistant Instructions

This file is read by AI assistants (Claude, etc.) at the start of development sessions.
It contains project conventions, rules, and habits that must be followed.

## Mandatory Workflow

1. **Every successful change** must end with a git commit and push:
   git add -A && git commit -m "Phase X.Y: description" && git push

2. **After completing a phase milestone**, update CHANGELOG.md with what was added/fixed.

3. **Weekly** (or when stats change significantly), update the performance table in README.md.

4. **Before editing any file**, read it first (cat or sed -n) to confirm current state.
   Never assume file contents from conversation history alone.

5. **After every patch**, run a syntax check before restarting:
   python3 -m py_compile <file>.py

6. **After restarting a service**, always verify with log output:
   systemctl restart becker-bot && sleep 10 && tail -20 /opt/becker-bot/becker_bot.log

## Code Conventions

- All bot code in /opt/becker-bot/
- Python 3.11, virtual env at /opt/becker-bot/venv/
- Indentation: 4 spaces (never tabs)
- Services: becker-bot (bot engine), becker-dashboard (Streamlit on :8501)
- Config and secrets in .env (never committed to git)
- State persisted in JSON files (positions.json, bot_state.json, learner_state.json)
- Fee model uses exact Polymarket formula: fee = C * rate * p * (1-p)

## Key Gotchas (learned the hard way)

- bash heredocs (cat << 'EOF') break when file content contains markdown code fences.
  Use python3 scripts to write files instead.
- The shared_state import in becker_bot_v4.py is multi-line with parentheses.
  Be careful not to corrupt it when adding new imports.
- Fee/P&L variables (realized_pnl_net, total_fees) must be restored from
  positions.json on startup, not from bot_state.json (which may have stale values).
- The reevaluate_positions() function has two exit paths (market resolution and
  trailing stop — replaced by hybrid exit system v4.1.8).
  not outside it.
- Dashboard indentation must be consistent (12 spaces inside column blocks).
  Mixed indentation causes silent Streamlit crashes.

## Project State Reference

- README.md — project overview, performance, schemas, LLM context block
- ARCHITECTURE.md — system diagrams, scan loop, estimation pipeline, data flow
- ROADMAP.md — phased upgrade plan with checkboxes and evaluation gate
- CHANGELOG.md — version history with dates

## Hard Design Rule — No Standalone Tools

**Every new data source, signal, or filter MUST feed into the unified scoring system.**
No tool operates independently. No standalone triggers. No isolated blockers.

The bot balances all inputs into one composite score per opportunity:
- EV (from estimator)
- Fee drag (from category fee model)
- Category historical return (from learner)
- Momentum z-scores (from Layer 2)
- Correlation with existing book (from correlation filter)
- Alternative data signals (from satellite/OSINT/tremor feeds)
- Options-chain cross-reference (from CME/CBOE implied probabilities)

Each input has a weight. Weights are learned from outcomes, not hardcoded.
The system self-balances: if satellite data consistently improves geopolitics returns,
its weight increases automatically. If momentum z-scores add noise, their weight decays.

**Implementation order:**
1. Cross gate (50 trades) — validate base system
2. Build unified scoring framework (50-100 trades) — single composite score
3. Plug in new data sources one at a time (100+ trades) — each becomes a scoring input
4. Adaptive weight learning (200+ trades) — system learns which inputs matter

This rule applies to: Tremor.live (1.11), correlation filter (1.2), geopolitics mode (1.8),
satellite feeds (3.8), options cross-ref (2.7), mean-reversion (3.4), and all future additions.

## Pending Design Decision — Unified Scoring System (Post-Gate)

**Context (2026-04-02):** Current systems conflict with each other:
1. Learner corrections push estimates up (+0.84 for geopolitics) while Becker sanity filter shrinks them back toward market price
2. Kelly sizing ignores category fee efficiency (sports 3% fees vs geopolitics 0%)
3. Capacity fills first-come-first-served, not by expected profitability
4. Sports has 49% of deployed capital but lowest return/trade ($1.69); geopolitics has 7x better return/trade ($11.82) with zero fees

**Decision:** Do NOT implement Phase 1.8 (geopolitics priority) as a standalone hack. Instead, after crossing the 50-trade gate, build a unified composite scoring system that replaces the current patchwork:
- Single score per opportunity combining: EV, fee drag, category historical performance, correlation with existing book
- Bot fills slots by rank, not by API response order
- Replaces independent sanity filter, category block, and Kelly as separate stages
- Needs 30+ closed trades per category for stable per-category averages
- Target: implement between 50-100 closed trades

**Combines roadmap items:** 1.2 (correlation filter), 1.8 (geopolitics priority), and elements of 4.5 (portfolio-aware sizing) into one coherent system.

## Session Startup


When beginning a new session, the human will provide:

    Project: Becker Bot v4.1
    Repo: https://github.com/arsenbenda/becker-bot (private)
    Read: CLAUDE.md, README.md, ARCHITECTURE.md, ROADMAP.md, CHANGELOG.md

The assistant should ask for the latest log output:

    tail -30 /opt/becker-bot/becker_bot.log

And the latest position summary:

    python3 -c "import json; p=json.loads(open('/opt/becker-bot/positions.json').read()); o=[x for x in p if x.get('status')=='open']; c=[x for x in p if x.get('status')=='closed']; print(f'Open: {len(o)}, Closed: {len(c)}, Gross: \${sum(float(x.get(chr(112)+chr(110)+chr(108),0)) for x in c):+.2f}, Net: \${sum(float(x.get(chr(110)+chr(101)+chr(116)+chr(95)+chr(112)+chr(110)+chr(108),x.get(chr(112)+chr(110)+chr(108),0))) for x in c):+.2f}')"
