# Bracket System Audit: F- → A+

## Overall Grade: **B-** — Strong concept, several fixable issues that will hurt your bracket and your resume demo

---

## WHAT'S WORKING WELL (A-tier)

**Agent diversity is genuinely good.** Seven distinct analytical lenses with real philosophical disagreements (Iron Curtain's "defense travels" vs Glass Cannon's "variance wins") is the strongest part of the system. The temperature spread (0.3–0.9), multi-model diversity (Claude vs Gemini), and bias field specialization create real disagreement rather than 7 copies of the same reasoning.

**The debate transcript output is excellent for a portfolio piece.** Markdown files with agent reasoning, dissent reports, upset scores, and Vegas comparisons are exactly what a hiring manager wants to see — transparent, auditable AI orchestration.

**Confidence clamping and base-rate anchoring** are well-calibrated. Oracle's ±15-point constraint from historical seed rates is the right kind of guardrail.

---

## CRITICAL ISSUES

### 1. Devil's Advocate is Theater (Grade: D)
The devil's advocate triggers on unanimous votes but **does not feed back into the conductor's decision.** It's logged and ignored. For a resume piece, this is a problem — anyone reading the code will see it's decorative. Either:
- Feed the DA vote into the conductor as an 8th input with 0.5x weight
- Or let the DA argument actually reduce the conductor's confidence by 5-10 points on unanimous picks

Without this, you have an "anti-groupthink mechanism" that doesn't actually prevent groupthink.

### 2. Stats Are Stale After R64 (Grade: D-)
Winners carry their **season-long stats unchanged** through every round. A team that just beat a 1-seed in R32 gets evaluated in S16 with the same `last_10_record` and `current_streak` from before the tournament. This means:
- **Momentum agents (Streak, Road Dog, Whisper) lose their entire purpose** in later rounds — they're reading pre-tournament momentum data for S16/E8 games
- The system is effectively blind to tournament performance after R64
- Later rounds will be less accurate than R64, which is the opposite of what you want

**Fix:** At minimum, update `last_10_record`, `current_streak`, and `conf_tournament_result` after each round based on bracket results. Even a simple "won R64/R32" annotation would help the narrative agents.

### 3. Bias Boost is a Thumb on the Scale in the Wrong Direction (Grade: C-)
The bias boost (+5 to +10 confidence) is applied **after** the LLM already made its pick. This means:
- If Iron Curtain picks the team with better defense, its confidence gets +10 — but it was **already biased toward defense by its system prompt**. You're double-counting the same signal.
- Iron Curtain's +10 is the highest boost, making it the most influential agent by raw confidence numbers, regardless of whether defense is actually the key factor in a given game.
- The conductor says it weights by "key factor specialist 2x" — but if that specialist also got a +10 bias boost, you're effectively 3x-ing one signal.

**Fix:** Either remove bias boost (the prompts already encode the bias) or apply it as a tie-breaker only (e.g., only boost if the agent's raw confidence was 55-65).

### 4. Two Agents Share `kenpom_rank` Bias Field (Grade: C)
Road Dog and Oracle both use `kenpom_rank` as their bias field. Two agents share `adj_o`. This reduces effective diversity — you have 7 agents but only 5 distinct bias signals. Road Dog should probably use something like `wins` or a coaching/experience metric instead.

---

## MODERATE ISSUES

### 5. Conductor Override Rule Creates a Hidden Chalk Bias (Grade: C+)
The 5+ agent majority override is **hard-enforced post-conductor.** Combined with the fact that most agents have strong system-prompt priors favoring higher seeds (Iron Curtain trusts defense = usually the favorite, Oracle anchors to base rates that favor favorites, Tempo Hawk's pace analysis usually favors the better team), you'll get 5+ agent agreement on the favorite in most games. The conductor literally **cannot** pick an upset if 5+ agents pick chalk.

This means your upset picks are almost entirely dependent on whether 3+ of your upset-leaning agents (Glass Cannon, Road Dog, Whisper, Streak) independently decide to pick the underdog. That's a high bar for games where it matters (5v12, 6v11, 7v10).

**The backtest confirmed this:** 0/3 upsets in dry-run mode. Even with real API calls, the structural chalk bias will suppress upset picks below historical base rates.

### 6. Upset Score Doesn't Influence Anything (Grade: C)
The upset score (0-100) is calculated, logged, and... nothing. It doesn't feed into the conductor, doesn't adjust confidence, doesn't trigger any override. It's a diagnostic metric that diagnoses but never treats. If upset_score ≥ 70, the conductor should at minimum see it and have its confidence capped.

### 7. Agent Accuracy Tracking is Soft, Not Hard (Grade: C+)
The conductor sees agent accuracy in its prompt but has no mechanical obligation to weight accurate agents higher. In a 63-game bracket, by the Final Four you'll have real accuracy data — but the system treats a 90%-accurate agent the same as a 40%-accurate one unless the LLM spontaneously decides to weight them differently.

---

## MINOR ISSUES

### 8. Glass Cannon's 34% Threshold is Arbitrary (Grade: B-)
The "if 3PT% > 34%, MUST pick upset OR explain" rule is reasonable but the threshold should probably scale by matchup. 34% is roughly average — the trigger should be relative (lower seed shoots better than higher seed from 3), not absolute.

### 9. No Conference Strength Adjustment (Grade: B-)
A 12-seed mid-major with a 28-5 record against weak competition gets the same `record` treatment as a 12-seed from a power conference. The agents don't have SOS (strength of schedule) data, which is one of the most predictive tournament metrics.

### 10. Temperature Scaling by Seed Difference is Backwards (Grade: C+)
Close games (8v9) get **higher** temperatures for "more creative responses." But close games are where you need the most analytical precision, not creativity. Blowouts (1v16) are already deterministic — extra creativity there is harmless. For competitive games, you want lower temperatures to avoid noise-driven upsets.

---

## WHAT THIS MEANS FOR YOUR BRACKET

**Expected failure mode:** Too much chalk in R64 (picking ~5-6 upsets when you need 8-10), followed by increasingly stale analysis in later rounds as momentum/narrative agents operate on pre-tournament data. Your Final Four picks will be reasonable (top seeds usually get there) but your Cinderella runs will be underpredicted.

**Expected strength:** When the system does pick upsets, they'll be well-reasoned (multiple agents agreed, key factor identified). The debate transcripts will be compelling regardless of accuracy.

---

## PRIORITY FIXES (ranked by impact)

1. **Update stats between rounds** — at minimum `last_10`, `current_streak`, "won R64 as X-seed over Y-seed"
2. **Make devil's advocate functional** — feed into conductor or cap confidence
3. **Remove or nerf bias boost** — the prompts already encode bias; the boost double-counts
4. **Give Road Dog a unique bias field** — coaching wins, tournament experience, something not `kenpom_rank`
5. **Feed upset_score into conductor** — if ≥60, cap favorite confidence at 72%
6. **Flip temperature scaling** — lower temp for close games, higher for blowouts (or just remove it)
