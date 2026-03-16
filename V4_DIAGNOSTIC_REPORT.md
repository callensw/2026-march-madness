# V4 Production Run Diagnostic Report

**Run Date:** 2026-03-16
**Games Analyzed:** 63
**Total Time:** 1519.4s (24.1s per game)
**API Calls:** 883 | Est. cost: $29.22
**Predicted Champion:** Arizona (1-seed) at 50% confidence

---

## Final Four

| Seed | Team | Region |
|------|------|--------|
| #1 | Duke | East |
| #1 | Arizona | West |
| #2 | Iowa State | Midwest |
| #5 | Vanderbilt | South |

**Championship:** Arizona over Vanderbilt (4-3 vote, 50% confidence)

---

## Red Flag Checklist

### 1. Iron Curtain Dominance — IMPROVED

Late-round key factors now rotate across games:

| Round | Game | Key Factor |
|-------|------|------------|
| E8 | Duke vs Michigan State | Experience gap in high-pressure Elite Eight environment |
| E8 | Arizona vs Gonzaga | Pace control negating shooting variance |
| E8 | Michigan vs Iowa State | Net efficiency advantage in identical tempo matchup |
| E8 | Vanderbilt vs VCU | Interior size advantage with Krivas controlling the paint |
| F4 | Duke vs Arizona | Pace control neutralizing talent differential |
| F4 | Vanderbilt vs Iowa State | Offensive efficiency gap |
| NCG | Arizona vs Vanderbilt | Veteran experience vs freshman talent in championship pressure |

Iron Curtain's defense lens is no longer the dominant factor in 4/5 late games. The rotation fix (0.5x weight on previously most-weighted agent) is forcing genuine diversity in the Conductor's primary analytical lens.

### 2. Conductor Override Direction — IMPROVED

6 overrides total (was 5 in v3). Override breakdown:

| Game | Majority Pick | Conductor Override | Direction |
|------|--------------|-------------------|-----------|
| Tennessee vs Miami OH | Miami OH (4-3) | Tennessee | **UPSET** |
| Michigan State vs USF | USF (5-2) | Michigan State | Chalk |
| BYU vs Gonzaga | BYU (4-3) | Gonzaga | Chalk |
| Duke vs St. John's | St. John's (4-3) | Duke | Chalk |
| Duke vs Michigan State | Michigan State (4-3) | Duke | Chalk |
| Arizona vs Gonzaga | Gonzaga (4-3) | Arizona | Chalk |

**Result:** 5 chalk / 1 upset (was 5/0 in v3). Still skews chalk but no longer exclusively one-directional. The symmetry rule helped produce at least one upset-direction override.

### 3. Vanderbilt — STILL IN FINAL FOUR (but less dominant)

Vanderbilt's path this run:

| Round | Opponent | Vote | Confidence |
|-------|----------|------|------------|
| R64 | McNeese | — | 50% |
| R32 | Nebraska | — | 50% |
| S16 | Florida (#1) | — | 50% |
| E8 | VCU (#11) | — | 50% |
| F4 | Iowa State (#2) | — | 50% |
| NCG | Arizona (#1) | **LOST** | 50% |

**Key difference from v3:** Vote margins are now tighter (5-2, 4-3) rather than the previous 6-1 lopsided votes against Houston and Michigan. Vanderbilt also **lost the championship** rather than winning it all.

**Assessment:** Vanderbilt is KenPom 11 with a 7.0/10 experience score — they're a legitimate Final Four contender regardless of their 5-seed. The conference tournament regression warning reduced the lopsided votes but didn't (and arguably shouldn't) eliminate them. This is probably an acceptable outcome.

### 4. Oracle Hallucination Guard — WORKING (with false positives)

**27 hallucination warnings caught** across the run.

Legitimate catches (3):
- Oracle mentioned "VCU" in Ohio State vs TCU game
- Oracle mentioned "VCU" in Clemson vs Iowa game
- Oracle mentioned "VCU" in Vanderbilt vs Iowa State game (the exact bug from v3)

False positives (~24):
- Most are "UNC" appearing in games involving UConn — agents legitimately reference historical UConn teams (e.g., "2014 UConn") but the confusable pair flags it
- Some "Michigan" references in non-Michigan games where agents cite Michigan as a historical example

**Action needed:** The `unc`/`uconn` confusable pair is too aggressive. Should either remove it or add context-awareness (don't flag if preceded by a year like "2014 UConn").

### 5. 4v13 Upsets — STILL 0/4

| 4-seed | 13-seed | Winner | Vote |
|--------|---------|--------|------|
| Kansas | Cal Baptist | Kansas | — |
| Arkansas | Hawaii | Arkansas | — |
| Alabama | Hofstra | Alabama | — |
| Nebraska | Troy | Nebraska | — |

The Oracle 4v13 calibration check was added, but none of these 13-seeds appear to match the strong Cinderella archetype (conference champ + 25W + good 3PT%). Calibration report flags this as `[LOW]` but 0/4 is within 1 standard deviation of the expected 0.84 upsets per tournament.

### 6. Final Four 1-Seeds — IMPROVED (2, not 3)

| v3 Final Four | v4 Final Four |
|---------------|---------------|
| Duke (#1) | Duke (#1) |
| Arizona (#1) | Arizona (#1) |
| Michigan (#1) | Iowa State (#2) |
| Vanderbilt (#5) | Vanderbilt (#5) |

**Michigan (#1) now loses to Iowa State (#2) in the Elite Eight.** Only 2 one-seeds in the Final Four vs 3 before. This is much closer to the historical average of ~1.5 one-seeds. The late-round chalk check in the Conductor prompt is working.

### 7. USF vs Louisville — FIXED

| Metric | v3 | v4 |
|--------|----|----|
| Vote | 7-0 USF | 5-2 USF |
| Dissenters | None | Iron Curtain, Whisper |
| Conductor | USF | USF |
| Confidence | — | 50% |

No longer unanimous. Two agents now pick Louisville, creating a healthy debate. The devil's advocate mechanism wasn't needed because the vote wasn't unanimous.

---

## Calibration Report

```
Seed Matchup | Upsets | Expected | Status
-------------|--------|----------|-------
1v16         | 0/4    | ~0/4     | OK
2v15         | 0/4    | ~0/4     | OK
3v14         | 0/4    | ~0.6/4   | OK
4v13         | 0/4    | ~0.8/4   | LOW
5v12         | 1/4    | ~1.4/4   | OK
6v11         | 2/4    | ~1.5/4   | OK
7v10         | 2/4    | ~1.6/4   | OK
8v9          | 2/4    | ~2.0/4   | OK

TOTAL UPSETS: 7/32 (expected 7-10) — right in range
```

---

## Agent Performance

| Agent | Games | Avg Response | Position Changes | Cost |
|-------|-------|-------------|-----------------|------|
| Glass Cannon | 63 | 1.2s | 22 | $0.08 |
| Iron Curtain | 63 | 8.5s | 16 | $18.81 |
| Oracle | 63 | 10.0s | 18 | $19.59 |
| Road Dog | 63 | 1.3s | 18 | $0.08 |
| Streak | 63 | 2.3s | 14 | $0.08 |
| Tempo Hawk | 63 | 8.8s | 13 | $18.23 |
| Whisper | 63 | 1.2s | 25 | $0.08 |

- Groupthink rate: 24% (15/63 unanimous) — healthy
- Conductor overrides: 6/63 (10%)
- Full agent responses (7/7): 63/63 — no failures

---

## Remaining Issues

1. **Hallucination false positives:** `unc`/`uconn` confusable pair fires too aggressively on legitimate historical references. Needs context-awareness or removal.

2. **4v13 still 0/4:** May be bracket-specific (weak 13-seeds this year). Within statistical variance but worth monitoring.

3. **Vanderbilt persistence:** Still makes Final Four in all runs. Likely correct given their profile but worth noting as a pattern across runs.

4. **All late-round confidences at 50%:** The mathematical probability combination produces very tight margins in later rounds, resulting in 50% confidence for every game from E8 onward. May want to investigate if the weight rotation is over-dampening conviction.
