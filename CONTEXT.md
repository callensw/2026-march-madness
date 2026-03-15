# March Madness Agent Swarm 2026 — Full Context

## What This Is

7 AI agents debate every NCAA March Madness tournament game and vote on winners. The engine calls Claude/Gemini APIs for agent analysis, writes results to Supabase, and a React dashboard on Vercel visualizes the debates.

**Repo:** https://github.com/callensw/2026-march-madness
**Droplet:** DigitalOcean Ubuntu, 2GB RAM
**Project dir:** ~/march-madness-swarm/
**Python venv:** ~/march-madness-swarm/venv/ (Python 3.12)
**Node:** v22, Vercel CLI at ~/.npm-global/bin/vercel
**Supabase project:** Memphis Labs (kakjbyoxqjvwnsdbqcnb)
**Tables:** mm_tournaments, mm_teams, mm_games, mm_agent_votes, mm_agent_accuracy

## The 7 Agents

1. **Tempo Hawk** 🦅 — Pace & efficiency obsessive. Only cares about adj_o, adj_d, tempo. Temperature 0.3. Runs on Claude.
2. **Iron Curtain** 🛡️ — Defensive zealot. Borderline paranoid about defense. +10 confidence boost for top defensive teams. Temperature 0.4. Runs on Claude.
3. **Glass Cannon** 💥 — Hot-shooting believer. Pushes back on "defense wins championships." Temperature 0.9. Runs on Gemini (in multi-model mode).
4. **Road Dog** 🐺 — Old-school scout. Distrusts analytics, cares about coaching experience and "who's been there." Temperature 0.5. Runs on Gemini (in multi-model mode).
5. **Whisper** 👁️ — Conspiracy theorist / intel hunter. Reads into injury reports, press conferences, social media silence. Temperature 0.9. Runs on Gemini (in multi-model mode).
6. **Oracle** 📜 — Historical base-rate pedant. Always anchors to seed win rates. Cites specific years/examples. Temperature 0.3. Runs on Claude.
7. **The Conductor** 🎼 — Final decision maker. Weighs arguments by relevance, tracks agent accuracy, required to write dissent reports.

## File Structure

```
~/march-madness-swarm/
├── swarm_engine.py          # Main async orchestration engine (67KB)
│                              - 6 specialist agents + Conductor
│                              - Bracket progression R64 → Championship
│                              - Agent memory across rounds
│                              - Multi-model (Claude + Gemini) support
│                              - Upset confidence scoring (0-100)
│                              - Anti-convergence (devil's advocate on unanimous votes)
│                              - Structured output with retry/fuzzy matching
│                              - Vegas odds comparison integration
│                              - Cost tracking per API call
│                              - Debate transcript generation (markdown)
│
├── supabase_client.py       # DB write helpers for mm_* tables + status.json
├── gemini_client.py         # Gemini API wrapper with retry logic
├── odds_tracker.py          # Fetches Vegas lines from The Odds API, compares to swarm
├── live_tracker.py          # Polls ESPN for live scores, updates accuracy
├── backtest.py              # Runs swarm against historical brackets for calibration
├── audio_gen.py             # Converts debate transcripts to podcast audio (ElevenLabs)
├── test_orchestration.py    # 22-test validation suite (all passing)
├── scrape_teams.py          # Barttorvik scraper + ESPN injury reports
├── fill_bracket.py          # Interactive CLI to build bracket, writes to Supabase
├── start.sh                 # Launches tmux "madness" session with 3 panes
├── team_data_2026.json      # Scraped/manual team stats
├── .env                     # API keys (not in git)
│
├── dashboard/               # Vite + React dashboard
│   ├── src/
│   │   ├── components/Layout.jsx      # Dark sidebar nav
│   │   ├── lib/supabase.js            # Supabase client for mm_* tables
│   │   ├── lib/agents.js              # Agent metadata (emoji, color, role)
│   │   ├── pages/Dashboard.jsx        # Stats bar, live status, game cards
│   │   ├── pages/BracketView.jsx      # SVG bracket visualization
│   │   ├── pages/DebateView.jsx       # Chat-thread debate reader
│   │   ├── pages/AgentLeaderboard.jsx # Accuracy rankings + profile cards
│   │   └── pages/UpsetWatch.jsx       # Ranked upset candidates
│   └── vercel.json
│
├── debates/                 # Generated markdown debate transcripts
└── logs/                    # swarm.log
```

## CLI Usage

```bash
# Activate
source ~/march-madness-swarm/venv/bin/activate

# Quick test (no API calls)
python swarm_engine.py --dry-run --single-game -y

# Full bracket mock
python swarm_engine.py --dry-run --full-bracket -y

# Real run — all 63 games, Claude + Gemini
python swarm_engine.py --full-bracket --multi-model

# Run tests (22/22 passing)
python test_orchestration.py

# Backtest against historical data
python backtest.py

# Live score tracking (polls ESPN)
python live_tracker.py --watch -i 3

# Audio generation (needs ElevenLabs key)
python audio_gen.py --dry-run debates/R64_Duke_vs_American.md

# Fetch Vegas odds (needs Odds API key)
python odds_tracker.py

# tmux session
./start.sh
```

## .env Keys Needed

```
ANTHROPIC_API_KEY=sk-ant-xxxxx          # Required — Claude API
SUPABASE_URL=https://kakjbyoxqjvwnsdbqcnb.supabase.co
SUPABASE_SERVICE_KEY=eyJxxxxx           # Required — Supabase writes
GEMINI_API_KEY=AIzaxxxxx                # Optional — multi-model mode
ODDS_API_KEY=xxxxx                      # Optional — free at the-odds-api.com
ELEVENLABS_API_KEY=el-xxxxx             # Optional — audio generation
CLAUDE_MODEL=claude-sonnet-4-20250514
GEMINI_MODEL=gemini-2.0-flash
```

## Key Architecture Decisions

**Anti-convergence:** Each agent has explicit "YOU MUST DISAGREE WITH [other agent] WHEN..." sections. Agents have different temperatures (0.3 for analytical, 0.9 for volatile). Unanimous votes trigger a devil's advocate re-run. Groupthink rate is tracked and warned above 60%.

**Structured output:** 3 retries with exponential backoff. Regex fallback for JSON extraction. Fuzzy team name matching via SequenceMatcher. Confidence clamped 50-99. Vague key_stat auto-penalizes confidence to ≤69. 45s timeout per agent, graceful degradation with 4+ votes.

**Bracket progression:** Winners advance automatically. `advance_bracket()` pairs adjacent game winners within a region. Final Four pairs East vs West, South vs Midwest. Agent memory carries across rounds so agents can reference their prior picks.

**Upset scoring:** Composite 0-100 combining: vote split (40pts), historical upset rate (25pts), statistical edges (20pts), agent confidence divergence (15pts). Flagged in logs and debate transcripts when ≥40.

**Conductor weighting:** Identifies the single most important factor per game, gives 2x weight to the matching specialist. Has access to per-agent accuracy track records. Required to write dissent reports. 3-3 splits force confidence to 50-58.

**Multi-model:** `--multi-model` flag puts 3 agents on Claude, 3 on Gemini. Model-level diversity is stronger than prompt-level diversity for breaking convergence.

**Backtest finding:** Dry-run mode has 100% chalk bias (0/3 upsets detected). This is expected with deterministic mocks. With real API calls, the opinionated prompts will produce genuine disagreement. The calibration report recommends specific agent tuning.

## What's Left Before Tonight (Selection Sunday 6 PM ET)

1. Fill in real API keys in .env
2. Fill in real Supabase anon key in dashboard/.env
3. Watch bracket reveal, run `python fill_bracket.py` to enter 68 teams
4. Run `python swarm_engine.py --full-bracket --multi-model`
5. Deploy dashboard: `cd dashboard && vercel`
6. Start live tracker: `python live_tracker.py --watch`
