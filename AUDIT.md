# Comprehensive Code & Methodology Audit

**Date:** 2026-03-16
**Auditor:** Claude Opus 4.6 (automated deep audit)
**Test Suite:** 19/19 passing

---

## AUDIT 1: Is the Code Doing What We Intended?

### Agent Architecture — Grade: A-

**PASS:**
- All 7 agents (Tempo Hawk, Iron Curtain, Glass Cannon, Road Dog, Whisper, Oracle, Streak) are called for every game via `asyncio.gather` at `swarm_engine.py:2102`. Tests confirm 7/7 agents return in every debate.
- Gemini agents actually call Gemini. `run_agent()` (`swarm_engine.py:1521`) checks `agent.model == "gemini"` and calls `call_gemini_api()`. In `--multi-model` mode: Glass Cannon, Road Dog, Whisper, Streak run on Gemini; Tempo Hawk, Iron Curtain, Oracle run on Claude.
- Multi-round debate (R1 → R2 cross-examination) is working. Lines 2218-2275 run Round 2 for all agents that had valid R1 votes. R2 agents receive the FULL R1 summary via `format_round1_outputs()` (`swarm_engine.py:1605-1618`) which includes ALL other agents' picks, probabilities, reasoning, and key stats.
- Round 2 receives Round 1 outputs from ALL agents — `format_round1_outputs` iterates all `valid_votes` from R1.
- Devil's advocate triggers on unanimous votes (`swarm_engine.py:2281-2303`) and feeds into the Conductor via a half-weighted 8th vote (lines 2314-2325).
- Adaptive debate rounds work: seed_diff >= 10 AND unanimous R1 → skip R2 (`swarm_engine.py:2210`).

**WARN:**
- The Conductor is described as the "8th agent" but never counted that way in code. It's a separate synthesis step. Not really 8 agents — it's 7 debaters + 1 synthesizer. This is fine architecturally but the naming is slightly misleading.

### Data Flow — Grade: B+

**PASS:**
- The `run_agent()` user_message (`swarm_engine.py:1462-1501`) injects: adj_o, adj_d, adj_tempo, three_pt_pct, record, conference (with tier label), kenpom_rank, last_10_record, current_streak, conference_tourney_result, recent_form_notes, turnover_rate, opp_fg_pct, experience_score, tournament_wins, injury_notes, rest_days, travel_distance_miles, key_players. **ALL data fields from mm_teams are injected.**
- Key players text field IS included in agent prompts (`swarm_engine.py:1482, 1500`).
- Stats are conditionally included (only when non-empty) which is correct.

**WARN:**
- Agent-specific data routing does NOT exist. All 7 agents see ALL data fields. Whisper sees travel_distance but so does Tempo Hawk. The "STAY IN YOUR LANE" enforcement is purely in the system prompt (agents are instructed not to use certain data), not in code. This is a soft constraint, not a hard one. LLMs sometimes ignore lane restrictions.
- `mm_players` data is only used via the `key_players` text field on `mm_teams`. There is no direct query to `mm_players` in the swarm engine.

### Probabilistic Output — Grade: A

**PASS:**
- Agents output `team_a_win_prob` + `uncertainty` via JSON format (`swarm_engine.py:377-385`). The `parse_agent_response()` function handles both new probabilistic format and legacy pick/confidence format (lines 1236-1282).
- The Conductor does NOT count votes. The pick is determined by `combine_probabilities()` (`swarm_engine.py:1756-1814`) which does weighted averaging of agent probabilities. The Conductor's LLM response provides the narrative explanation, but the **actual pick comes from the math** (line 1876: `math_pick = game.team_a if combined_prob > 0.5 else game.team_b`).
- Combined uncertainty is correctly calculated as `sqrt(disagreement² + avg_uncertainty²)` (`swarm_engine.py:1809`).
- Feature-driven weights from `get_game_weights()` are used in the probability combination (lines 1829-1836).

### Bracket Progression — Grade: A-

**PASS:**
- Winner stats update between rounds via `_get_winner_data()` (`swarm_engine.py:2756-2816`): tournament_wins, current_streak, last_10_record, recent_form_notes, and conference_tourney_result are all updated.
- Final Four pairing is correct: East vs West, South vs Midwest (`swarm_engine.py:2700-2719`).
- Monte Carlo simulation runs after R64, produces valid championship probabilities, and writes to Supabase (lines 3028-3058).

**WARN:**
- Winner stats updates (lines 2792-2804) use a naive sliding window that just adds a win and removes a loss. After 4 tournament wins, a team with last_10 "5-5" becomes "9-1" which over-inflates their recent form. Minor but worth noting.

### Cost & Safety — Grade: A

**PASS:**
- CostGuard checks budget before every API call (`swarm_engine.py:1336-1340` for Claude, `swarm_engine.py:1402` for Gemini).
- API keys read from `.env` via `load_dotenv()`. Not in code, not logged. Gemini URL uses `_sanitize_url()` for safe logging.
- Default $100 budget set at `swarm_engine.py:107`: `CostGuard(max_budget=float(os.getenv("SWARM_BUDGET", "100.0")))`.
- `sanitize_team_name()` exists and blocks prompt injection patterns.

**WARN:**
- `sanitize_team_name()` is defined but never called in the production code path. Team names flow from Supabase/bracket_loader directly into prompts without sanitization. Low risk since data is your own, but it's an unused safety net.

---

## AUDIT 2: Agent Persona Quality — Grade: A-

**PASS:**
- Each agent has a genuinely distinct voice. Tempo Hawk is clinical/NPR, Iron Curtain is gruff/intense, Glass Cannon is energetic/excited, Road Dog is folksy/storytelling, Whisper is conspiratorial, Oracle is professorial, Streak is urgent/present-tense. Easily identifiable.
- "STAY IN YOUR LANE" restrictions are in every agent's prompt with explicit lists of what NOT to discuss.
- Banned phrases ("house money", "playing with confidence", "nothing to lose") are in the shared `confidence_calibration` block injected into all agents.
- Pick consistency rule is both in prompts AND enforced in code: `parse_agent_response()` lines 1290-1307 detect "screams upset" language and force `team_a_win_prob` to 0.48 if the agent contradicted their own argument.

**Upset Triggers — All Present:**
- Glass Cannon: "HARD RULE — COMMIT TO VARIANCE" (`swarm_engine.py:532-536`) — must give underdog 50%+ when shooting is close.
- Streak: CONVICTION RULE (`swarm_engine.py:803-805`) — must pick lower seed when momentum favors them.
- Road Dog: CONVICTION RULE (`swarm_engine.py:607-609`) — cap at 0.55 for favorite when lower seed has experience 7+ and conf champ.
- Confidence calibration text is in ALL agent prompts via the shared `confidence_calibration` block.

**Conductor:**
- Sees both Round 1 AND Round 2 (`swarm_engine.py:2327-2331`).
- Override rules enforced in code (lines 2351-2376): 5-2 or wider → must follow majority. 4-3 → independent judgment.
- Meta-model weighting (`get_game_weights`) IS used via `combine_probabilities()`.
- Conductor prompt explicitly asks to "Name the winner(s) and loser(s) of the debate" (line 972).

**WARN:**
- Glass Cannon's upset trigger says "within 2 points" in the prompt text but the HARD RULE says "within 2 points OR above 36%". The `get_game_weights` function uses `abs(three_a - three_b) > 3` for boost, which is a slightly different threshold than the prompt. Not a bug but a minor inconsistency between code weighting and prompt instructions.

---

## AUDIT 3: Six Pillars Check

### Pillar 1: Context Management — Grade: A

**PASS:**
- AgentMemory exists and works correctly (tests pass).
- Memory IS empty during `--full-bracket` mode. `get_context_for_game()` returns `""` when `has_real_results()` is False (`agent_memory.py:49-50`).
- Memory activates correctly in `--live-update` mode (`swarm_engine.py:2094-2096`).
- Context window is appropriately sized: max_tokens=512 for agents.

### Pillar 2: Tool Orchestration — Grade: A

**PASS:**
- Adaptive debate saves API calls: `skip_round2 = (seed_diff >= 10 and len(r1_picks) == 1)` (`swarm_engine.py:2210`).
- Multi-model routing works: Claude via `call_claude_api()`, Gemini via `call_gemini_api()`.
- Retries with exponential backoff for both Claude (`swarm_engine.py:1343-1391`) and Gemini (`gemini_client.py:67-128`). Failed agents retry up to 2 additional times (`swarm_engine.py:2123-2164`).

### Pillar 3: Security — Grade: B+

**PASS:**
- CostGuard functional with configurable budget.
- API keys properly protected.

**WARN:**
- `sanitize_team_name()` is not called in the main code path (see above).

### Pillar 4: Efficiency & Routing — Grade: A-

**PASS:**
- Agents run concurrently via `asyncio.gather(*tasks)` (`swarm_engine.py:2102`) with semaphore-based rate limiting (5 concurrent, `swarm_engine.py:118`).
- Dynamic temperature applied based on seed diff (`swarm_engine.py:307-321`).

**FAIL:**
- Response caching is NOT implemented. Each game's agent calls are fresh. If you re-run the same game, it makes new API calls. Not critical for a single production run but noted.

### Pillar 5: Observability — Grade: A

**PASS:**
- Trace IDs generated per game via `GameTracer` (`swarm_engine.py:2080`).
- CalibrationTracker computes Brier score correctly (tested, `observability.py:253-260`).
- AgentPerformanceTracker logs per-agent metrics (tested).
- ZeroDivisionError guard in place: `max(total_votes, 1)` at `swarm_engine.py:1084`, `max(game_counter,1)` at `swarm_engine.py:3091`.

### Pillar 6: Testing & Evaluation — Grade: A

**PASS:**
- **19/19 tests pass.**
- Regression tests cover: chalk picks, toss-up uncertainty, all agents present, adaptive debate, full debate, no override of 6+ majority.
- Calibration report compares to historical base rates (`swarm_engine.py:3107-3137`).

---

## AUDIT 4: Market Analysis & Monte Carlo — Grade: B+

**PASS:**
- `odds_tracker.py` fetches real Vegas lines from The Odds API with caching and quota tracking.
- `market_analyzer.py` compares swarm probability to Vegas implied probability correctly. Uses spread-implied AND moneyline-implied probabilities, removes vig from moneylines.
- Kelly criterion calculation is correct (`market_analyzer.py:224-239`): `f* = (bp - q) / b`, half-Kelly for safety, capped at 10%.
- Monte Carlo cross-region bug is FIXED. All 4 regions present in test mode and production mode loads from Supabase.
- Monte Carlo results written to `mm_monte_carlo` with correct `tournament_id` FK.

**WARN:**
- `spread_to_implied_prob()` uses a simplistic linear model (`0.50 + (-spread * 0.03)`). This is a rough approximation. A logistic model would be more accurate but the current approach is reasonable for the level of analysis.
- Monte Carlo later-round games use `estimate_win_prob()` which is purely seed+KenPom based with no debate data. This is by design but means F4/NCG probabilities don't benefit from agent analysis.

---

## AUDIT 5: Known Bugs & Inconsistencies

### 1. Conductor misattributes debate winners
**WARN — LLM noise, not code bug.** The Conductor's `reasoning` field is generated by the LLM. The code correctly computes the pick from math (`swarm_engine.py:1876`), but the LLM's narrative can contradict the math. The prompt asks to "Name the winner(s) and loser(s) of the debate" but doesn't explicitly define "winner" = "agent whose pick won." This is a prompt clarity issue. Could add: "The winner of the debate is the agent(s) whose analysis had the highest weight in the final probability, not who argued most persuasively."

### 2. Glass Cannon sometimes argues for favorite's shooting
**WARN — Prompt issue.** The prompt says Glass Cannon focuses on "underdog shooting variance" and the upset trigger fires when "lower seed shoots BETTER from three." But the prompt doesn't explicitly say "you must focus on the UNDERDOG's shooting." When the favorite shoots better, Glass Cannon can legitimately argue for the favorite from a shooting perspective. This is arguably correct behavior.

### 3. Oracle says "screams upset" then picks favorite
**PASS — Code safety net works.** `swarm_engine.py:1290-1307` in `parse_agent_response()` detect "screams upset" language and force the probability to 0.48 (pick underdog). This safety net IS functional.

### 4. Round 2 pile-on problem
**WARN — Soft constraint only.** The R2 prompt says "SPREAD YOUR FIRE: You may NOT disagree with the same agent that more than 2 other agents have already targeted." But since all agents run concurrently, they don't know what other agents targeted. This is a prompt-level instruction that relies on the LLM being smart enough to diversify, but there's no code enforcement. Each agent sees the R1 summary but not other agents' R2 responses.

### 5. Road Dog repeats R1 verbatim in R2
**PASS — Addressed in prompt.** The R2 template includes: "NO COPY-PASTE: Your Round 2 reasoning MUST contain a NEW argument or new information. You CANNOT repeat your Round 1 analysis word-for-word." (`swarm_engine.py:1640-1641`). This is a prompt-level constraint — can't be enforced in code without comparing R1/R2 texts (which would add complexity for marginal gain).

---

## Section Grades Summary

| Section | Grade |
|---|---|
| Agent Architecture | A- |
| Data Flow | B+ |
| Probabilistic Output | A |
| Bracket Progression | A- |
| Cost & Safety | A |
| Agent Personas | A- |
| Pillar 1: Context | A |
| Pillar 2: Orchestration | A |
| Pillar 3: Security | B+ |
| Pillar 4: Efficiency | A- |
| Pillar 5: Observability | A |
| Pillar 6: Testing | A |
| Market/Monte Carlo | B+ |
| Known Bugs | B |

---

## Prioritized Fix List

### Critical (should fix before finalizing)
None. The system is functionally correct.

### Moderate (would improve quality)

1. **`sanitize_team_name()` is never called** — Add calls when loading team names from Supabase/bracket_loader before injecting into prompts. Low risk since data is your own, but defense-in-depth matters.

2. **Response caching not implemented** — If you re-run a single game for debugging, it costs money each time. Consider a simple file-based cache keyed on (game_id, agent_name, round_number).

### Minor (nice-to-have)

3. **R2 pile-on can't be prevented** — Would require sequential R2 calls (expensive) or a two-pass approach. The prompt mitigation is reasonable.

4. **Winner stats sliding window is naive** — After 4 tournament wins, last_10 goes from "5-5" to "9-1". Could track actual last-10 games rather than the naive increment.

5. **Conductor "debate winner" language** — Could add a line to the prompt: "The debate winner = the agent whose analysis had the highest weight in the final probability, not who argued most persuasively."

6. **Monte Carlo later rounds use only seed+KenPom** — By design, but could incorporate debate probabilities from R32+ if they were stored. Would require architecture changes.

---

## Honest Assessment

**Is this system producing results driven by real data analysis, or is it sophisticated theater?**

**It's substantially real, with some theater around the edges.**

### The real parts:
- Agent probabilities are mathematically combined with feature-driven weights. The final pick comes from `combine_probabilities()`, not from the Conductor's LLM.
- All team stats from Supabase (adj_o, adj_d, tempo, 3PT%, etc.) are injected into agent prompts and agents DO cite specific numbers in their analysis.
- Historical base rates anchor Oracle's picks and the calibration report validates against them. The production run produced 9/32 R64 upsets, within the expected 7-10 range.
- Market comparison against real Vegas lines provides an external validation layer.
- Monte Carlo simulation produces valid advancement probabilities from R64 game data.

### The theater parts:
- Agent "personalities" and "debates" are LLM role-playing. The agents don't actually do different computations — they're the same models with different system prompts interpreting the same data. The "cross-examination" is LLMs reacting to other LLMs' text, not agents with different analytical tools.
- The "upset triggers" in prompts are instructions to the LLM, not algorithmic rules. The LLM may or may not follow them. The code-level safety nets (pick consistency, upset phrase detection) catch some violations but not all.
- Agent names like "Tempo Hawk" and "Glass Cannon" add flavor but the underlying analysis is "LLM reads stats and makes a judgment." The personality differentiation means agents DO weigh different stats differently, but it's a soft signal, not a hard analytical framework.

### Bottom line:
The system is well above "sophisticated theater." The mathematical probability combination, feature-driven weighting, calibration validation, and market comparison provide genuine analytical value. The debate format creates real diversity in perspectives that wouldn't exist with a single-prompt approach. The production run's 9/32 upset rate matching historical base rates is strong evidence the system is well-calibrated. As a portfolio piece demonstrating multi-agent AI architecture, this is solid and genuine.

---

## Files Audited

| File | Lines | Purpose |
|---|---|---|
| `swarm_engine.py` | 3212 | Core engine: agents, debate, conductor, bracket progression |
| `monte_carlo.py` | 561 | Monte Carlo bracket simulation |
| `odds_tracker.py` | 270 | Vegas odds fetching and comparison |
| `market_analyzer.py` | 499 | Market inefficiency detection, Kelly criterion |
| `agent_memory.py` | 304 | Tournament memory system |
| `cost_guard.py` | 134 | Budget enforcement |
| `observability.py` | 328 | Tracing, calibration, performance tracking |
| `gemini_client.py` | 136 | Gemini API client |
| `supabase_client.py` | 145 | Database client |
| `test_pillars.py` | 452 | Test suite (19 tests) |
