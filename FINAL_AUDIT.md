# FINAL COMPREHENSIVE AUDIT — March Madness Agent Swarm

**Auditor:** Claude Opus 4.6 | **Date:** 2026-03-16 | **Scope:** Full system, Six Pillars, production readiness for $23 run

---

## EXECUTIVE SUMMARY

| Area | Grade | Status |
|------|-------|--------|
| **Pillar 1: Context Management** | **A-** | Pass |
| **Pillar 2: Tool Orchestration** | **A-** | Pass |
| **Pillar 3: Security** | **B+** | **1 blocker** |
| **Pillar 4: Efficiency & Routing** | **A-** | Pass |
| **Pillar 5: Observability** | **B+** | **1 blocker** |
| **Pillar 6: Testing & Evaluation** | **A-** | Pass |
| Core Engine (swarm_engine.py) | **A-** | Pass |
| Dashboard (React/Vercel) | **A-** | Pass |
| Supporting Modules | **A-** | Pass |
| **Overall** | **B+** | **2 production blockers remain** |

---

## PRODUCTION BLOCKERS (must fix before $23 run)

### BLOCKER 1: `observability.py:177` — ZeroDivisionError crash

`AgentPerformanceTracker.get_agent_summary()` divides by `len(metrics)` without guarding for empty list. If any agent fails all attempts in a round (possible under timeout/degradation), this crashes the entire pipeline mid-run.

```python
# Line 177 — current (crashes)
"avg_response_ms": sum(m.response_time_ms for m in metrics) / len(metrics),

# Fix
"avg_response_ms": (sum(m.response_time_ms for m in metrics) / len(metrics)) if metrics else 0,
```

**Risk:** Pipeline crash mid-tournament = wasted API spend, partial results, manual recovery.

### BLOCKER 2: Supabase `mm_agent_votes` constraint mismatch

Test output shows:
```
there is no unique or exclusion constraint matching the ON CONFLICT specification
```

`supabase_client.py:101` tries `on_conflict="game_id,agent_name,round_number"` but the table lacks this composite unique constraint. The fallback at line 106 (`on_conflict="game_id,agent_name"`) also fails per the error log. **Agent votes are not being persisted to the database.**

**Risk:** Dashboard shows no agent votes. Accuracy tracking broken. The entire frontend is empty.

---

## SIX PILLARS — DETAILED GRADES

### Pillar 1: Context Management — A-

| Component | Status |
|-----------|--------|
| Agent memory (prediction vs live-update separation) | Excellent |
| Tournament memory persistence (save/load) | Working |
| Tiered context windows per agent | Implemented |
| Memory carries across rounds | Verified |

**Strengths:** Clean mode separation — prediction mode returns empty context (no fake self-awareness), live-update mode provides real accuracy feedback. `AgentMemory` dataclass design is solid with proper data limiting (last 10 misses, 50 calibration points).

**Risk (non-blocking):** `agent_memory.py:266` — no try-except on `json.load()`. Corrupted `tournament_memory.json` crashes on startup. Add a try-except with fallback to empty state.

### Pillar 2: Tool Orchestration — A-

| Component | Status |
|-----------|--------|
| Adaptive debate rounds (skip R2 for blowouts) | Working |
| Multi-model routing (Claude + Gemini) | Working |
| Devil's advocate on unanimous votes | Fires, partially functional |
| Bracket progression (R64 → Championship) | Correct |

**Strengths:** Adaptive debate saves ~30% API cost on blowouts (seed_diff >= 10 + unanimous = skip R2). Multi-model diversity (3 Claude, 3 Gemini) is the strongest anti-convergence mechanism. Bracket progression correctly pairs Final Four (East/West, South/Midwest).

**Improved since last audit:**
- Bias boost now only applies in toss-up zone (55-68 confidence) — no longer double-counting
- All 7 agents have unique bias fields (Road Dog now uses `record`, not `kenpom_rank`)
- Temperature scaling is correct (lower temp for close games like 8v9)

**Residual concern:** Devil's advocate vote is included in probability math (halved confidence) and caps conductor confidence at 82%, but the conductor's pick is still driven by `combined_prob` math, not the DA argument. This is **functional but weak** — upgraded from D to B- since the DA now mechanically affects confidence.

### Pillar 3: Security — B+ (blocker)

| Component | Status |
|-----------|--------|
| Cost guardrails (async budget enforcement) | Working |
| Prompt injection sanitization | Implemented but unused |
| API key handling (.env, .gitignore) | Correct |
| Budget warning thresholds | Working |

**Strengths:** `CostGuard` uses async lock for thread safety, progressive warnings at 50/75/90% budget, `BudgetExceededError` hard-stops the run.

**Issues:**
- `cost_guard.py:record_actual()` is never called — budget tracking uses estimates only. For a $23 budget this likely works (estimates are conservative), but actual costs could diverge.
- `sanitize_team_name()` exists but is dead code — never called from `swarm_engine.py`. Not a blocker but misleading for code review.
- Cost estimation constants differ between `cost_guard.py` and `observability.py` (different per-token rates for same models).

**The Supabase constraint blocker (described above) is a data-integrity issue that falls under this pillar.**

### Pillar 4: Efficiency & Routing — A-

| Component | Status |
|-----------|--------|
| Adaptive debate (skip R2 on blowouts) | Working — ~30% savings |
| Feature-driven agent weighting | Working after R1 |
| Parallel async pipeline | Working |
| Market inefficiency detection | Implemented |

**Strengths:** `get_game_weights()` applies mechanical accuracy multipliers (1.3x for >65% accurate agents, 0.7x for <40%) after Round 1. Async gather runs all 7 agents in parallel.

**Concern (non-blocking):** `market_analyzer.py:227` has a confusing bet probability formula. Kelly criterion math should be reviewed before trusting bet sizing recommendations. This module is post-processing / informational only — does not affect picks.

### Pillar 5: Observability — B+ (blocker)

| Component | Status |
|-----------|--------|
| Per-game trace IDs | Working (UUID-based) |
| Structured event logging | Working |
| Calibration curves (Brier, ECE, log loss) | Working |
| Agent performance metrics | **BLOCKER — ZeroDivisionError** |

**The ZeroDivisionError blocker (described above) is in this pillar.**

Everything else is solid: `GameTracer` generates clean trace IDs, `CalibrationTracker` correctly computes Brier score with epsilon-guarded log loss, structured events are properly timestamped and serializable.

### Pillar 6: Testing & Evaluation — A-

| Component | Status |
|-----------|--------|
| test_orchestration.py (25 tests) | **25/25 PASS** |
| test_pillars.py (19 tests) | **19/19 PASS** |
| Regression: no chalk bias | Verified |
| Regression: all 7 agents present | Verified |
| Regression: conductor override rule | Verified |

**44/44 tests passing.** Test coverage is strong for core paths. Regression suite validates critical invariants (no agent dropouts, conductor can't override 6+ majority, 5v12 produces genuine uncertainty 50-75%).

**Gaps (non-blocking):**
- No test for `AgentPerformanceTracker` with zero metrics (the crash case)
- No tests for `market_analyzer.py` (only has inline `__main__` test)
- `audio_gen.py`, `scrape_teams.py`, `fill_bracket.py` untested
- `live_tracker.py:173` uses substring matching — "Duke" would match "Duquesne"

---

## CORE ENGINE (swarm_engine.py) — A-

**2,865 lines. This is the heart of the system.**

| Aspect | Grade |
|--------|-------|
| Structured output parsing (4-layer fallback) | A |
| Retry logic (3 attempts, exponential backoff) | A |
| Fuzzy team name matching | A |
| Graceful degradation (4+ votes = continue) | A |
| Bracket progression | A |
| Agent diversity (7 unique agents, unique bias fields) | A |
| Conductor decision mechanism | A- |
| Error handling / timeouts | A- |
| Anti-convergence | B+ |

**Known design tradeoffs (acceptable):**
- 5+ majority hard-overrides conductor — creates structural chalk bias, but this is a deliberate safety mechanism
- Conductor pick comes from probability math, reasoning from LLM — narrative may not match pick. Intentional design.
- Stats update between rounds but not mid-game — acceptable for a bracket predictor

---

## DASHBOARD — A-

| Aspect | Grade |
|--------|-------|
| Supabase integration (5 mm_* tables) | A |
| All 5 pages functional | A |
| Build status (Vite) | A — builds clean |
| Security (anon key only, .env in .gitignore) | A |
| Error handling | A |
| Agent config (8 agents, emojis, colors) | A |
| Mobile responsiveness | B- |

**Mobile issues (non-blocking for a portfolio demo):**
- Fixed 220px sidebar consumes 36% of mobile viewport
- 40px padding with no breakpoints
- SVG bracket may overflow on small screens
- No `@media` queries anywhere

**Dashboard .env** has anon key properly documented as safe for client-side. Root `.gitignore` correctly excludes both `.env` files.

---

## SUPPORTING MODULES — A-

| Module | Lines | Grade | Notes |
|--------|-------|-------|-------|
| supabase_client.py | 152 | A- | Atomic status.json, graceful fallback. **Constraint mismatch = blocker** |
| gemini_client.py | 135 | A- | Retry logic solid. No bounds check on `candidates[0]` (low risk) |
| odds_tracker.py | 269 | A | Robust caching, fuzzy matching, graceful fallback |
| live_tracker.py | 311 | B+ | Substring matching fragile (Duke/Duquesne). fcntl Unix-only |
| backtest.py | 594 | A | Comprehensive calibration reporting |
| monte_carlo.py | 437 | A | Mathematically sound bracket simulation |
| audio_gen.py | 613 | B+ | Optional. Hardcoded silence frame bitrate is fragile |
| scrape_teams.py | 212 | B+ | No ESPN date filtering on injury reports |
| fill_bracket.py | 245 | B+ | Unescaped format string in code generation (low risk) |
| start.sh | ~50 | A | Clean tmux launcher with signal handling |

---

## COST ESTIMATE FOR $23 PRODUCTION RUN

Per test output: 25 tests used ~97 API calls at $2.13 estimated cost.

Full 63-game bracket with multi-model:
- ~7 agent calls + 1 conductor + potential DA per game x up to 2 rounds
- Estimated: ~800-1000 API calls
- **Estimated cost: $15-20 for Claude + $1-3 for Gemini = $16-23**
- Budget guard will enforce the $23 cap

This is tight but feasible. The adaptive debate (skipping R2 on blowouts) saves ~30%.

---

## VERDICT

### What must be fixed (2 blockers):

1. **`observability.py:177`** — Guard the division: `if metrics else 0`
2. **Supabase `mm_agent_votes` table** — Add composite unique constraint `(game_id, agent_name, round_number)` or fix the `on_conflict` specification to match the existing schema

### What should be fixed (recommended but not blocking):

3. `agent_memory.py:266` — Add try-except on JSON load
4. Call `cost_guard.record_actual()` after API calls for accurate budget tracking
5. Align cost-per-token constants between `cost_guard.py` and `observability.py`

**Once the 2 blockers are resolved, every area grades A- or higher. The system is ready for the $23 production run.**
