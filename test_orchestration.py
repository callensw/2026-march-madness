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
    assert len(agents) == 6, f"Expected 6 agents, got {len(agents)}"
    names = [a.name for a in agents]
    assert len(set(names)) == 6, "Agent names not unique"

    prompts = [a.system_prompt for a in agents]
    for i, p1 in enumerate(prompts):
        for j, p2 in enumerate(prompts):
            if i < j:
                overlap = len(set(p1.split()) & set(p2.split())) / max(len(p1.split()), len(p2.split()))
                assert overlap < 0.6, f"{names[i]} and {names[j]} prompts {overlap:.0%} similar"

    for agent in agents:
        assert "DISAGREE" in agent.system_prompt, f"{agent.name} missing DISAGREE section"

    temps = {a.name: a.temperature for a in agents}
    assert temps["Glass Cannon"] > temps["Tempo Hawk"]
    assert temps["Whisper"] > temps["Oracle"]


@test("Multi-model agent assignment")
def test_multi_model(t: TestResult):
    agents = build_agents(multi_model=True)
    claude_agents = [a for a in agents if a.model == "claude"]
    gemini_agents = [a for a in agents if a.model == "gemini"]
    assert len(claude_agents) == 3, f"Expected 3 Claude agents, got {len(claude_agents)}"
    assert len(gemini_agents) == 3, f"Expected 3 Gemini agents, got {len(gemini_agents)}"
    # Verify analytical agents stay on Claude
    claude_names = {a.name for a in claude_agents}
    assert "Tempo Hawk" in claude_names, "Tempo Hawk should be on Claude"
    assert "Oracle" in claude_names, "Oracle should be on Claude"


@test("JSON parsing handles clean JSON")
def test_parse_clean(t: TestResult):
    raw = '{"pick": "Duke", "confidence": 82, "reasoning": "Strong defense.", "key_stat": "adj_d: 89.2"}'
    result = parse_agent_response(raw, "Duke", "Michigan")
    assert result is not None
    assert result["pick"] == "Duke"
    assert result["confidence"] == 82


@test("JSON parsing handles wrapped JSON")
def test_parse_wrapped(t: TestResult):
    raw = 'Analysis:\n\n{"pick": "Michigan", "confidence": 71, "reasoning": "Good shooting.", "key_stat": "3PT: 38%"}\n\nDone.'
    result = parse_agent_response(raw, "Duke", "Michigan")
    assert result is not None
    assert result["pick"] == "Michigan"


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


@test("All 6 agents produce valid votes (dry-run)")
async def test_all_agents_vote(t: TestResult):
    agents = build_agents()
    game = make_sample_games()[1]

    async with httpx.AsyncClient() as client:
        tasks = [run_agent(client, a, game, dry_run=True) for a in agents]
        votes = await asyncio.gather(*tasks)

    valid = [v for v in votes if not v.error and v.pick]
    t.error = "" if len(valid) == 6 else f"Only {len(valid)}/6 valid"
    for v in valid:
        assert v.pick in (game.team_a, game.team_b)
        assert 50 <= v.confidence <= 99
        assert v.reasoning


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


@test("Debate transcript includes upset watch and vote tally")
async def test_transcript(t: TestResult):
    agents = build_agents()
    game = make_sample_games()[1]  # 5v12 — should have upset score

    async with httpx.AsyncClient() as client:
        debate = await analyze_game(client, game, agents, {}, 1, 1, dry_run=True)

    transcript = generate_debate_transcript(debate)
    assert len(transcript) > 200
    assert game.team_a in transcript
    assert game.team_b in transcript
    assert "CONDUCTOR" in transcript
    assert "Vote Tally" in transcript


@test("Supabase handles missing credentials gracefully")
def test_supabase_graceful(t: TestResult):
    ok = supabase_client.write_game_result({"id": "test"})
    assert ok is False
    ok2 = supabase_client.write_agent_votes([{"game_id": "test"}])
    assert ok2 is False
    supabase_client.write_status({"test": True})
    assert (Path(__file__).parent / "status.json").exists()


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
    # Should return False with placeholder key
    assert is_gemini_available() is False


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
