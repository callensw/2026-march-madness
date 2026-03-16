# March Madness Agent Swarm — 2026 Bracket Predictions

**Production Run v3** | March 16, 2026 | 63 games | 881 API calls | $26.84 total cost

---

## How This Works

7 AI specialist agents debate every tournament game in a structured 2-round format:
- **Round 1**: Each agent independently analyzes the matchup through their specialty lens
- **Round 2**: Agents cross-examine each other's arguments, can strengthen, weaken, or flip positions
- **The Conductor**: Synthesizes all arguments using weighted mathematical probability combination

The final pick is determined by **math** (weighted probability averaging), not vote counting. The Conductor provides narrative explanation but cannot override the probability math.

### The Agents
| Agent | Specialty | Model | Bias Field |
|-------|-----------|-------|------------|
| Tempo Hawk | Pace/tempo mismatches | Claude Sonnet 4 | adj_tempo |
| Iron Curtain | Defensive efficiency | Claude Sonnet 4 | adj_d |
| Glass Cannon | 3-point shooting variance | Gemini 2.5 Flash | three_pt_pct |
| Road Dog | Experience, coaching, travel | Gemini 2.5 Flash | experience_score |
| Whisper | Injuries, rest, hidden edges | Gemini 2.5 Flash | injury_notes |
| Oracle | Historical patterns, base rates | Claude Sonnet 4 | kenpom_rank |
| Streak | Momentum, hot/cold streaks | Gemini 2.5 Flash | current_streak |

---

## The Bracket

### CHAMPION: #1 Arizona (Wildcats)
**Championship confidence: 50%** (genuine toss-up acknowledged)
**Path: LIU → Utah State → Wisconsin → Purdue → Duke → Vanderbilt**

### Final Four
| Game | Winner | Vote | Prob | Key Factor |
|------|--------|------|------|------------|
| #1 Duke vs #1 Arizona | **Arizona** | 4-3 | 50% | Duke injuries (Foster/Ngongba II out), Arizona's deeper bench outproduced Duke 28-19 PPG |
| #5 Vanderbilt vs #1 Michigan | **Vanderbilt** | 6-1 | 58% | Elite defense + veteran leadership (7.0/10 experience), 1985 Villanova parallels |

### Championship
| Game | Winner | Vote | Prob | Key Factor |
|------|--------|------|------|------------|
| #1 Arizona vs #5 Vanderbilt | **Arizona** | 5-2 | 55% | Iron Curtain won the debate — Arizona's defense (39.2% opp FG%) + Streak's momentum (14-game win streak). Vandy shot 29% from three in last 3 games |

---

## Full Bracket — Round by Round

### Round of 64 (32 games)

#### East Region
| Matchup | Winner | Vote | Notes |
|---------|--------|------|-------|
| #1 Duke vs #16 Siena | **Duke** | 7-0 | R2 skipped (blowout) |
| #8 Ohio State vs #9 TCU | **Ohio State** | 4-3 | |
| #5 St. John's vs #12 Northern Iowa | **St. John's** | 6-1 | |
| #4 Kansas vs #13 Cal Baptist | **Kansas** | 4-3 | |
| #6 Louisville vs #11 USF | **USF** | 7-0 | UPSET (57.4 upset score) |
| #3 Michigan State vs #14 North Dakota State | **Michigan State** | 7-0 | R2 skipped |
| #7 UCLA vs #10 UCF | **UCLA** | 4-3 | |
| #2 UConn vs #15 Furman | **UConn** | 7-0 | R2 skipped |

#### West Region
| Matchup | Winner | Vote | Notes |
|---------|--------|------|-------|
| #1 Arizona vs #16 LIU | **Arizona** | 7-0 | R2 skipped |
| #8 Villanova vs #9 Utah State | **Utah State** | 6-1 | UPSET (67.2 upset score — highest in tournament) |
| #5 Wisconsin vs #12 High Point | **Wisconsin** | 6-1 | |
| #4 Arkansas vs #13 Hawaii | **Arkansas** | 6-1 | |
| #6 BYU vs #11 Texas | **Texas** | 4-3 | UPSET — Conductor override (picked Texas over BYU majority) |
| #3 Gonzaga vs #14 Kennesaw State | **Gonzaga** | 7-0 | R2 skipped |
| #7 Miami FL vs #10 Missouri | **Miami FL** | 4-3 | Conductor override (picked Miami FL over Missouri majority) |
| #2 Purdue vs #15 Queens | **Purdue** | 7-0 | R2 skipped |

#### Midwest Region
| Matchup | Winner | Vote | Notes |
|---------|--------|------|-------|
| #1 Michigan vs #16 Howard | **Michigan** | 7-0 | R2 skipped |
| #8 Georgia vs #9 Saint Louis | **Saint Louis** | 4-3 | UPSET (60.4 upset score) |
| #5 Texas Tech vs #12 Akron | **Akron** | 6-1 | UPSET (51.2 upset score) |
| #4 Alabama vs #13 Hofstra | **Alabama** | 5-2 | |
| #6 Tennessee vs #11 Miami OH | **Tennessee** | 4-3 | |
| #3 Virginia vs #14 Wright State | **Virginia** | 7-0 | R2 skipped |
| #7 Kentucky vs #10 Santa Clara | **Santa Clara** | 5-2 | UPSET |
| #2 Iowa State vs #15 Tennessee State | **Iowa State** | 7-0 | R2 skipped |

#### South Region
| Matchup | Winner | Vote | Notes |
|---------|--------|------|-------|
| #1 Florida vs #16 Prairie View A&M | **Florida** | 7-0 | R2 skipped |
| #8 Clemson vs #9 Iowa | **Clemson** | 5-2 | |
| #5 Vanderbilt vs #12 McNeese | **Vanderbilt** | 4-3 | Conductor override (picked Vandy over McNeese majority) |
| #4 Nebraska vs #13 Troy | **Nebraska** | 4-3 | Conductor override (picked Nebraska over Troy majority) |
| #6 UNC vs #11 VCU | **VCU** | 7-0 | UPSET (64.4 upset score) |
| #3 Illinois vs #14 Penn | **Illinois** | 4-3 | |
| #7 Saint Mary's vs #10 Texas A&M | **Texas A&M** | 4-3 | Conductor override (picked Texas A&M over Saint Mary's majority) |
| #2 Houston vs #15 Idaho | **Houston** | 7-0 | |

### Round of 32 (16 games)

#### East
| Matchup | Winner | Vote | Notes |
|---------|--------|------|-------|
| #1 Duke vs #8 Ohio State | **Duke** | 6-1 | |
| #5 St. John's vs #4 Kansas | **St. John's** | 6-1 | UPSET (61.8 score) — St. John's over Kansas |
| #11 USF vs #3 Michigan State | **USF** | 4-3 | Cinderella run continues |
| #7 UCLA vs #2 UConn | **UCLA** | 5-2 | UPSET (54.1 score) |

#### West
| Matchup | Winner | Vote | Notes |
|---------|--------|------|-------|
| #1 Arizona vs #9 Utah State | **Arizona** | 5-2 | |
| #5 Wisconsin vs #4 Arkansas | **Wisconsin** | 5-2 | UPSET (54.1 score) |
| #11 Texas vs #3 Gonzaga | **Texas** | 4-3 | Cinderella continues |
| #7 Miami FL vs #2 Purdue | **Purdue** | 5-2 | Miami FL's run ends |

#### Midwest
| Matchup | Winner | Vote | Notes |
|---------|--------|------|-------|
| #1 Michigan vs #9 Saint Louis | **Michigan** | 5-2 | |
| #12 Akron vs #4 Alabama | **Akron** | 4-3 | 12-seed continues! |
| #6 Tennessee vs #3 Virginia | **Tennessee** | 5-2 | |
| #10 Santa Clara vs #2 Iowa State | **Iowa State** | 4-3 | |

#### South
| Matchup | Winner | Vote | Notes |
|---------|--------|------|-------|
| #1 Florida vs #8 Clemson | **Florida** | 6-1 | |
| #5 Vanderbilt vs #4 Nebraska | **Vanderbilt** | 4-3 | UPSET (50.4 score) |
| #11 VCU vs #3 Illinois | **VCU** | 4-3 | UPSET — 11-seed in S16 (43.4 score) |
| #10 Texas A&M vs #2 Houston | **Houston** | 5-2 | |

### Sweet 16 (8 games)
| Matchup | Winner | Vote | Notes |
|---------|--------|------|-------|
| #1 Duke vs #5 St. John's | **Duke** | 4-3 | Tight game |
| #11 USF vs #7 UCLA | **USF** | 5-2 | 11-seed in Elite 8! |
| #1 Arizona vs #5 Wisconsin | **Arizona** | 5-2 | |
| #11 Texas vs #2 Purdue | **Purdue** | 5-2 | Texas run ends |
| #1 Michigan vs #12 Akron | **Michigan** | 4-3 | Akron's Cinderella ends |
| #6 Tennessee vs #2 Iowa State | **Iowa State** | 5-2 | |
| #1 Florida vs #5 Vanderbilt | **Vanderbilt** | 5-2 | UPSET (55.1) — Vandy beats #1 seed |
| #11 VCU vs #2 Houston | **Houston** | 4-3 | VCU's run ends |

### Elite 8 (4 games)
| Matchup | Winner | Vote | Key Insight |
|---------|--------|------|-------------|
| #1 Duke vs #11 USF | **Duke** | 4-3 (USF led vote) | Conductor override — math favored Duke despite USF vote lead. Duke's efficiency gap too wide. |
| #1 Arizona vs #2 Purdue | **Arizona** | 4-3 (Purdue led vote) | Conductor override — Arizona's defense (39.2% opp FG%) and health advantage over banged-up Purdue |
| #1 Michigan vs #2 Iowa State | **Michigan** | 4-3 | Iron Curtain decisive — Michigan's offensive efficiency edge (126.3 vs 124.9) in identical-tempo game |
| #5 Vanderbilt vs #2 Houston | **Vanderbilt** | 6-1 | Iron Curtain + tournament momentum. "VCU's Cinderella profile matches 2011 Final Four run" — Oracle |

---

## Cinderella Runs

### #5 Vanderbilt (to Championship Game)
**Path: McNeese → Nebraska → Florida (#1) → Houston (#2) → Michigan (#1) → lost to Arizona**
- Beat three higher seeds including a #1 and #2
- Oracle compared to 1985 Villanova and 2014 UConn
- Key strength: 7.0/10 experience score, elite defense, veteran backcourt (Duke Miles)
- Iron Curtain was their biggest advocate throughout

### #11 USF (to Elite 8)
- Beat #6 Louisville (7-0 unanimous) → #3 Michigan State (4-3) → #7 UCLA (5-2) → lost to #1 Duke (4-3)
- Veteran guards (7.0/10 experience) vs Duke's freshman-heavy lineup

### #11 VCU (to Sweet 16)
- Beat #6 UNC (7-0 unanimous, 64.4 upset score) → #3 Illinois (4-3) → lost to #2 Houston (4-3)
- Matched 2011 VCU Final Four profile per Oracle

### #12 Akron (to Sweet 16)
- Beat #5 Texas Tech (6-1) → #4 Alabama (4-3) → lost to #1 Michigan (4-3)

### #11 Texas (to Sweet 16)
- Beat #6 BYU (4-3, conductor override) → #3 Gonzaga (4-3) → lost to #2 Purdue (5-2)

---

## R64 Calibration Report

| Matchup | Upsets | Expected | Status |
|---------|--------|----------|--------|
| 1v16 | 0/4 | ~0% (0/4) | OK |
| 2v15 | 0/4 | ~6% (0/4) | OK |
| 3v14 | 0/4 | ~15% (0/4) | OK |
| 4v13 | 0/4 | ~21% (1/4) | LOW |
| 5v12 | 1/4 | ~36% (1/4) | OK |
| 6v11 | 3/4 | ~38% (1/4) | OK |
| 7v10 | 2/4 | ~39% (1/4) | OK |
| 8v9 | 2/4 | ~49% (2/4) | OK |
| **TOTAL** | **8/32** | **7-10** | **OK** |

8 upsets in R64 — within the historical expected range of 7-10. Only flag: 4v13 produced 0 upsets vs 1 expected (slightly low but within variance).

---

## Monte Carlo Championship Probabilities

10,000 bracket simulations from R64 probabilities:

| Rank | Team | Seed | Region | Win Championship |
|------|------|------|--------|-----------------|
| 1 | Duke | #1 | East | 4.14% |
| 2 | Houston | #2 | South | 3.69% |
| 3 | Arizona | #1 | West | 3.68% |
| 4 | Michigan | #1 | Midwest | 3.64% |
| 5 | Florida | #1 | South | 3.45% |
| 6 | Purdue | #2 | West | 3.35% |
| 7 | UConn | #2 | East | 3.03% |
| 8 | Iowa State | #2 | Midwest | 2.93% |
| 9 | Gonzaga | #3 | West | 2.91% |
| 10 | Michigan State | #3 | East | 2.65% |

Monte Carlo Cinderella Watch:
- Any 12+ seed reaches S16: **96.1%**
- Any 9-16 seed reaches F4: **73.3%**
- Top Cinderella: Akron (#12) S16: 26.2%

---

## Upset Watch — Top 19 Flagged Games

| Score | Matchup | Round | Pick |
|-------|---------|-------|------|
| 67.2 | #8 Villanova vs #9 Utah State | R64 | Utah State |
| 64.4 | #6 UNC vs #11 VCU | R64 | VCU |
| 61.8 | #5 St. John's vs #4 Kansas | R32 | St. John's |
| 60.4 | #8 Georgia vs #9 Saint Louis | R64 | Saint Louis |
| 57.4 | #6 Louisville vs #11 USF | R64 | USF |
| 55.1 | #1 Florida vs #5 Vanderbilt | S16 | Vanderbilt |
| 54.1 | #7 UCLA vs #2 UConn | R32 | UCLA |
| 54.1 | #5 Wisconsin vs #4 Arkansas | R32 | Wisconsin |
| 51.2 | #5 Texas Tech vs #12 Akron | R64 | Akron |
| 50.4 | #5 Vanderbilt vs #4 Nebraska | R32 | Vanderbilt |
| 50.4 | #11 USF vs #7 UCLA | S16 | USF |
| 49.4 | #6 Tennessee vs #3 Virginia | R32 | Tennessee |
| 48.1 | #5 Vanderbilt vs #2 Houston | E8 | Vanderbilt |
| 47.5 | #6 Tennessee vs #11 Miami OH | R64 | Tennessee |
| 47.1 | #5 Vanderbilt vs #1 Michigan | F4 | Vanderbilt |
| 45.4 | #7 Kentucky vs #10 Santa Clara | R64 | Santa Clara |
| 43.4 | #11 VCU vs #3 Illinois | R32 | VCU |
| 43.3 | #8 Clemson vs #9 Iowa | R64 | Clemson |
| 40.2 | #6 BYU vs #11 Texas | R64 | Texas |

---

## System Behavior & Key Metrics

### Conductor Overrides (5/63 = 7.9%)
All 5 occurred in R64 on close games where mathematical probability combination disagreed with the slim vote majority:
1. **Texas over BYU** (vote was 4-3 BYU) — injury factor
2. **Miami FL over Missouri** (vote was 4-3 Missouri) — efficiency edge
3. **Vanderbilt over McNeese** (vote was 4-3 McNeese) — shooting analysis
4. **Nebraska over Troy** (vote was 4-3 Troy) — pace advantage
5. **Texas A&M over Saint Mary's** (vote was 4-3 Saint Mary's) — shooting edge

Note: 1 additional override was **blocked** — Conductor tried to pick UCF over a 5-2 UCLA majority and was force-corrected.

### Adaptive R2 Skips (11/63 = 17.5%)
When R1 vote is unanimous AND seed differential is 11+, Round 2 cross-examination is skipped to save cost. All 11 were blowout matchups (1v16, 2v15, 3v14 type games).

### Agent Performance
| Agent | Model | Avg Response | Position Changes | Cost |
|-------|-------|-------------|-----------------|------|
| Glass Cannon | Gemini | 1155ms | 19 | $0.07 |
| Iron Curtain | Claude | 7834ms | 14 | $17.63 |
| Oracle | Claude | 8370ms | 22 | $17.64 |
| Road Dog | Gemini | 1207ms | 17 | $0.07 |
| Streak | Gemini | 2412ms | 17 | $0.07 |
| Tempo Hawk | Claude | 8160ms | 16 | $17.08 |
| Whisper | Gemini | 1282ms | 25 | $0.07 |

- **Most influential agent**: Iron Curtain (weighted most by Conductor in E8, F4, NCG)
- **Most volatile**: Whisper (25 position changes — changed mind most in R2)
- **Most stable**: Iron Curtain (14 position changes — held ground)
- **Oracle** had 22 position changes — historical patterns sometimes clashed with current data

### Cost Breakdown
- **Total: $26.84** (27% of $100 budget)
- Claude Sonnet 4: 1.33M input / 90K output tokens = $26.63
- Gemini 2.5 Flash: 1.48M input / 66K output tokens = $0.21
- 881 total API calls across 63 games

---

## Late-Round Conductor Verdicts

### Elite 8

**Duke over USF (East)**: "Oracle and Iron Curtain won this debate — Duke's 39.6 offensive efficiency margin is simply too wide for USF to overcome. Road Dog's experience argument for USF was compelling but efficiency wins in March."

**Arizona over Purdue (West)**: "Iron Curtain won — Arizona's 39.2% opponent FG% and health advantage overcome Purdue's marginal efficiency edge. Purdue's banged-up rotation can't sustain 40 minutes against Arizona's depth."

**Michigan over Iowa State (Midwest)**: "Iron Curtain decisive — near-identical tempos (70-71) mean this is decided by Michigan's offensive efficiency edge (126.3 vs 124.9). Iowa State's defense is elite but Michigan's firepower is slightly better."

**Vanderbilt over Houston (South)**: "Iron Curtain and Streak won — elite defense plus tournament momentum beats Houston's youth. Vanderbilt held three top offenses under 65 points. The Commodores' Cinderella run continues."

### Final Four

**Arizona over Duke**: "Iron Curtain and Tempo Hawk won — Arizona's depth and pace control trump Duke's shooting edge. Road Dog, Oracle, and Streak all weakened their Duke positions after cross-examination, recognizing Arizona's health advantage matters more. This is a coin flip decided by availability."

**Vanderbilt over Michigan**: "Iron Curtain and Streak won — elite defense plus momentum beats youth. Oracle's flip to Michigan based on historical patterns was compelling but overruled by Vanderbilt's current 4-game NCAA streak. Glass Cannon's shooting variance argument couldn't overcome defensive suffocation. The Commodores' Final Four run continues."

### Championship

**Arizona over Vanderbilt**: "Iron Curtain and Streak won this debate — defense beats shooting variance, momentum matters. Glass Cannon flipped after realizing Vandy's recent 29% three-point shooting negates their season average. Road Dog's experience argument can't overcome Arizona's superior talent and current form. The house always wins."

---

## Architecture Quick Reference

- **Engine**: `swarm_engine.py` (3200+ lines) — orchestrates all debates
- **Monte Carlo**: `monte_carlo.py` — 10,000 bracket simulations
- **Market Analysis**: `market_analyzer.py` — Vegas odds comparison, Kelly criterion
- **Memory**: `agent_memory.py` — tracks agent accuracy across rounds (empty in prediction mode)
- **Observability**: `observability.py` — Brier scores, calibration curves, performance tracking
- **Cost Guard**: `cost_guard.py` — budget enforcement, prompt injection protection
- **Database**: Supabase (mm_games, mm_agent_votes, mm_monte_carlo tables)
- **Models**: Claude Sonnet 4 (Iron Curtain, Oracle, Tempo Hawk) + Gemini 2.5 Flash (Glass Cannon, Road Dog, Streak, Whisper)
- **Response Cache**: `.response_cache/` — 568 cached API responses for debugging
- **Debate Transcripts**: `debates/` — 66 markdown files with full agent arguments

### Key Design Decisions
1. **Math over vibes**: Final pick = weighted probability combination, not vote counting
2. **Feature-driven weighting**: Agent weights change per game based on which factors matter most
3. **Anti-convergence**: Devil's advocate on unanimous votes, adaptive R2 skipping on blowouts
4. **Multi-model diversity**: Claude + Gemini prevents single-model groupthink
5. **Confidence calibration**: Conductor has hard caps (8v9 = 50-55%, only 85%+ on 1v16 type)

---

*Generated by March Madness Agent Swarm v2 | Tournament ID: 3e52e2dd-1c70-441c-b46c-766e7b0ee28f*
*Git: github.com/callensw/2026-march-madness*
