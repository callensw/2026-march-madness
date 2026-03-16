#!/usr/bin/env python3
"""
Test suite for March Madness Agent Swarm orchestration v2.
Covers: structured output, agent diversity, bracket progression,
upset scoring, agent memory, multi-model, and debate transcripts.
"""

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))

from swarm_engine import (
    AgentVote,
    ConductorDecision,
    Game,
    GameDebate,
    UpsetScore,
    advance_bracket,
    build_agents,
    build_conductor_prompt,
    calculate_upset_score,
    fuzzy_match_team,
    generate_debate_transcript,
    make_sample_games,
    parse_agent_response,
    run_agent,
    run_conductor,
    analyze_game,
    cost_tracker,
    ROUND_NAMES,
)
import supabase_client


class TestResult:
    def __init__(self, name: str):
        self.name = name
        self.passed = False
        self.error = ""
        self.duration = 0.0

    def __repr__(self):
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {self.name} ({self.duration:.2f}s)" + (
            f"\n       {self.error}" if self.error else ""
        )


results: list[TestResult] = []


def test(name):
    def decorator(func):
        async def wrapper():
            t = TestResult(name)
            start = time.monotonic()
            try:
                if asyncio.iscoroutinefunction(func):
                    await func(t)
                else:
                    func(t)
                if not t.error:
                    t.passed = True
            except Exception as e:
                t.error = str(e)
            t.duration = time.monotonic() - start
            results.append(t)
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Core tests (from v1)
# ---------------------------------------------------------------------------

@test("Agent configs are valid and distinct")
def test_agent_configs(t: TestResult):
    agents = build_agents()
    assert len(agents) == 7, f"Expected 7 agents, got {len(agents)}"
    names = [a.name for a in agents]
    assert len(set(names)) == 7, "Agent names not unique"

    prompts = [a.system_prompt for a in agents]
    for i, p1 in enumerate(prompts):
        for j, p2 in enumerate(prompts):
            if i < j:
                overlap = len(set(p1.split()) & set(p2.split())) / max(len(p1.split()), len(p2.split()))
                assert overlap < 0.6, f"{names[i]} and {names[j]} prompts {overlap:.0%} similar"

    temps = {a.name: a.temperature for a in agents}
    assert temps["Glass Cannon"] > temps["Tempo Hawk"]
    assert temps["Whisper"] > temps["Oracle"]


@test("Multi-model agent assignment")
def test_multi_model(t: TestResult):
    agents = build_agents(multi_model=True)
    claude_agents = [a for a in agents if a.model == "claude"]
    gemini_agents = [a for a in agents if a.model == "gemini"]
    assert len(claude_agents) == 3, f"Expected 3 Claude agents, got {len(claude_agents)}"
    assert len(gemini_agents) == 4, f"Expected 4 Gemini agents, got {len(gemini_agents)}"
    # Verify analytical agents stay on Claude
    claude_names = {a.name for a in claude_agents}
    assert "Tempo Hawk" in claude_names, "Tempo Hawk should be on Claude"
    assert "Oracle" in claude_names, "Oracle should be on Claude"


@test("JSON parsing handles clean JSON (probabilistic)")
def test_parse_clean(t: TestResult):
    # New probabilistic format
    raw = '{"team_a_win_prob": 0.72, "uncertainty": 0.08, "reasoning": "Strong defense.", "key_stat": "adj_d: 89.2"}'
    result = parse_agent_response(raw, "Duke", "Michigan")
    assert result is not None
    assert result["pick"] == "Duke"  # >0.5 = team_a
    assert result["team_a_win_prob"] == 0.72
    # Legacy format still works
    raw2 = '{"pick": "Duke", "confidence": 82, "reasoning": "Strong defense.", "key_stat": "adj_d: 89.2"}'
    result2 = parse_agent_response(raw2, "Duke", "Michigan")
    assert result2 is not None
    assert result2["pick"] == "Duke"


@test("JSON parsing handles wrapped JSON")
def test_parse_wrapped(t: TestResult):
    raw = 'Analysis:\n\n{"team_a_win_prob": 0.35, "uncertainty": 0.10, "reasoning": "Good shooting.", "key_stat": "3PT: 38%"}\n\nDone.'
    result = parse_agent_response(raw, "Duke", "Michigan")
    assert result is not None
    assert result["pick"] == "Michigan"  # 0.35 < 0.5 = team_b


@test("Confidence clamped 50-99")
def test_confidence_clamp(t: TestResult):
    raw = '{"pick": "Duke", "confidence": 105, "reasoning": "Lock.", "key_stat": "KenPom #1"}'
    r = parse_agent_response(raw, "Duke", "Michigan")
    assert r["confidence"] == 99

    raw2 = '{"pick": "Duke", "confidence": 30, "reasoning": "Weak.", "key_stat": "adj_d 91"}'
    r2 = parse_agent_response(raw2, "Duke", "Michigan")
    assert r2["confidence"] == 50


@test("Confidence penalty for vague key_stat")
def test_vague_penalty(t: TestResult):
    raw = '{"pick": "Duke", "confidence": 85, "reasoning": "Vibes.", "key_stat": "overall feeling"}'
    r = parse_agent_response(raw, "Duke", "Michigan")
    assert r["confidence"] <= 69


@test("Fuzzy matching team names")
def test_fuzzy_match(t: TestResult):
    assert fuzzy_match_team("Duke", "Duke", "Michigan") == "Duke"
    assert fuzzy_match_team("Blue Devils (Duke)", "Duke", "Michigan") == "Duke"
    assert fuzzy_match_team("Dukee", "Duke", "Michigan") == "Duke"
    assert fuzzy_match_team("XYZABC", "Duke", "Michigan") is None


@test("Invalid pick rejected")
def test_invalid_pick(t: TestResult):
    raw = '{"pick": "Kansas", "confidence": 70, "reasoning": "Good.", "key_stat": "25-6"}'
    r = parse_agent_response(raw, "Duke", "Michigan")
    assert r is None


# ---------------------------------------------------------------------------
# New v2 tests
# ---------------------------------------------------------------------------

@test("Upset score calculation — blowout")
def test_upset_score_blowout(t: TestResult):
    game = make_sample_games()[0]  # 1 vs 16
    votes = [
        AgentVote("A", game.team_a, 85, "Lock", "stat"),
        AgentVote("B", game.team_a, 90, "Lock", "stat"),
        AgentVote("C", game.team_a, 88, "Lock", "stat"),
        AgentVote("D", game.team_a, 92, "Lock", "stat"),
    ]
    score = calculate_upset_score(game, votes)
    assert score is not None
    assert score.score < 15, f"1v16 blowout should have low upset score, got {score.score}"


@test("Upset score calculation — toss-up")
def test_upset_score_tossup(t: TestResult):
    game = make_sample_games()[1]  # 5 vs 12
    votes = [
        AgentVote("A", game.team_a, 65, "Slight edge", "stat"),
        AgentVote("B", game.team_b, 72, "Underdog case", "stat"),
        AgentVote("C", game.team_b, 68, "Shooting edge", "stat"),
        AgentVote("D", game.team_a, 60, "Slight lean", "stat"),
        AgentVote("E", game.team_b, 75, "Strong case", "stat"),
        AgentVote("F", game.team_a, 55, "Coin flip", "stat"),
    ]
    score = calculate_upset_score(game, votes)
    assert score is not None
    assert score.score > 30, f"5v12 with 3 agents on underdog should be >30, got {score.score}"


@test("Agent memory context passed to agents")
async def test_agent_memory(t: TestResult):
    agents = build_agents()
    game = make_sample_games()[0]
    memory = {
        "Tempo Hawk": [
            "R64: picked Duke (80%) in #1 Duke vs #16 American",
            "R64: picked Michigan (72%) in #5 Michigan vs #12 UCF",
        ]
    }

    async with httpx.AsyncClient() as client:
        vote = await run_agent(
            client, agents[0], game, dry_run=True,
            memory_context="\n".join(memory["Tempo Hawk"]),
        )
    assert not vote.error, f"Agent with memory failed: {vote.error}"
    assert vote.pick in (game.team_a, game.team_b)


@test("Bracket progression — R64 to R32")
def test_bracket_progression(t: TestResult):
    games = make_sample_games()
    # Simulate 2 completed debates in same region
    debates = []
    for g in games[:2]:
        d = GameDebate(
            game=g,
            votes=[],
            conductor=ConductorDecision(pick=g.team_a, confidence=75, reasoning="Test"),
            timestamp="2026-03-15T00:00:00Z",
        )
        debates.append(d)

    # Both need to be in same region for pairing to work
    debates[0].game.region = "East"
    debates[1].game.region = "East"

    next_games = advance_bracket(debates, "R64")
    # With 2 games in same region, we should get 1 R32 game
    assert len(next_games) == 1, f"Expected 1 R32 game, got {len(next_games)}"
    assert next_games[0].round_name == "R32"
    assert next_games[0].team_a == debates[0].game.team_a  # winner of game 1
    assert next_games[0].team_b == debates[1].game.team_a  # winner of game 2


@test("All 7 agents produce valid votes (dry-run)")
async def test_all_agents_vote(t: TestResult):
    agents = build_agents()
    game = make_sample_games()[1]

    async with httpx.AsyncClient() as client:
        tasks = [run_agent(client, a, game, dry_run=True) for a in agents]
        votes = await asyncio.gather(*tasks)

    valid = [v for v in votes if not v.error and v.pick]
    t.error = "" if len(valid) == 7 else f"Only {len(valid)}/7 valid"
    for v in valid:
        assert v.pick in (game.team_a, game.team_b)
        assert 50 <= v.confidence <= 99
        assert v.reasoning
        assert 0.0 < v.win_probability < 1.0
        assert 0.0 <= v.uncertainty <= 0.20


@test("Conductor produces valid decision (dry-run)")
async def test_conductor(t: TestResult):
    agents = build_agents()
    game = make_sample_games()[1]

    async with httpx.AsyncClient() as client:
        tasks = [run_agent(client, a, game, dry_run=True) for a in agents]
        votes = await asyncio.gather(*tasks)

    valid = [v for v in votes if not v.error and v.pick]
    async with httpx.AsyncClient() as client:
        decision = await run_conductor(client, game, valid, {}, dry_run=True)

    assert decision.pick in (game.team_a, game.team_b)
    assert 50 <= decision.confidence <= 99
    assert decision.reasoning


@test("Full pipeline — 3 games (dry-run)")
async def test_full_pipeline(t: TestResult):
    agents = build_agents()
    games = make_sample_games()

    async with httpx.AsyncClient() as client:
        for i, game in enumerate(games):
            debate = await analyze_game(
                client, game, agents, {}, i + 1, len(games), dry_run=True,
                agent_memory={},
            )
            assert debate.conductor is not None
            assert debate.conductor.pick in (game.team_a, game.team_b)
            valid = [v for v in debate.votes if not v.error]
            assert len(valid) >= 4

            # Verify upset score was calculated
            assert debate.upset_score is not None or game.seed_a == game.seed_b


@test("Debate transcript includes both rounds and probability")
async def test_transcript(t: TestResult):
    agents = build_agents()
    game = make_sample_games()[1]  # 5v12 — should have upset score

    async with httpx.AsyncClient() as client:
        debate = await analyze_game(client, game, agents, {}, 1, 1, dry_run=True)

    transcript = generate_debate_transcript(debate)
    assert len(transcript) > 200
    assert game.team_a in transcript
    assert game.team_b in transcript
    assert "Round 1" in transcript
    assert "Round 2" in transcript
    assert "Cross-Examination" in transcript
    assert "Conductor" in transcript
    assert "Vote Tally" in transcript


@test("Round 2 cross-examination produces valid responses (dry-run)")
async def test_round2(t: TestResult):
    from swarm_engine import run_agent_round2, format_round1_outputs
    agents = build_agents()
    game = make_sample_games()[1]

    async with httpx.AsyncClient() as client:
        # Run Round 1
        tasks = [run_agent(client, a, game, dry_run=True) for a in agents]
        r1_votes = await asyncio.gather(*tasks)

    valid_r1 = [v for v in r1_votes if not v.error]
    r1_summary = format_round1_outputs(valid_r1, game)
    assert len(r1_summary) > 100, "Round 1 summary should be substantial"

    # Run Round 2
    async with httpx.AsyncClient() as client:
        r2_tasks = [run_agent_round2(client, a, game, r1_summary, dry_run=True) for a in agents]
        r2_votes = await asyncio.gather(*r2_tasks)

    valid_r2 = [v for v in r2_votes if not v.error]
    assert len(valid_r2) >= 5, f"Only {len(valid_r2)} valid Round 2 responses"
    for v in valid_r2:
        assert v.round_number == 2
        assert v.position_change in ("strengthened", "weakened", "flipped", "unchanged")
        assert 0.0 < v.win_probability < 1.0

    # At least 1 agent should change position in mocks
    changes = [v for v in valid_r2 if v.position_change in ("weakened", "flipped")]
    assert len(changes) >= 1, "Expected at least 1 position change in Round 2"


@test("Probability combination math")
def test_combine_probs(t: TestResult):
    from swarm_engine import combine_probabilities
    votes = [
        AgentVote("A", "Duke", 70, "R", win_probability=0.70, uncertainty=0.05),
        AgentVote("B", "Duke", 60, "R", win_probability=0.60, uncertainty=0.10),
        AgentVote("C", "Michigan", 65, "R", win_probability=0.35, uncertainty=0.12),
    ]
    prob, unc = combine_probabilities(votes, {})
    # Weighted avg of [0.70, 0.60, 0.35] = 0.55
    assert 0.45 < prob < 0.65, f"Expected ~0.55, got {prob}"
    assert unc > 0.05, f"Uncertainty should reflect disagreement, got {unc}"


@test("Monte Carlo simulation produces valid results")
def test_monte_carlo(t: TestResult):
    from monte_carlo import GameProb, TeamSim, simulate_bracket
    # Use all 4 regions (2 games each) so F4/NCG paths exist
    regions = ["East", "West", "South", "Midwest"]
    test_games = []
    all_team_names = []
    for ri, region in enumerate(regions):
        base = ri * 4
        teams = [
            (f"T{base+1}", 1, region, 5 + ri), (f"T{base+2}", 16, region, 200 + ri),
            (f"T{base+3}", 8, region, 30 + ri), (f"T{base+4}", 9, region, 40 + ri),
        ]
        all_team_names.extend([t[0] for t in teams])
        probs_r = [0.95, 0.52]
        for gi in range(2):
            n1, s1, r1, k1 = teams[gi * 2]
            n2, s2, r2, k2 = teams[gi * 2 + 1]
            t_a = TeamSim(n1, s1, r1, k1)
            t_b = TeamSim(n2, s2, r2, k2)
            test_games.append(GameProb(f"test_{ri}_{gi}", t_a, t_b, probs_r[gi], "R64"))

    result = simulate_bracket(test_games, n_sims=1000, seed=42)

    # 1-seeds should advance to R32 more often than 16-seeds
    assert result.advancement_probs["T1"].get("R32", 0) > 0.90, "1-seed should advance ~95% of time"
    assert result.advancement_probs["T2"].get("R32", 0) < 0.15, "16-seed should rarely advance"
    # S16 probabilities should favor top seeds
    assert result.advancement_probs["T1"].get("S16", 0) > result.advancement_probs["T2"].get("S16", 0)
    # Upset stats should exist for R64
    assert "R64" in result.upset_stats
    assert result.upset_stats["R64"]["expected"] >= 0


@test("Supabase client initializes and status.json works")
def test_supabase_graceful(t: TestResult):
    # Status.json should always work (file-based)
    supabase_client.write_status({"test": True})
    assert (Path(__file__).parent / "status.json").exists()
    # Client may or may not be available depending on env
    client = supabase_client.get_client()
    if client is None:
        # No credentials: writes should return False gracefully
        ok = supabase_client.write_game_result({"id": "test"})
        assert ok is False


@test("Response time measurement")
async def test_response_times(t: TestResult):
    agents = build_agents()
    game = make_sample_games()[0]
    async with httpx.AsyncClient() as client:
        for agent in agents:
            vote = await run_agent(client, agent, game, dry_run=True)
            assert vote.response_time > 0
            assert vote.response_time < 5


@test("Cost tracker accumulates correctly")
def test_cost_tracker(t: TestResult):
    assert cost_tracker.all_calls > 0
    assert cost_tracker.total_input_tokens > 0
    assert cost_tracker.total_cost >= 0


@test("Odds tracker module loads")
def test_odds_tracker(t: TestResult):
    from odds_tracker import (
        american_to_implied_prob,
        spread_to_implied_prob,
        compare_swarm_to_vegas,
    )
    # -150 favorite ≈ 60% implied
    prob = american_to_implied_prob(-150)
    assert 0.55 < prob < 0.65, f"Expected ~0.60, got {prob}"

    # 3-point spread ≈ 59% implied
    prob2 = spread_to_implied_prob(-3)
    assert 0.55 < prob2 < 0.65, f"Expected ~0.59, got {prob2}"


@test("Live tracker module loads")
def test_live_tracker(t: TestResult):
    from live_tracker import _make_key, _fuzzy_key
    key = _make_key("Duke", "Michigan")
    assert "|" in key
    # Consistent regardless of order
    assert _make_key("Duke", "Michigan") == _make_key("Michigan", "Duke")


@test("Gemini client module loads")
def test_gemini_client(t: TestResult):
    from gemini_client import is_gemini_available
    # Should return a boolean (True if key configured, False if not)
    result = is_gemini_available()
    assert isinstance(result, bool), f"Expected bool, got {type(result)}"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
async def run_all_tests():
    print("=" * 60)
    print("March Madness Agent Swarm v2 — Test Suite")
    print("=" * 60)
    print()

    test_funcs = [
        test_agent_configs,
        test_multi_model,
        test_parse_clean,
        test_parse_wrapped,
        test_confidence_clamp,
        test_vague_penalty,
        test_fuzzy_match,
        test_invalid_pick,
        test_upset_score_blowout,
        test_upset_score_tossup,
        test_agent_memory,
        test_bracket_progression,
        test_all_agents_vote,
        test_conductor,
        test_full_pipeline,
        test_transcript,
        test_round2,
        test_combine_probs,
        test_monte_carlo,
        test_supabase_graceful,
        test_response_times,
        test_cost_tracker,
        test_odds_tracker,
        test_live_tracker,
        test_gemini_client,
    ]

    for func in test_funcs:
        await func()
        print(f"  {results[-1]}")

    print()
    print("=" * 60)
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    print(f"Results: {passed}/{total} passed")
    total_time = sum(r.duration for r in results)
    print(f"Total time: {total_time:.2f}s")
    print(f"{cost_tracker.summary()}")

    if passed < total:
        print(f"\nFailed:")
        for r in results:
            if not r.passed:
                print(f"  {r}")

    print("=" * 60)
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
