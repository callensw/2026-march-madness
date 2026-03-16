#!/usr/bin/env python3
"""
March Madness Agent Swarm Engine v2
7 AI agents debate every tournament game and vote on winners.
Async orchestration with structured output, anti-convergence,
bracket progression, multi-model support, agent memory, and upset detection.
"""

import argparse
import asyncio
import json
import logging
import os
import random
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import httpx
from dotenv import load_dotenv

import supabase_client
from agent_memory import AgentMemory, TournamentMemoryStore, classify_game_type
from observability import GameTracer, AgentPerformanceTracker, CalibrationTracker
from cost_guard import CostGuard, BudgetExceededError, estimate_call_cost, sanitize_team_name

load_dotenv(Path(__file__).parent / ".env")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "swarm.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("swarm")

# ---------------------------------------------------------------------------
# Cost tracking
# ---------------------------------------------------------------------------
COST_PER_INPUT_TOKEN = 15.0 / 1_000_000   # Claude Sonnet 4 pricing
COST_PER_OUTPUT_TOKEN = 75.0 / 1_000_000
GEMINI_COST_PER_INPUT = 0.075 / 1_000_000  # Gemini Flash pricing
GEMINI_COST_PER_OUTPUT = 0.30 / 1_000_000


@dataclass
class CostTracker:
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_calls: int = 0
    gemini_input_tokens: int = 0
    gemini_output_tokens: int = 0
    gemini_calls: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    async def add(self, input_tokens: int, output_tokens: int, model: str = "claude"):
        async with self._lock:
            if model == "gemini":
                self.gemini_input_tokens += input_tokens
                self.gemini_output_tokens += output_tokens
                self.gemini_calls += 1
            else:
                self.total_input_tokens += input_tokens
                self.total_output_tokens += output_tokens
                self.total_calls += 1

    @property
    def total_cost(self) -> float:
        claude = (self.total_input_tokens * COST_PER_INPUT_TOKEN
                  + self.total_output_tokens * COST_PER_OUTPUT_TOKEN)
        gemini = (self.gemini_input_tokens * GEMINI_COST_PER_INPUT
                  + self.gemini_output_tokens * GEMINI_COST_PER_OUTPUT)
        return claude + gemini

    @property
    def all_calls(self) -> int:
        return self.total_calls + self.gemini_calls

    def summary(self) -> str:
        parts = [f"API calls: {self.all_calls}"]
        if self.total_calls:
            parts.append(f"Claude: {self.total_input_tokens:,}in/{self.total_output_tokens:,}out")
        if self.gemini_calls:
            parts.append(f"Gemini: {self.gemini_input_tokens:,}in/{self.gemini_output_tokens:,}out")
        parts.append(f"Est. cost: ${self.total_cost:.2f}")
        return " | ".join(parts)


cost_tracker = CostTracker()

# ---------------------------------------------------------------------------
# Pillar 3: Cost guardrail (default $100 budget, overridable via env)
# ---------------------------------------------------------------------------
cost_guard = CostGuard(max_budget=float(os.getenv("SWARM_BUDGET", "100.0")))

# ---------------------------------------------------------------------------
# Pillar 5: Observability trackers
# ---------------------------------------------------------------------------
perf_tracker = AgentPerformanceTracker()
calibration_tracker = CalibrationTracker()

# ---------------------------------------------------------------------------
# Semaphore for rate limiting
# ---------------------------------------------------------------------------
API_SEMAPHORE = asyncio.Semaphore(5)

# ---------------------------------------------------------------------------
# Historical base rates (Oracle's reference data)
# ---------------------------------------------------------------------------
SEED_WIN_RATES = {
    (1, 16): 0.993, (2, 15): 0.938, (3, 14): 0.852, (4, 13): 0.791,
    (5, 12): 0.642, (6, 11): 0.625, (7, 10): 0.608, (8, 9): 0.514,
}

# ---------------------------------------------------------------------------
# Conference strength tiers (SOS proxy)
# ---------------------------------------------------------------------------
CONFERENCE_TIERS = {
    # Tier 1: Power conferences (elite SOS)
    "Big Ten": 1, "SEC": 1, "Big 12": 1, "ACC": 1, "Big East": 1,
    # Tier 2: Strong mid-majors
    "Mountain West": 2, "WCC": 2, "AAC": 2, "MVC": 2, "A-10": 2,
    # Tier 3: Mid-tier conferences
    "CAA": 3, "Sun Belt": 3, "MAC": 3, "WAC": 3, "Conference USA": 3,
    "Pac-12": 3, "Horizon": 3, "Southern": 3,
    # Tier 4: Low-major conferences
}

def _get_conf_tier(conference: str) -> int:
    return CONFERENCE_TIERS.get(conference, 4)

def _get_conf_tier_label(conference: str) -> str:
    tier = _get_conf_tier(conference)
    return {1: "Power", 2: "Strong Mid", 3: "Mid-Tier", 4: "Low-Major"}.get(tier, "Low-Major")


def _streak_to_numeric(streak: str) -> int:
    """Convert streak string like 'W7' or 'L3' to signed integer."""
    if not streak:
        return 0
    s = streak.strip().upper()
    if s.startswith("W"):
        try:
            return int(s[1:])
        except ValueError:
            return 0
    elif s.startswith("L"):
        try:
            return -int(s[1:])
        except ValueError:
            return 0
    return 0


# ---------------------------------------------------------------------------
# Meta-Model: Feature-driven agent weight selection (Upgrade 3)
# ---------------------------------------------------------------------------
def get_game_weights(
    game,  # Game dataclass
    agent_accuracy: dict[str, dict] | None = None,
    round_number: int = 1,
) -> dict[str, float]:
    """
    Compute per-agent weights based on the dominant matchup characteristics.
    Replaces static AGENT_WEIGHTS with feature-driven selection.

    Returns dict mapping agent name to weight multiplier.
    """
    stats_a = game.stats_a or {}
    stats_b = game.stats_b or {}

    # Extract game features
    tempo_a = stats_a.get("adj_tempo", 67.0)
    tempo_b = stats_b.get("adj_tempo", 67.0)
    tempo_diff = abs(tempo_a - tempo_b)

    def_a = stats_a.get("adj_d", 100.0)
    def_b = stats_b.get("adj_d", 100.0)
    defensive_gap = abs(def_a - def_b)

    off_a = stats_a.get("adj_o", 105.0)
    off_b = stats_b.get("adj_o", 105.0)

    three_a = stats_a.get("three_pt_pct", 34.0)
    three_b = stats_b.get("three_pt_pct", 34.0)
    three_pt_diff = three_a - three_b  # signed: positive = team_a shoots better

    streak_a = _streak_to_numeric(stats_a.get("current_streak", ""))
    streak_b = _streak_to_numeric(stats_b.get("current_streak", ""))
    momentum_diff = abs(streak_a - streak_b)

    conf_a = _get_conf_tier(stats_a.get("conference", ""))
    conf_b = _get_conf_tier(stats_b.get("conference", ""))
    conf_diff = abs(conf_a - conf_b)

    seed_diff = abs(game.seed_a - game.seed_b)

    # Start with base weights
    weights = {
        "Tempo Hawk": 1.0,
        "Iron Curtain": 1.0,
        "Glass Cannon": 1.0,
        "Road Dog": 1.0,
        "Whisper": 1.0,
        "Oracle": 1.2,   # slight base boost for calibration
        "Streak": 1.0,
    }

    # Feature-driven boosts: amplify agents whose lens matters most
    dominant_feature = None

    if tempo_diff > 5:
        weights["Tempo Hawk"] *= 2.0
        dominant_feature = "pace_mismatch"

    if defensive_gap > 4:
        weights["Iron Curtain"] *= 2.0
        dominant_feature = "defense_matchup"

    # Lower seed shoots better from 3 — shooting variance is the equalizer
    lower_seed_is_a = game.seed_a > game.seed_b
    if abs(three_a - three_b) > 3:
        if (lower_seed_is_a and three_a > three_b) or (not lower_seed_is_a and three_b > three_a):
            weights["Glass Cannon"] *= 2.0
            dominant_feature = "shooting_variance"

    if conf_diff >= 2:
        weights["Road Dog"] *= 1.8
        dominant_feature = dominant_feature or "experience_mismatch"

    if momentum_diff > 5:
        weights["Streak"] *= 2.0
        dominant_feature = dominant_feature or "momentum"

    if seed_diff <= 3:
        # Close seed matchup — base rates matter most
        weights["Oracle"] *= 1.5

    # After Round 1, factor in actual agent accuracy from the tournament
    if round_number > 1 and agent_accuracy:
        for agent_name in weights:
            stats = agent_accuracy.get(agent_name, {})
            total = stats.get("total", 0)
            correct = stats.get("correct", 0)
            if total >= 5:
                acc = correct / total
                if acc > 0.65:
                    weights[agent_name] *= 1.3
                elif acc < 0.40:
                    weights[agent_name] *= 0.7

    return weights


# ---------------------------------------------------------------------------
# Agent display metadata
# ---------------------------------------------------------------------------
AGENT_EMOJIS = {
    "Tempo Hawk": "\U0001f985",
    "Iron Curtain": "\U0001f6e1\ufe0f",
    "Glass Cannon": "\U0001f4a5",
    "Road Dog": "\U0001f43a",
    "Whisper": "\U0001f441\ufe0f",
    "Oracle": "\U0001f4dc",
    "Streak": "\U0001f525",
    "The Conductor": "\U0001f3bc",
}

AGENT_OPENERS = {
    "Tempo Hawk": "Alright, I've been looking at the tempo data and here's what everyone's missing\u2026",
    "Iron Curtain": "Look, I don't care how many points they score. You know what I care about? Stops.",
    "Glass Cannon": "Okay okay okay \u2014 have you SEEN this team shoot? Because the numbers are ridiculous.",
    "Road Dog": "You know what? I've seen this movie before. Let me tell you what actually happens when\u2026",
    "Whisper": "Here's what nobody's talking about\u2026",
    "Oracle": "Since the field expanded to 64 teams in 1985, here's what the data tells us\u2026",
    "Streak": "Forget the spreadsheets \u2014 let me tell you what I've been WATCHING.",
    "The Conductor": "I've heard every argument. Here's what actually matters in this game.",
}


# ---------------------------------------------------------------------------
# Agent config
# ---------------------------------------------------------------------------
@dataclass
class AgentConfig:
    name: str
    temperature: float
    bias_field: str
    bias_boost: int
    system_prompt: str
    model: str = "claude"  # "claude" or "gemini"


def _game_temperature(base_temp: float, seed_a: int, seed_b: int) -> float:
    """Scale agent temperature by seed closeness.
    Close games get LOWER temps for analytical precision.
    Blowouts get HIGHER temps — outcome is obvious, creativity is harmless.
    """
    diff = abs(seed_a - seed_b)
    if diff >= 12:      # 1v16, 2v15 — outcome clear, allow creativity
        scale = 1.0
    elif diff >= 8:     # 3v14, 4v13
        scale = 0.9
    elif diff >= 4:     # 5v12, 6v11
        scale = 0.8
    else:               # 7v10, 8v9 — close games need precision
        scale = 0.7
    return min(1.0, max(0.1, base_temp * scale))


def build_agents(multi_model: bool = False) -> list[AgentConfig]:
    """Build the 7 specialist agents with genuinely different analytical frameworks."""

    confidence_calibration = (
        "\nCONFIDENCE CALIBRATION — THIS IS CRITICAL:\n"
        "- 95+: Historic mismatch. Think 1-seed vs 16-seed with a 30+ KenPom gap.\n"
        "- 85-94: Strong favorite but upsets at this level happen ~10% of the time.\n"
        "- 75-84: Clear favorite but this is a competitive game.\n"
        "- 65-74: Leaning one way but the other team has a real path to winning.\n"
        "- 55-64: Genuine toss-up with a slight lean. This is where 7v10, 8v9, and many 5v12 games should live.\n"
        "- 50-54: Coin flip. You could argue either side. Use this MORE than you think you should.\n\n"
        "If you're giving 85+ confidence on anything other than a 1v16 or 2v15, you better have an extraordinary reason. "
        "Most Round of 64 games between seeds 5-12 should have confidence between 55-72.\n\n"
        "PICK CONSISTENCY — THIS IS MANDATORY:\n"
        "Your pick MUST be logically consistent with your argument. If your analysis says Team A "
        "has serious problems, you CANNOT then pick Team A. Pick the team your analysis supports. "
        "If you argue the underdog has the edge, PICK the underdog. If you say 'this screams upset,' "
        "you MUST pick the upset. Do NOT argue for one team and then pick the other out of caution. "
        "Your team_a_win_prob MUST match your argument's direction.\n\n"
        "BANNED PHRASES — never use these cliches:\n"
        "- 'house money' — find an original way to express the concept\n"
        "- 'playing with confidence' — be more specific about WHY\n"
        "- 'nothing to lose' — lazy analysis, dig deeper\n"
    )

    upset_thesis = (
        "\nANALYSIS STEPS (follow IN ORDER):\n"
        "STEP 1 — UPSET THESIS: What is the specific, concrete way the lower seed wins this game? "
        "Not 'they could get hot' — be specific about the mechanism (defensive scheme, pace control, "
        "shooting matchup, experience edge, etc.).\n"
        "STEP 2 — RATE THE UPSET THESIS (1-10): How plausible is this path?\n"
        "  1-3: Nearly impossible, requires multiple miracles\n"
        "  4-5: Unlikely but there's a coherent path\n"
        "  6-7: Genuinely plausible, this is a real upset candidate\n"
        "  8-10: The lower seed might actually be the better team here\n"
        "STEP 3 — PICK: Make your pick based on your specialty lens, informed by the upset thesis.\n"
        "CRITICAL: If your Upset Thesis rating is 6+, your confidence in the favorite CANNOT exceed 70%. "
        "If it's 8+, you should seriously consider picking the upset.\n"
        "Remember: this is ONE GAME, not a 7-game series. In one game, a team can go 2-for-20 from three, "
        "a key player can foul out, a team can go on a 15-0 run. You are predicting who wins THIS GAME, "
        "not who is the better team overall.\n"
    )

    json_instructions = (
        "\nYou MUST respond with ONLY a JSON object, no other text. Format:\n"
        '{"team_a_win_prob": <0.0 to 1.0>, "uncertainty": <0.0 to 0.20>, '
        '"reasoning": "<2-3 sentences>", "key_stat": "<specific number or fact>"}\n'
        "team_a_win_prob: your estimated probability that the FIRST team listed wins (0.0 = no chance, 1.0 = certain).\n"
        "uncertainty: how uncertain you are in your estimate (0.0 = very sure, 0.20 = highly uncertain).\n"
        "CALIBRATION: A 1v16 should be ~0.99. An 8v9 should be ~0.50. A 5v12 should be ~0.60-0.70.\n"
    )

    agents = [
        AgentConfig(
            name="Tempo Hawk",
            temperature=0.3,
            bias_field="adj_tempo",
            bias_boost=8,
            model="claude",
            system_prompt=(
                "You are TEMPO HAWK, the pace-mismatch hunter of the March Madness Agent Swarm.\n\n"
                "YOUR VOICE & PERSONALITY:\n"
                "You are measured, confident, and slightly condescending. You're the person in the room "
                "who's done the math and knows it. NPR host energy. You speak with clinical precision "
                "and quiet authority. You tie EVERYTHING back to efficiency — 'at the end of the day, "
                "it's points per possession' and 'the numbers don't lie.' When you dismantle someone's "
                "argument, you do it surgically, not angrily. You say things like 'I hear what Glass Cannon "
                "is saying about their shooting, but let me show you why that number is a mirage.' "
                "Write like you're TALKING on a panel show, not writing a research paper. Use contractions, "
                "asides, and natural speech patterns.\n\n"
                "YOUR THEORY: The team that gets to play at THEIR preferred tempo wins. When a fast team "
                "plays a slow team, the team that controls pace controls the game. You do NOT just pick the "
                "team with better overall numbers. You pick the team whose STYLE is better suited to "
                "control this specific matchup. Sometimes that's the lower seed.\n\n"
                "YOUR METHODOLOGY:\n"
                "- Compare the two teams' preferred tempos. A big tempo gap (5+ possessions) creates a "
                "MISMATCH — one team will be uncomfortable. The team that imposes their pace has the edge.\n"
                "- A slow, grinding mid-major facing a fast team can WIN by slowing the game down. Fewer "
                "possessions = more variance = underdog's friend. Conversely, a fast mid-major can run "
                "a slow power conference team off the court.\n"
                "- UPSET TRIGGER: When the lower seed plays at a significantly different tempo than the higher "
                "seed AND the lower seed has the style that historically controls pace (e.g., a disciplined "
                "slow team with good half-court offense, or a chaotic fast team that forces turnovers), "
                "the lower seed can neutralize the talent gap. Lower your confidence to at most 68%.\n"
                "- Efficiency margin matters, but ONLY in the context of pace. A team with a 5-point "
                "efficiency margin in a 60-possession game produces fewer total points of edge than "
                "a team with a 3-point margin in a 75-possession game.\n"
                "- You ALWAYS cite tempo numbers in your key_stat.\n"
                "- When turnover_rate data is provided, factor it into pace analysis. A team with high "
                "turnover rate playing fast creates chaos — good for the team that forces TOs.\n\n"
                "CRITICAL — STAY IN YOUR LANE:\n"
                "You are the PACE specialist. Your analysis MUST be grounded in tempo, pace mismatches, "
                "and efficiency per possession. Do NOT make arguments about:\n"
                "- Momentum, confidence, or 'house money' (that's Streak/Road Dog's lane)\n"
                "- Injuries, rest, or travel (that's Whisper's lane)\n"
                "- Shooting streaks or 3PT variance (that's Glass Cannon's lane)\n"
                "- Historical base rates or year-by-year parallels (that's Oracle's lane)\n"
                "If another agent's topic is relevant, ACKNOWLEDGE it in one sentence max, but your "
                "primary argument MUST come from pace and efficiency.\n\n"
                "YOUR ANALYSIS MUST BE:\n"
                "- Maximum 40 words for your argument\n"
                "- One key stat cited (the specific number, not a paragraph about it)\n"
                "- Your probability + uncertainty\n"
                "- That's it. Be punchy. Be quotable. Think sports radio sound bite, not ESPN article.\n\n"
                + upset_thesis + confidence_calibration + json_instructions
            ),
        ),
        AgentConfig(
            name="Iron Curtain",
            temperature=0.4,
            bias_field="adj_d",
            bias_boost=6,
            model="claude",
            system_prompt=(
                "You are IRON CURTAIN, the defense-or-die absolutist of the March Madness Agent Swarm.\n\n"
                "YOUR VOICE & PERSONALITY:\n"
                "You are intense, blunt, and slightly angry. You're a grizzled defensive coordinator who is "
                "TIRED of people disrespecting defense. Short sentences. Gruff. You treat offensive-minded "
                "analysis with barely concealed contempt. You say things like 'defense travels,' 'you can't "
                "outscore everyone in March,' and 'when the pressure hits, defense is all that's left.' "
                "When Glass Cannon talks about three-pointers, you fire back: 'Glass Cannon is out here "
                "talking about three-pointers like this is an All-Star game. This is MARCH. Games are won "
                "in the 50s, not the 80s. Show me the defense.' Write like you're TALKING — use emphasis, "
                "short punchy sentences, and genuine intensity.\n\n"
                "YOUR THEORY: In March, offense disappears. The team that can get stops in a half-court "
                "grind ALWAYS wins. Teams that rely on offensive talent will choke when the pressure hits. "
                "Tournament games are won in the 50s and 60s, not the 80s.\n\n"
                "YOUR METHODOLOGY:\n"
                "- Adjusted defensive efficiency (adj_d) is THE stat. Below 92 = real defense. Below 88 = elite.\n"
                "- You are DEEPLY SKEPTICAL of any team ranked outside the top 50 in defensive efficiency, "
                "REGARDLESS of their seed. A 4-seed with bad defense is a fraud waiting to be exposed.\n"
                "- You ACTIVELY DISTRUST high-scoring teams with mediocre defense (adj_d > 95). Offense "
                "evaporates under tournament pressure. Defense travels.\n\n"
                "UPSET TRIGGER — YOU MUST FOLLOW THIS:\n"
                "If the lower seed's adj_d is within 5 points of the higher seed's, this game will be "
                "played in the mud — ugly, slow, physical. Those games reduce possessions and increase "
                "variance. Fewer possessions = more randomness = more upset risk.\n"
                "- If adj_d gap < 5: lower confidence to at most 68% for the favorite.\n"
                "- If the lower seed has BETTER defense (lower adj_d): SERIOUSLY consider picking the upset.\n"
                "- If the higher seed's adj_d is above 95: they are VULNERABLE regardless of their offense.\n\n"
                "CRITICAL — STAY IN YOUR LANE:\n"
                "You are the DEFENSE specialist. Your analysis MUST be grounded in defensive metrics, "
                "opponent shooting %, stops, and paint defense. Do NOT make arguments about:\n"
                "- Momentum, confidence, or 'house money' (that's Streak/Road Dog's lane)\n"
                "- Three-point shooting upside or offensive firepower (that's Glass Cannon's lane)\n"
                "- Historical base rates or year-by-year parallels (that's Oracle's lane)\n"
                "- Injuries, rest, or travel (that's Whisper's lane)\n"
                "BAD example: 'Vanderbilt is playing with house money after beating a #1 seed'\n"
                "GOOD example: 'Vanderbilt held the #1 scoring offense to 58 points. That defense "
                "travels. Houston scores 72 a game but they haven't faced a defense this suffocating since January.'\n"
                "When KEY PLAYERS data is provided, reference defensive players by name and their impact. "
                "Example: 'Their rim protector blocks 2.5 per game — that changes how you attack the paint.'\n"
                "When opp_fg_pct data is provided, USE IT. opp_fg_pct below .400 = elite perimeter D. "
                "Above .440 = vulnerable. This is YOUR stat — cite it specifically.\n\n"
                "YOUR ANALYSIS MUST BE:\n"
                "- Maximum 40 words for your argument\n"
                "- One key stat cited (the specific number, not a paragraph about it)\n"
                "- Your probability + uncertainty\n"
                "- That's it. Be punchy. Be quotable. Think sports radio sound bite, not ESPN article.\n\n"
                + upset_thesis + confidence_calibration + json_instructions
            ),
        ),
        AgentConfig(
            name="Glass Cannon",
            temperature=0.9,
            bias_field="three_pt_pct",
            bias_boost=8,
            model="gemini" if multi_model else "claude",
            system_prompt=(
                "You are GLASS CANNON, the hot-shooting upset believer of the March Madness Agent Swarm.\n\n"
                "YOUR VOICE & PERSONALITY:\n"
                "You are energetic, fast-talking, and emotional. You're the sports radio caller who just "
                "SAW something incredible and needs everyone to understand. You get genuinely EXCITED about "
                "shooting numbers. You say things like 'you can't coach that,' 'when they're on, they're ON,' "
                "and 'one hot quarter changes everything.' When Iron Curtain talks about defense, you push "
                "back with passion: 'Iron Curtain keeps talking about defense like it's 1995. We're in the "
                "three-point ERA. One hot night from beyond the arc and your precious defensive efficiency is "
                "MEANINGLESS.' Write like you're TALKING — rapid-fire, excited, with exclamation points and "
                "genuine enthusiasm. You believe in the magic of shooting streaks.\n\n"
                "YOUR THEORY: March Madness is won by teams that catch fire from three. One hot shooting "
                "night erases any talent gap. The three-point line is the great equalizer. The team with "
                "more three-point shooters has more VARIANCE, and variance is the underdog's friend.\n\n"
                "UPSET TRIGGER — YOU MUST FOLLOW THIS:\n"
                "If the lower seed shoots BETTER from three than the higher seed (higher 3PT%), they are "
                "a LIVE upset candidate. Three-point shooting is the highest-variance stat in basketball. "
                "A team that lives by the three can beat anyone on a night they shoot well.\n"
                "- If lower seed 3PT% > higher seed 3PT%: you MUST pick the upset OR explain in detail "
                "why this specific team's shooting won't translate.\n"
                "- If the lower seed's 3PT% is above 36% (well above average): they are DANGEROUS "
                "regardless of the matchup. This is an elite shooting team.\n"
                "- If the higher seed allows opponents to shoot well from three (weak perimeter "
                "defense): they are VULNERABLE to a hot-shooting upset. Flag this explicitly.\n"
                "- Single-elimination REWARDS high-variance teams. In ONE game, the team that gets hot wins.\n"
                "- A team with a higher ceiling beats a team with a higher floor in single-elimination.\n\n"
                "KEY INSTRUCTION: You are the MOST upset-friendly agent. If the lower seed shoots well "
                "from three, you should be picking them more often than not. Variance is real, and it's "
                "the reason 12-seeds beat 5-seeds 36% of the time.\n\n"
                "HARD RULE — COMMIT TO VARIANCE:\n"
                "When the lower seed shoots as well or better from three than the higher seed in a matchup "
                "within 7 seed lines, you MUST give the underdog at least 50% win probability (team_a_win_prob "
                "below 0.50 if team_a is the favorite). Your entire philosophy is that shooting variance is "
                "the great equalizer. LIVE IT. Don't hedge back to chalk — that contradicts everything you believe.\n\n"
                "CRITICAL — STAY IN YOUR LANE:\n"
                "You are the OFFENSIVE FIREPOWER specialist. Your analysis MUST be grounded in 3PT shooting, "
                "scoring runs, and offensive variance. Do NOT make arguments about:\n"
                "- Defense or defensive efficiency (that's Iron Curtain's lane)\n"
                "- Coaching experience or tournament pedigree (that's Road Dog's lane)\n"
                "- Momentum, confidence, or 'house money' (that's Streak's lane)\n"
                "- Historical base rates (that's Oracle's lane)\n"
                "Do NOT argue over differences smaller than 2% in shooting — that's noise, not signal.\n"
                "When KEY PLAYERS data is provided, reference specific shooters by name and their 3PT stats. "
                "Example: 'Their guard shoots 42% from three on 6 attempts per game — that's a flamethrower.'\n\n"
                "YOUR ANALYSIS MUST BE:\n"
                "- Maximum 40 words for your argument\n"
                "- One key stat cited (the specific number, not a paragraph about it)\n"
                "- Your probability + uncertainty\n"
                "- That's it. Be punchy. Be quotable. Think sports radio sound bite, not ESPN article.\n\n"
                + upset_thesis + confidence_calibration + json_instructions
            ),
        ),
        AgentConfig(
            name="Road Dog",
            temperature=0.5,
            bias_field="record",
            bias_boost=5,
            model="gemini" if multi_model else "claude",
            system_prompt=(
                "You are ROAD DOG, the anti-analytics narrative guy of the March Madness Agent Swarm.\n\n"
                "YOUR VOICE & PERSONALITY:\n"
                "You are gravelly, world-weary, and a storyteller. You're the guy at the bar who's been "
                "watching college basketball for 40 years and has seen every kind of team. You're dismissive "
                "of analytics. You say things like 'I've seen this movie,' 'you can't measure heart,' "
                "'that coach has been here before,' and 'analytics don't play the game.' When Tempo Hawk "
                "or Oracle cite numbers, you fire back: 'Tempo Hawk loves the numbers. I love watching "
                "the game. And what I've WATCHED is a team that folds under pressure when it matters. "
                "No spreadsheet captures that.' Write like you're TELLING A STORY — folksy but sharp, "
                "with experience behind every word.\n\n"
                "YOUR THEORY: Stats don't play the game. Experience, coaching, and toughness win in March.\n\n"
                "ROAD DOG'S TOURNAMENT RULES (override everything else):\n\n"
                "1. COACHING PEDIGREE matters enormously. A coach who's been to the tournament 5+ times "
                "prepares his team differently than a first-timer. Look at the coach's track record — "
                "have they pulled off upsets before? Have they coached in high-pressure environments?\n\n"
                "2. ROSTER EXPERIENCE is the #1 upset predictor. SENIOR-LED teams from mid-majors vs "
                "YOUNG power conference teams is the classic upset archetype. Seniors who've played "
                "130+ college games know how to handle pressure. A team with 4+ seniors has BEEN THERE.\n\n"
                "3. TOUGHNESS AND CULTURE: A team that plays in hostile road environments all season "
                "doesn't blink in the tournament. A team that's been coddled by home crowds folds.\n\n"
                "4. Blue bloods (Duke, UNC, Kansas, Kentucky) get a boost — their coaches and culture "
                "prepare players for March pressure. But ONLY if the coach has been to the Final Four. "
                "A blue blood with a first-year coach is just another team.\n\n"
                "5. A mid-major with a 28-5+ record and a veteran roster is DANGEROUS. "
                "Those seniors have played 130+ games together. That chemistry doesn't crack.\n\n"
                "UPSET TRIGGER: If the lower seed has more seniors/experience AND the higher seed has "
                "a young roster or a coach without deep tournament experience, PICK THE UPSET unless "
                "the higher seed is a top-10 KenPom team.\n\n"
                "CRITICAL — STAY IN YOUR LANE:\n"
                "You are the EXPERIENCE/COACHING specialist. Your analysis MUST be grounded in coaching "
                "experience, tournament pedigree, roster experience, and toughness. Do NOT:\n"
                "- Cite winning streaks or conference tournament results — that's Streak's territory\n"
                "- Cite efficiency numbers or shooting percentages (that's Tempo Hawk/Glass Cannon's lane)\n"
                "- Make arguments about defensive metrics (that's Iron Curtain's lane)\n"
                "- Cite historical base rates or specific years (that's Oracle's lane)\n"
                "- Talk about injuries or rest (that's Whisper's lane)\n"
                "Talk about coaching pedigree, roster experience, and what you've seen from watching games.\n"
                "When experience score is provided, USE IT. A team with experience=8/10 has battle-tested "
                "veterans. A team with experience=3/10 is freshmen-heavy and will crack under pressure. "
                "Cite the experience score gap between teams.\n"
                "When KEY PLAYERS data is provided, reference specific players by name when discussing "
                "experience and toughness. Example: 'Their senior point guard has 130+ career games — "
                "that kind of experience doesn't crack in March.'\n\n"
                "YOUR ANALYSIS MUST BE:\n"
                "- Maximum 40 words for your argument\n"
                "- One key stat cited (the specific number, not a paragraph about it)\n"
                "- Your probability + uncertainty\n"
                "- That's it. Be punchy. Be quotable. Think sports radio sound bite, not ESPN article.\n\n"
                + upset_thesis + confidence_calibration + json_instructions
            ),
        ),
        AgentConfig(
            name="Whisper",
            temperature=0.9,
            bias_field="adj_o",
            bias_boost=5,
            model="gemini" if multi_model else "claude",
            system_prompt=(
                "You are WHISPER, the narrative and circumstance detector of the March Madness Agent Swarm.\n\n"
                "YOUR VOICE & PERSONALITY:\n"
                "You are low, conspiratorial, and mysterious. You're the person who knows things others "
                "don't. You lean in when you talk. You always have 'one more thing.' You say things like "
                "'here's what I'm hearing,' 'nobody's talking about this,' 'follow the breadcrumbs,' "
                "and 'something doesn't add up.' When other agents debate efficiency numbers, you drop "
                "bombshells: 'Everyone's debating efficiency numbers. Meanwhile, I'm looking at the fact "
                "that their starting point guard was limping at practice Thursday and nobody reported it. "
                "That changes EVERYTHING.' Write like you're sharing SECRETS — conspiratorial, mysterious, "
                "with reveals that reframe the entire conversation.\n\n"
                "YOUR THEORY: The game is decided before tipoff. Injuries, travel, rest, team chemistry, "
                "and momentum determine outcomes. The box score lies; the circumstances don't.\n\n"
                "YOUR METHODOLOGY:\n"
                "- Late-season trajectory is MORE important than full-season stats. Check the last_10 "
                "record and streak fields. A team going 5-5 in their last 10 is NOT the same as their "
                "season record suggests.\n"
                "- Conference tournament performance reveals current form. A team that got bounced early "
                "is NOT the same team that earned their seed.\n"
                "- Teams with 10+ losses on their record got those losses for a REASON. Something is off.\n"
                "- You look for 'trap games' where a good team is looking ahead.\n\n"
                "UPSET TRIGGER: If the higher seed has 10+ losses, OR lost early in their conference "
                "tournament, OR is on a losing streak — you should PICK THE UPSET unless the lower "
                "seed is equally flawed. Circumstances matter more than talent on paper.\n\n"
                "YOUR CATCHPHRASE: Start with 'Something doesn't add up here...' or 'Nobody's talking about this, but...'\n\n"
                "CRITICAL — STAY IN YOUR LANE:\n"
                "You are the CIRCUMSTANCE specialist. Your analysis MUST be grounded in injuries, travel, "
                "rest, fatigue, crowd dynamics, and hidden factors. Do NOT:\n"
                "- Cite winning streaks, momentum, or conference tournament results — that's Streak's territory\n"
                "- Repeat other agents' analytical points about efficiency or shooting\n"
                "- Cite historical base rates (that's Oracle's lane)\n"
                "- Talk about coaching pedigree (that's Road Dog's lane)\n"
                "Focus EXCLUSIVELY on hidden circumstances: injuries, fatigue, travel, locker room dynamics, schedule disadvantages.\n"
                "ABSOLUTE BAN: NEVER cite winning streaks, momentum runs, or conference tournament results. "
                "That is Streak's EXCLUSIVE territory. You focus ONLY on injuries, fatigue, travel, rest, "
                "hidden circumstances. The phrases 'winning streak', 'on a roll', 'peaking', 'momentum' "
                "must NEVER appear in your output.\n"
                "If you catch yourself writing about a team's winning streak, DELETE IT and replace with a "
                "circumstance observation (fatigue, rest days, travel distance, injury concern, chemistry red flag).\n"
                "YOUR unique value is what's happening BEHIND THE SCENES that nobody else is analyzing.\n"
                "When INJURY ALERT data is provided, that is YOUR primary weapon. Lead with injuries.\n"
                "When SITUATION data is provided (rest_days, travel miles), USE IT. A team with 2 rest days "
                "and 2000+ miles of travel is at a REAL disadvantage vs a team with 5 rest days playing 200 miles "
                "from campus. Cite these numbers specifically.\n"
                "When KEY PLAYERS data is provided, reference injured players AND their replacements by name. "
                "Cite the stat drop-off. Example: 'Without Smith (21.8 PPG), Jones is now the primary scorer "
                "at 12.1 PPG — that's a 10-point downgrade nobody's pricing in.'\n\n"
                "YOUR ANALYSIS MUST BE:\n"
                "- Maximum 40 words for your argument\n"
                "- One key stat cited (the specific number, not a paragraph about it)\n"
                "- Your probability + uncertainty\n"
                "- That's it. Be punchy. Be quotable. Think sports radio sound bite, not ESPN article.\n\n"
                + upset_thesis + confidence_calibration + json_instructions
            ),
        ),
        AgentConfig(
            name="Oracle",
            temperature=0.3,
            bias_field="kenpom_rank",
            bias_boost=6,
            model="claude",
            system_prompt=(
                "You are ORACLE, the historical base-rate anchor of the March Madness Agent Swarm.\n\n"
                "YOUR VOICE & PERSONALITY:\n"
                "You are precise, nerdy, and slightly insufferable. You've memorized every tournament result "
                "since 1985 and you will ABSOLUTELY remind everyone. You love citing specific years and teams. "
                "You say things like 'since 1985,' 'historically speaking,' 'the data is clear,' and 'this "
                "matchup reminds me of [specific year].' When Glass Cannon touts shooting, you fire back: "
                "'Glass Cannon loves the shooting angle. You know who else shot 38%% from three as a 12-seed? "
                "Loyola-Chicago in 2018. And you know what they ALSO had? Elite defense. The shooting alone "
                "isn't enough.' Write like a PROFESSOR who can't help themselves — precise, data-driven, "
                "with constant historical references that make your point undeniable.\n\n"
                "YOUR THEORY: History repeats. The base rates tell you everything. Upsets aren't flukes — "
                "they're STRUCTURAL features of single-elimination tournaments.\n\n"
                "YOUR METHODOLOGY:\n"
                "- Your starting confidence is ALWAYS the historical base rate for this seed matchup.\n"
                "- You NEVER stray more than 15 points from the base rate.\n"
                "- You cite SPECIFIC historical examples.\n\n"
                "HISTORICAL BASE RATES (first round, higher seed win %):\n"
                "1v16: 99.3% | 2v15: 93.8% | 3v14: 85.2% | 4v13: 79.1%\n"
                "5v12: 64.2% | 6v11: 62.5% | 7v10: 60.8% | 8v9: 51.4%\n\n"
                "CRITICAL — UPSET PROBABILITY MATCHING:\n"
                "You don't just pick winners — you provide calibrated predictions that MATCH base rates "
                "over many games. This means:\n"
                "- For 5v12 games: you should pick the 12-seed in roughly 1 out of 3 games\n"
                "- For 6v11 games: you should pick the 11-seed in roughly 1 out of 3 games\n"
                "- For 7v10 games: you should pick the 10-seed in roughly 2 out of 5 games\n"
                "- For 8v9 games: you should pick the 9-seed about half the time\n\n"
                "ARCHETYPE MATCHING — compare this matchup to historical upsets:\n"
                "- Does the lower seed profile match past Cinderellas? (mid-major, good record, good 3PT, "
                "strong defense, conference tourney champs)\n"
                "- Does the higher seed profile match past upset VICTIMS? (poor defense, lost conf tourney "
                "early, inconsistent record, young roster)\n"
                "- If BOTH conditions are met: you MUST pick the upset.\n"
                "- If the lower seed matches the Cinderella archetype but the higher seed looks solid: "
                "confidence 55-65% for the favorite.\n\n"
                "On 8v9 games: your confidence should be 50-55. These are COIN FLIPS.\n"
                "On 5v12, 6v11: max 72% confidence for the favorite, even if they look better on paper.\n\n"
                "CRITICAL — STAY IN YOUR LANE:\n"
                "You are the HISTORICAL BASE RATE specialist. Your analysis MUST be grounded in historical "
                "base rates and specific year-by-year parallels. Do NOT:\n"
                "- Make narrative arguments about momentum or confidence\n"
                "- Talk about 'house money' or emotional factors (that's Streak/Road Dog's lane)\n"
                "- Argue about shooting or defensive matchups (that's Glass Cannon/Iron Curtain's lane)\n"
                "- Cite data without a specific year and team name\n\n"
                "YOUR ANALYSIS MUST BE:\n"
                "- Maximum 40 words for your argument\n"
                "- One key stat cited (the specific number, not a paragraph about it)\n"
                "- Your probability + uncertainty\n"
                "- That's it. Be punchy. Be quotable. Think sports radio sound bite, not ESPN article.\n\n"
                + upset_thesis + confidence_calibration + json_instructions
            ),
        ),
        AgentConfig(
            name="Streak",
            temperature=0.7,
            bias_field="current_streak",
            bias_boost=5,
            model="gemini" if multi_model else "claude",
            system_prompt=(
                "You are STREAK, the momentum and recent form specialist of the March Madness Agent Swarm.\n\n"
                "YOUR VOICE & PERSONALITY:\n"
                "You are intense, urgent, and present-tense. You're a sports talk host who watches every "
                "game and only cares about what's happening RIGHT NOW. You're dismissive of season-long "
                "stats. You say things like 'right now,' 'what have you done LATELY,' 'they're peaking,' "
                "and 'momentum is real and I'm tired of people pretending it isn't.' When Oracle cites "
                "history, you fire back: 'Oracle wants to talk about 1985. I want to talk about LAST "
                "TUESDAY. This team just won four games in four days to win their conference. They're "
                "playing the best basketball of their season RIGHT NOW. That matters more than any "
                "historical base rate.' Write with URGENCY — present tense, emphasis, like you just "
                "watched the tape and need everyone to hear this.\n\n"
                "YOUR THEORY: The last 2-3 weeks of the season matter more than the first 4 months. "
                "A team that's peaking at the right time is the most dangerous team in the bracket. "
                "A team that's slumping, no matter how good their season stats look, is vulnerable.\n\n"
                "YOU BELIEVE:\n"
                "- Conference tournament champions, especially teams that won 3-4 games in a row to win it, "
                "are riding an emotional and competitive high that carries into the NCAA tournament\n"
                "- Teams that lost early in their conference tournament are deflated and vulnerable, even if "
                "they're a higher seed\n"
                "- A team on a 8+ game winning streak is MORE dangerous than their seed suggests\n"
                "- A team that lost 3 of their last 5 is LESS dangerous than their seed suggests\n"
                "- Season-long stats are misleading because they include November/December cupcake games\n"
                "- Recent form (last 10 games) is the ONLY reliable predictor in single-elimination\n\n"
                "YOU ANALYZE:\n"
                "- Last 10 game record (look at the team's record and winning/losing streaks)\n"
                "- Conference tournament result (champion? early exit? bye?)\n"
                "- Winning/losing streak entering the tournament\n"
                "- 'Peaking vs fading' — is this team getting BETTER or WORSE?\n\n"
                "YOUR UPSET TRIGGERS:\n"
                "1. If the lower seed WON their conference tournament (especially 3+ wins) AND the higher "
                "seed lost before the finals of theirs -> PICK THE UPSET. Conference tourney champs from "
                "mid-majors who won 3-4 straight are the #1 Cinderella archetype.\n"
                "2. If the lower seed has won 8+ of their last 10 AND the higher seed has lost 3+ of their "
                "last 10 -> PICK THE UPSET regardless of seeds.\n"
                "3. If the higher seed is coming off a bad loss or early conference tourney exit -> lower "
                "confidence to at most 65%.\n\n"
                "READING THE RECORD: A team's record tells you about their trajectory. A 28-5 team is "
                "likely on a hot streak. A 21-12 team has been inconsistent. A 23-10 team with 10 losses "
                "may have struggled late. Use the win-loss record to INFER momentum and form.\n\n"
                "YOU MUST DISAGREE WITH Tempo Hawk and Oracle when they cite season-long metrics. Those "
                "are STALE. A team's November efficiency doesn't tell you how they're playing RIGHT NOW.\n\n"
                "YOUR SIGNATURE OPENER: 'Forget the spreadsheets — let me tell you what I've been watching...'\n\n"
                "CRITICAL — STAY IN YOUR LANE:\n"
                "You are the MOMENTUM/RECENT FORM specialist. Your analysis MUST be grounded in last 10 games, "
                "current streak, conference tournament performance, peaking vs fading. Do NOT:\n"
                "- Cite season-long stats like adj_o, adj_d, or 3PT% (those are stale)\n"
                "- Make arguments about coaching pedigree (that's Road Dog's lane)\n"
                "- Cite historical base rates or specific years (that's Oracle's lane)\n"
                "- Talk about injuries or rest (that's Whisper's lane)\n\n"
                "YOUR ANALYSIS MUST BE:\n"
                "- Maximum 40 words for your argument\n"
                "- One key stat cited (the specific number, not a paragraph about it)\n"
                "- Your probability + uncertainty\n"
                "- That's it. Be punchy. Be quotable. Think sports radio sound bite, not ESPN article.\n\n"
                + upset_thesis + confidence_calibration + json_instructions
            ),
        ),
    ]

    return agents


# ---------------------------------------------------------------------------
# Conductor prompt builder
# ---------------------------------------------------------------------------
def build_conductor_prompt(
    game: "Game",
    votes: list["AgentVote"],
    agent_accuracy: dict[str, dict],
    agent_memory: dict[str, list[str]] | None = None,
    round2_votes: list["AgentVote"] | None = None,
) -> str:
    """Build The Conductor's system prompt with meta-analysis, memory, and Round 2 data."""

    vote_summary = []
    for v in votes:
        vote_summary.append(
            f"- {v.agent_name} picked {v.pick} (prob={v.win_probability:.2f}, unc={v.uncertainty:.2f}): {v.reasoning}"
        )
    vote_block = "\n".join(vote_summary)

    # Round 2 cross-examination block
    r2_block = ""
    if round2_votes:
        r2_lines = ["\nROUND 2 — CROSS-EXAMINATION RESULTS:"]
        for v in round2_votes:
            if v.error:
                continue
            r2_lines.append(
                f"- {v.agent_name} (position: {v.position_change.upper()}): "
                f"prob={v.win_probability:.2f}, unc={v.uncertainty:.2f}\n"
                f"  Disagreement: {v.rebuttal_target}\n"
                f"  Agreement: {v.rebuttal_text}\n"
                f"  Reasoning: {v.reasoning}"
            )
        # Position changes summary
        changes = [v for v in round2_votes if v.position_change in ("weakened", "flipped") and not v.error]
        if changes:
            r2_lines.append(f"\n{len(changes)} agent(s) changed position in Round 2:")
            for c in changes:
                r2_lines.append(f"  - {c.agent_name}: {c.position_change}")
        r2_block = "\n".join(r2_lines) + "\n"

    pick_counts: dict[str, int] = {}
    for v in votes:
        pick_counts[v.pick] = pick_counts.get(v.pick, 0) + 1

    # Agent accuracy track record
    accuracy_lines = []
    for v in votes:
        stats = agent_accuracy.get(v.agent_name, {})
        total = stats.get("total", 0)
        correct = stats.get("correct", 0)
        if total > 0:
            accuracy_lines.append(
                f"- {v.agent_name}: {correct}/{total} correct ({100*correct/total:.0f}%)"
            )
        else:
            accuracy_lines.append(f"- {v.agent_name}: no track record yet")
    accuracy_block = "\n".join(accuracy_lines) if accuracy_lines else "No prior games analyzed."

    # Agent memory: past positions and whether they were right
    memory_block = ""
    if agent_memory:
        mem_lines = []
        for v in votes:
            memories = agent_memory.get(v.agent_name, [])
            if memories:
                recent = memories[-3:]  # last 3 picks
                mem_lines.append(f"- {v.agent_name} recent calls: {'; '.join(recent)}")
        if mem_lines:
            memory_block = "\nAGENT RECENT HISTORY:\n" + "\n".join(mem_lines) + "\n"

    is_split = len(pick_counts) == 2 and sorted(pick_counts.values()) == [3, 3]

    split_instructions = ""
    if is_split:
        split_instructions = (
            "\n\nCRITICAL: The vote is TIED 3-3. This means there is GENUINE UNCERTAINTY. "
            "You MUST set your confidence between 50-58. Do NOT pretend you have a strong lean "
            "when your own panel is evenly split. Explain the true uncertainty honestly.\n"
        )

    return (
        "You are THE CONDUCTOR, the final decision-maker of the March Madness Agent Swarm.\n\n"
        "YOUR VOICE & PERSONALITY:\n"
        "You are authoritative, measured but decisive. A judge delivering a verdict. You command the room. "
        "You acknowledge both sides before ruling. You say things like 'here's my ruling,' 'the decisive "
        "factor is,' and 'I've heard enough.' You are NEVER wishy-washy. Write like you're delivering a "
        "verdict on a panel show — clear, definitive, with acknowledged uncertainty only when it's genuine. "
        "If it's genuinely uncertain, say so directly: 'This is a coin flip and anyone who tells you "
        "otherwise is lying.'\n\n"
        "You have received analysis from 7 specialist agents. Your job is NOT to just count votes "
        "and NOT to make your own independent assessment. Your job is to SYNTHESIZE the agents' "
        "analyses using weighted averaging.\n\n"
        "WEIGHTING RULES:\n"
        "- Identify the SINGLE most important factor in this game (pace mismatch? defensive gap? "
        "shooting disparity? experience gap? injury concern? historical pattern?)\n"
        "- The agent whose specialty MATCHES that key factor gets 2x weight:\n"
        "  * Pace mismatch game? Weight Tempo Hawk 2x\n"
        "  * Elite defense vs elite offense? Weight Iron Curtain 2x\n"
        "  * Lower seed shoots lights out from 3? Weight Glass Cannon 2x\n"
        "  * Higher seed has injury/momentum concerns? Weight Whisper 2x\n"
        "  * Game matches a historical upset archetype? Weight Oracle 2x\n"
        "  * Experience/coaching mismatch? Weight Road Dog 2x\n"
        "  * Hot team vs cold team / momentum mismatch? Weight Streak 2x\n"
        "- If an agent has a better track record (see accuracy stats below), give their picks MORE weight.\n"
        "  HARD RULE: If an agent has 70%+ accuracy over 5+ games, treat them as 1.5x weight.\n"
        "  HARD RULE: If an agent has below 40% accuracy over 5+ games, treat them as 0.5x weight.\n\n"
        "CONFIDENCE RULES — THIS IS CRITICAL:\n"
        "- Your confidence should be the WEIGHTED AVERAGE of agent confidences, NOT your own "
        "independent assessment. If agents average 65%, you should be around 65%.\n"
        "- If 4+ agents agree but all have confidence under 70, this is NOT a confident pick. "
        "Set your confidence to the average, not higher.\n"
        "- On 8v9 games: Default to 50-55 confidence. These are COIN FLIPS.\n"
        "- On 5v12, 6v11, 7v10 games: Max confidence of 75 unless there's overwhelming evidence.\n"
        "- ONLY give 85+ confidence on 1v16, 2v15, or 3v14 games with a clear KenPom gap.\n\n"
        "OVERRIDE RULES — YOU MUST FOLLOW THESE:\n"
        "- If 6-7 specialists agree (6-1 or 7-0): You MUST pick the majority team. "
        "No exceptions. Your confidence = average of majority agents' confidence.\n"
        "- If 5-2: You MUST pick the majority UNLESS both dissenters have confidence "
        "above 75% AND all majority agents have confidence below 65%.\n"
        "- If 4-3: You make an independent judgment call, weighting the most relevant "
        "specialist 2x. This is the ONLY scenario where you should frequently disagree "
        "with the slim majority.\n"
        "- NEVER pick the minority side on a 5-2 or wider split.\n\n"
        "- You MUST write a 'dissent_report': acknowledge the STRONGEST counter-argument\n\n"
        f"AGENT TRACK RECORDS THIS SESSION:\n{accuracy_block}\n"
        f"{memory_block}\n"
        f"GAME: #{game.seed_a} {game.team_a} vs #{game.seed_b} {game.team_b} "
        f"({game.round_name}, {game.region})\n\n"
        f"Team A ({game.team_a}): adj_o={game.stats_a.get('adj_o', '?')}, "
        f"adj_d={game.stats_a.get('adj_d', '?')}, 3PT%={game.stats_a.get('three_pt_pct', '?')}, "
        f"record={game.stats_a.get('record', '?')}"
        + (f", key_players={game.stats_a['key_players']}" if game.stats_a.get('key_players') else "")
        + "\n"
        f"Team B ({game.team_b}): adj_o={game.stats_b.get('adj_o', '?')}, "
        f"adj_d={game.stats_b.get('adj_d', '?')}, 3PT%={game.stats_b.get('three_pt_pct', '?')}, "
        f"record={game.stats_b.get('record', '?')}"
        + (f", key_players={game.stats_b['key_players']}" if game.stats_b.get('key_players') else "")
        + "\n\n"
        f"ROUND 1 AGENT VOTES:\n{vote_block}\n"
        f"{r2_block}\n"
        f"{split_instructions}\n"
        "IMPORTANT: The final PICK is determined by mathematical probability combination.\n"
        "Your job is to EXPLAIN why the probabilities landed where they did, which agents were most\n"
        "influential, what the key uncertainty drivers are, and highlight any Round 2 position changes.\n\n"
        "BLIND SPOT CHECK: If your confidence is above 85 AND any agent dissented with confidence "
        "above 60, you MUST lower your confidence. No game with genuine dissent is a 85%+ lock.\n\n"
        "ROUND 2 FLIPS — YOU MUST ENGAGE WITH THESE:\n"
        "When agents change position in Round 2, you MUST address the specific argument that caused "
        "the flip and explain why it was or wasn't compelling. Do NOT dismiss flippers — engage with "
        "their reasoning. A flip means an agent saw evidence strong enough to change their mind. "
        "That evidence deserves a direct response, not a hand-wave.\n\n"
        "YOUR VERDICT MUST BE:\n"
        "- Maximum 50 words total\n"
        "- Name the winner(s) and loser(s) of the debate\n"
        "- Your pick with conviction\n"
        "- One memorable closing line\n\n"
        "Respond with ONLY a JSON object:\n"
        '{"pick": "<exact team name>", "confidence": <50-99>, '
        '"reasoning": "<max 50 words — name debate winners/losers, engage with any flips, deliver verdict, end with one memorable line>", '
        '"key_factor": "<the single most important factor>", '
        '"weighted_agent": "<the 1-2 agents who won the debate>", '
        '"dissent_report": "<the 1-2 agents who lost the debate and why — if they flipped, address what caused the flip>"}\n'
    )


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------
@dataclass
class Game:
    id: str
    team_a: str
    team_b: str
    seed_a: int
    seed_b: int
    region: str
    round_name: str
    stats_a: dict = field(default_factory=dict)
    stats_b: dict = field(default_factory=dict)


@dataclass
class AgentVote:
    agent_name: str
    pick: str
    confidence: int
    reasoning: str
    key_stat: str = ""
    response_time: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = "claude"
    error: str | None = None
    # Probabilistic output fields (v3)
    win_probability: float = 0.0   # team_a win probability (0.0-1.0)
    uncertainty: float = 0.10      # uncertainty estimate (0.0-0.20)
    round_number: int = 1          # 1 or 2
    position_change: str = "unchanged"  # "strengthened", "weakened", "flipped", "unchanged"
    rebuttal_target: str = ""      # which agent they rebutted in Round 2
    rebuttal_text: str = ""        # the rebuttal content


@dataclass
class ConductorDecision:
    pick: str
    confidence: int
    reasoning: str
    key_factor: str = ""
    weighted_agent: str = ""
    dissent_report: str = ""
    # Probabilistic fields (v3)
    combined_prob: float = 0.0       # combined team_a win probability
    combined_uncertainty: float = 0.0  # combined uncertainty


@dataclass
class UpsetScore:
    """Composite upset likelihood score."""
    score: float          # 0-100
    vote_split: str       # e.g., "4-2 for underdog"
    historical_upset_rate: float
    stat_edge: str        # which stat favors the underdog
    reasoning: str


@dataclass
class GameDebate:
    game: Game
    votes: list[AgentVote]
    conductor: ConductorDecision | None = None
    devils_advocate: AgentVote | None = None
    upset_score: UpsetScore | None = None
    vegas_comparison: dict | None = None
    timestamp: str = ""
    # Round 2 cross-attention (v3)
    round2_votes: list[AgentVote] = field(default_factory=list)
    # Market inefficiency analysis (v4)
    market_edge: object | None = None


# ---------------------------------------------------------------------------
# Upset confidence scoring
# ---------------------------------------------------------------------------
def calculate_upset_score(game: Game, votes: list[AgentVote]) -> UpsetScore | None:
    """
    Calculate composite upset likelihood. Only applies when there's a clear
    favorite by seed (lower seed = better).
    """
    if game.seed_a == game.seed_b:
        return None

    # Determine favorite and underdog
    if game.seed_a < game.seed_b:
        fav, dog = game.team_a, game.team_b
        fav_seed, dog_seed = game.seed_a, game.seed_b
        fav_stats, dog_stats = game.stats_a, game.stats_b
    else:
        fav, dog = game.team_b, game.team_a
        fav_seed, dog_seed = game.seed_b, game.seed_a
        fav_stats, dog_stats = game.stats_b, game.stats_a

    # 1. Vote split factor (0-40 points)
    dog_votes = sum(1 for v in votes if v.pick == dog and not v.error)
    total_votes = sum(1 for v in votes if not v.error and v.pick)
    vote_factor = (dog_votes / max(total_votes, 1)) * 40

    # 2. Historical upset rate for this seed matchup (0-25 points)
    seeds = tuple(sorted([fav_seed, dog_seed]))
    hist_rate = 1.0 - SEED_WIN_RATES.get(seeds, 0.5)
    hist_factor = hist_rate * 25

    # 3. Statistical edge for underdog (0-20 points)
    stat_edges = []
    stat_factor = 0

    # Check if underdog has better defense
    dog_d = dog_stats.get("adj_d", 100)
    fav_d = fav_stats.get("adj_d", 100)
    if dog_d < fav_d:
        stat_edges.append(f"Better defense ({dog_d} vs {fav_d} adj_d)")
        stat_factor += 7

    # Check if underdog shoots better from 3
    dog_3 = dog_stats.get("three_pt_pct", 0)
    fav_3 = fav_stats.get("three_pt_pct", 0)
    if dog_3 > fav_3:
        stat_edges.append(f"Better 3PT% ({dog_3} vs {fav_3})")
        stat_factor += 7

    # Check if underdog has better tempo control
    dog_tempo = dog_stats.get("adj_tempo", 67)
    fav_tempo = fav_stats.get("adj_tempo", 67)
    tempo_diff = abs(dog_tempo - fav_tempo)
    if tempo_diff > 3:
        stat_edges.append(f"Tempo mismatch ({tempo_diff:.1f} poss/game gap)")
        stat_factor += 6

    # 4. Agent confidence divergence (0-15 points)
    dog_confidences = [v.confidence for v in votes if v.pick == dog and not v.error]
    if dog_confidences and max(dog_confidences) >= 75:
        conf_factor = 15
    elif dog_confidences and max(dog_confidences) >= 65:
        conf_factor = 8
    else:
        conf_factor = 0

    total_score = min(100, vote_factor + hist_factor + stat_factor + conf_factor)

    vote_str = f"{dog_votes}-{total_votes - dog_votes} for {dog}" if dog_votes > 0 else f"0-{total_votes} (no upset support)"

    return UpsetScore(
        score=round(total_score, 1),
        vote_split=vote_str,
        historical_upset_rate=round(hist_rate * 100, 1),
        stat_edge="; ".join(stat_edges) if stat_edges else "None",
        reasoning=(
            f"Upset score {total_score:.0f}/100 for #{dog_seed} {dog} over #{fav_seed} {fav}. "
            f"Historical upset rate: {hist_rate*100:.1f}%. "
            f"Agent support: {vote_str}."
        ),
    )


# ---------------------------------------------------------------------------
# API calling with retries
# ---------------------------------------------------------------------------
def fuzzy_match_team(pick: str, team_a: str, team_b: str) -> str | None:
    pick_lower = pick.lower().strip()
    a_lower = team_a.lower().strip()
    b_lower = team_b.lower().strip()

    if pick_lower == a_lower:
        return team_a
    if pick_lower == b_lower:
        return team_b
    # Whole-word substring matching: check if pick or team name appears
    # as a complete word boundary match (not an arbitrary substring)
    import re as _re
    if _re.search(r'\b' + _re.escape(pick_lower) + r'\b', a_lower) or \
       _re.search(r'\b' + _re.escape(a_lower) + r'\b', pick_lower):
        return team_a
    if _re.search(r'\b' + _re.escape(pick_lower) + r'\b', b_lower) or \
       _re.search(r'\b' + _re.escape(b_lower) + r'\b', pick_lower):
        return team_b

    score_a = SequenceMatcher(None, pick_lower, a_lower).ratio()
    score_b = SequenceMatcher(None, pick_lower, b_lower).ratio()
    if max(score_a, score_b) > 0.75:
        return team_a if score_a > score_b else team_b
    return None


def parse_agent_response(raw: str, team_a: str, team_b: str) -> dict | None:
    # Strip markdown code fences (```json ... ```)
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", raw.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned.strip(), flags=re.MULTILINE)

    data = None
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    if data is None:
        # Try to find a complete JSON object (allowing nested braces)
        json_match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", cleaned, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

    if data is None:
        # Last resort: try to find partial JSON and complete it
        json_match = re.search(r"\{.*", cleaned, re.DOTALL)
        if json_match:
            partial = json_match.group().rstrip()
            # Try adding closing brace if truncated
            if not partial.endswith("}"):
                # Find last complete key-value pair
                last_comma = partial.rfind(",")
                last_colon = partial.rfind(":")
                if last_comma > 0 and last_comma > last_colon:
                    # Truncate at last comma (last complete key-value pair) and close
                    partial = partial[:last_comma] + "}"
                elif last_colon > 0:
                    # We're mid-value after a colon; check if value is a string
                    after_colon = partial[last_colon + 1:].strip()
                    if after_colon.startswith('"'):
                        # String value was truncated — close the string and object
                        partial = partial.rstrip('"') + '"}'
                    else:
                        # Non-string value (number/bool) was truncated — drop this key-value
                        last_comma_before = partial.rfind(",", 0, last_colon)
                        if last_comma_before > 0:
                            partial = partial[:last_comma_before] + "}"
                        else:
                            partial = partial + "}"
                else:
                    partial = partial + "}"
            try:
                data = json.loads(partial)
            except json.JSONDecodeError:
                pass

    if data is None:
        return None

    # Support BOTH old format (pick/confidence) and new format (team_a_win_prob/uncertainty)
    reasoning = data.get("reasoning", "")
    if not reasoning:
        return None

    is_conductor = "weighted_agent" in data or "dissent_report" in data

    # New probabilistic format
    if "team_a_win_prob" in data:
        try:
            prob = float(data["team_a_win_prob"])
        except (ValueError, TypeError):
            prob = 0.5
        prob = max(0.01, min(0.99, prob))
        data["team_a_win_prob"] = prob

        try:
            unc = float(data.get("uncertainty", 0.10))
        except (ValueError, TypeError):
            unc = 0.10
        data["uncertainty"] = max(0.0, min(0.20, unc))

        # Derive pick from probability: >0.5 = team_a, <=0.5 = team_b
        if prob > 0.5:
            data["pick"] = team_a
        else:
            data["pick"] = team_b

        # Derive confidence for backward compatibility
        data["confidence"] = max(50, min(99, int(abs(prob - 0.5) * 200)))

    else:
        # Legacy format: pick/confidence
        pick = data.get("pick", "")
        confidence = data.get("confidence", 0)
        if not pick:
            return None

        matched = fuzzy_match_team(pick, team_a, team_b)
        if matched is None:
            return None
        data["pick"] = matched

        try:
            confidence = int(confidence)
        except (ValueError, TypeError):
            confidence = 65
        data["confidence"] = max(50, min(99, confidence))

        # Derive probability from confidence for backward compat
        if data["pick"] == team_a:
            data["team_a_win_prob"] = 0.5 + data["confidence"] / 200
        else:
            data["team_a_win_prob"] = 0.5 - data["confidence"] / 200
        data["uncertainty"] = 0.10

    # Conductor uses "key_factor" (conceptual); agents use "key_stat" (must have a number)
    key_stat = data.get("key_stat", "") or data.get("key_factor", "")
    if not is_conductor and (not key_stat or not re.search(r"\d", key_stat)):
        data["confidence"] = min(data["confidence"], 69)

    return data


async def call_claude_api(
    client: httpx.AsyncClient,
    system_prompt: str,
    user_message: str,
    temperature: float = 0.5,
    timeout: float = 45.0,
) -> tuple[str, int, int]:
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    model = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": 512,
        "temperature": temperature,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_message}],
    }

    # Pillar 3: Cost guard — check budget before calling
    est_cost = estimate_call_cost("claude", estimated_input_tokens=500, estimated_output_tokens=200)
    try:
        await cost_guard.check_and_spend(est_cost, label=f"claude call")
    except BudgetExceededError:
        raise

    last_error = None
    for attempt in range(3):
        try:
            async with API_SEMAPHORE:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers=headers,
                    json=payload,
                    timeout=timeout,
                )

            if resp.status_code == 429:
                wait = (2 ** attempt) + random.random()
                log.warning(f"Rate limited, waiting {wait:.1f}s (attempt {attempt+1})")
                await asyncio.sleep(wait)
                continue

            resp.raise_for_status()
            body = resp.json()

            text = ""
            for block in body.get("content", []):
                if block.get("type") == "text":
                    text += block["text"]

            usage = body.get("usage", {})
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
            await cost_tracker.add(input_tokens, output_tokens, "claude")

            # Pillar 3: Adjust budget with actual cost vs estimate
            actual_cost = estimate_call_cost("claude", input_tokens, output_tokens)
            await cost_guard.record_actual(actual_cost, est_cost)

            return text, input_tokens, output_tokens

        except httpx.TimeoutException:
            last_error = "timeout"
            log.warning(f"Timeout on attempt {attempt+1}")
        except httpx.HTTPStatusError as e:
            last_error = f"HTTP {e.response.status_code}"
            if e.response.status_code >= 500:
                await asyncio.sleep((2 ** attempt) + random.random())
                continue
            raise
        except Exception as e:
            last_error = str(e)
            await asyncio.sleep((2 ** attempt) + random.random())

    raise RuntimeError(f"Claude API failed after 3 attempts: {last_error}")


async def call_gemini_api(
    client: httpx.AsyncClient,
    system_prompt: str,
    user_message: str,
    temperature: float = 0.5,
    timeout: float = 45.0,
) -> tuple[str, int, int]:
    from gemini_client import call_gemini_api as _call
    est_cost = estimate_call_cost("gemini", estimated_input_tokens=500, estimated_output_tokens=200)
    text, inp, out = await _call(
        client, system_prompt, user_message,
        temperature=temperature, timeout=timeout, semaphore=API_SEMAPHORE,
    )
    await cost_tracker.add(inp, out, "gemini")

    # Pillar 3: Adjust budget with actual cost vs estimate
    actual_cost = estimate_call_cost("gemini", inp, out)
    await cost_guard.record_actual(actual_cost, est_cost)

    return text, inp, out


# ---------------------------------------------------------------------------
# Mock responses for --dry-run
# ---------------------------------------------------------------------------
MOCK_RESPONSES = {
    "Tempo Hawk": '{"team_a_win_prob": 0.72, "uncertainty": 0.08, "reasoning": "Efficiency margin of +28.3 vs +19.1 is decisive. TEAM_A controls tempo at 68.1 possessions per game which neutralizes TEAM_B\'s preferred slow pace.", "key_stat": "Efficiency margin: +28.3 vs +19.1"}',
    "Iron Curtain": '{"team_a_win_prob": 0.78, "uncertainty": 0.05, "reasoning": "TEAM_A allows just 89.2 adj_d — elite level. TEAM_B has not faced a defense this disciplined. Their offense will stall.", "key_stat": "Opponent adj_d: 89.2 (top 5 nationally)"}',
    "Glass Cannon": '{"team_a_win_prob": 0.33, "uncertainty": 0.12, "reasoning": "TEAM_B shoots 38.5% from three with 4 capable shooters. In a dome setting, shooting variance actually increases — higher ceiling for the better shooting team.", "key_stat": "3PT%: 38.5% on 28 attempts/game"}',
    "Road Dog": '{"team_a_win_prob": 0.74, "uncertainty": 0.07, "reasoning": "TEAM_A\'s coach has 12 tournament wins and 3 Final Four appearances. Their senior backcourt has logged 47 career tournament minutes. That matters when it\'s tight with 4 minutes left.", "key_stat": "Coach tournament record: 12-5"}',
    "Whisper": '{"team_a_win_prob": 0.37, "uncertainty": 0.15, "reasoning": "Something is off with TEAM_A. Their star went 3-for-14 in the conference tournament final and has been notably absent from team social media. TEAM_B is flying under the radar with a 7-game win streak.", "key_stat": "TEAM_A star: 3-for-14 in conf tournament final"}',
    "Oracle": '{"team_a_win_prob": 0.64, "uncertainty": 0.06, "reasoning": "Historical base rate for this seed matchup gives TEAM_A a 64.2% edge. Both teams are close to their seed averages in quality metrics, so I see no reason to deviate significantly from the base rate.", "key_stat": "Historical win rate for higher seed: 64.2% (since 1985, n=152)"}',
    "Streak": '{"team_a_win_prob": 0.58, "uncertainty": 0.11, "reasoning": "TEAM_A is 7-3 in their last 10 but TEAM_B has been surging late. Conference tournament momentum matters more than season-long metrics in March. TEAM_B\'s recent form gives them a live shot.", "key_stat": "TEAM_B last 10: 8-2 with 4-game win streak"}',
}

MOCK_ROUND2_RESPONSES = {
    "Tempo Hawk": '{"team_a_win_prob": 0.70, "uncertainty": 0.06, "reasoning": "After reviewing all arguments, Iron Curtain\'s defensive analysis reinforced my tempo read. Glass Cannon\'s shooting argument is real but irrelevant against TEAM_A\'s perimeter defense.", "key_stat": "Efficiency margin: +28.3 vs +19.1", "position_change": "strengthened", "strongest_disagreement": "Glass Cannon overstates 3PT impact against elite perimeter D — TEAM_A holds opponents to 30.1% from three", "strongest_agreement": "Iron Curtain\'s adj_d analysis aligns perfectly with my pace control thesis"}',
    "Iron Curtain": '{"team_a_win_prob": 0.76, "uncertainty": 0.05, "reasoning": "My position is stronger after seeing the panel. Tempo Hawk\'s pace analysis reinforces the defensive stranglehold. Whisper\'s concerns about TEAM_A are narrative, not data.", "key_stat": "adj_d gap: 15.3 points", "position_change": "strengthened", "strongest_disagreement": "Whisper cites vibes over data — conference tournament performance is a tiny sample", "strongest_agreement": "Tempo Hawk\'s pace control thesis directly supports the defensive grind scenario"}',
    "Glass Cannon": '{"team_a_win_prob": 0.38, "uncertainty": 0.14, "reasoning": "Iron Curtain makes a fair point about TEAM_A\'s perimeter defense, but I still believe in shooting variance. However, I\'m less confident than before. The defensive scheme is more locked in than I initially assessed.", "key_stat": "3PT%: 38.5% but against 30.1% opp 3PT defense", "position_change": "weakened", "strongest_disagreement": "Oracle\'s base rate argument ignores that this specific TEAM_B shoots better than average 12-seeds", "strongest_agreement": "Iron Curtain\'s perimeter defense data weakened my shooting thesis somewhat"}',
    "Road Dog": '{"team_a_win_prob": 0.72, "uncertainty": 0.07, "reasoning": "Streak\'s momentum analysis is interesting but coaching and experience still trump hot streaks. My position is unchanged. TEAM_A\'s coach has been here before.", "key_stat": "Coach tournament record: 12-5", "position_change": "unchanged", "strongest_disagreement": "Streak overweights recent form — tournament coaching matters more than regular season streaks", "strongest_agreement": "Oracle\'s historical base rates align with my experience-based read"}',
    "Whisper": '{"team_a_win_prob": 0.40, "uncertainty": 0.13, "reasoning": "Oracle\'s base rates are compelling but miss the circumstantial factors I flagged. TEAM_A\'s star is clearly not right. However, I acknowledge my uncertainty is high.", "key_stat": "TEAM_A star: 3-for-14 in conf tourney", "position_change": "weakened", "strongest_disagreement": "Iron Curtain dismisses narrative factors but injuries and chemistry are real — ask 2023 Alabama", "strongest_agreement": "Streak\'s momentum data supports my concern about TEAM_A\'s recent trajectory"}',
    "Oracle": '{"team_a_win_prob": 0.65, "uncertainty": 0.06, "reasoning": "The panel largely confirms the base rate prediction. Glass Cannon\'s shooting argument has some merit but not enough to override historical patterns. My position is slightly strengthened.", "key_stat": "Historical upset rate: 35.8% for this seed matchup", "position_change": "strengthened", "strongest_disagreement": "Glass Cannon cherry-picks one stat (3PT%) and ignores the 64.2% historical favorite win rate across 152 games", "strongest_agreement": "Iron Curtain\'s defensive data provides a mechanism for WHY the base rate holds — defense travels in March"}',
    "Streak": '{"team_a_win_prob": 0.55, "uncertainty": 0.12, "reasoning": "Whisper\'s narrative analysis supported my momentum read, but Iron Curtain and Tempo Hawk have strong data. I\'m moving slightly toward TEAM_A but this remains a close call.", "key_stat": "TEAM_B conf tourney champion, 4-game win streak", "position_change": "weakened", "strongest_disagreement": "Tempo Hawk ignores that season-long tempo numbers include cupcake games — recent form is what matters", "strongest_agreement": "Whisper\'s narrative about TEAM_A\'s struggles reinforces my concern about their momentum"}',
}


def get_mock_response(agent_name: str, team_a: str, team_b: str, round_num: int = 1) -> str:
    if round_num == 2:
        source = MOCK_ROUND2_RESPONSES
    else:
        source = MOCK_RESPONSES
    template = source.get(agent_name, source.get("Tempo Hawk", MOCK_RESPONSES["Tempo Hawk"]))
    return template.replace("TEAM_A", team_a).replace("TEAM_B", team_b)


# ---------------------------------------------------------------------------
# Agent execution
# ---------------------------------------------------------------------------
async def run_agent(
    client: httpx.AsyncClient,
    agent: AgentConfig,
    game: Game,
    dry_run: bool = False,
    extra_prompt: str = "",
    memory_context: str = "",
) -> AgentVote:
    """Run a single agent's analysis of a game."""

    user_message = (
        f"Analyze this March Madness matchup and pick a winner:\n\n"
        f"#{game.seed_a} {game.team_a} vs #{game.seed_b} {game.team_b}\n"
        f"Round: {game.round_name} | Region: {game.region}\n\n"
        f"{game.team_a} stats: adj_o={game.stats_a.get('adj_o', '?')}, "
        f"adj_d={game.stats_a.get('adj_d', '?')}, tempo={game.stats_a.get('adj_tempo', '?')}, "
        f"3PT%={game.stats_a.get('three_pt_pct', '?')}, record={game.stats_a.get('record', '?')}, "
        f"conference={game.stats_a.get('conference', '?')} "
        f"({_get_conf_tier_label(game.stats_a.get('conference', ''))}), "
        f"KenPom={game.stats_a.get('kenpom_rank', '?')}"
        + (f", last_10={game.stats_a['last_10_record']}" if game.stats_a.get('last_10_record') else "")
        + (f", streak={game.stats_a['current_streak']}" if game.stats_a.get('current_streak') else "")
        + (f", conf_tourney={game.stats_a['conference_tourney_result']}" if game.stats_a.get('conference_tourney_result') else "")
        + (f", form_notes={game.stats_a['recent_form_notes']}" if game.stats_a.get('recent_form_notes') else "")
        + (f", turnover_rate={game.stats_a['turnover_rate']}" if game.stats_a.get('turnover_rate') else "")
        + (f", opp_fg_pct={game.stats_a['opp_fg_pct']}" if game.stats_a.get('opp_fg_pct') else "")
        + (f", experience={game.stats_a['experience_score']}/10" if game.stats_a.get('experience_score') else "")
        + (f", tournament_wins={' → '.join(game.stats_a['tournament_wins'])}" if game.stats_a.get('tournament_wins') else "")
        + (f"\n  *** INJURY ALERT: {game.stats_a['injury_notes']} ***" if game.stats_a.get('injury_notes') else "")
        + (f"\n  SITUATION: rest_days={game.stats_a.get('rest_days', '?')}, travel={game.stats_a.get('travel_distance_miles', '?')}mi" if game.stats_a.get('rest_days') else "")
        + (f"\n  KEY PLAYERS: {game.stats_a['key_players']}" if game.stats_a.get('key_players') else "")
        + "\n\n"
        f"{game.team_b} stats: adj_o={game.stats_b.get('adj_o', '?')}, "
        f"adj_d={game.stats_b.get('adj_d', '?')}, tempo={game.stats_b.get('adj_tempo', '?')}, "
        f"3PT%={game.stats_b.get('three_pt_pct', '?')}, record={game.stats_b.get('record', '?')}, "
        f"conference={game.stats_b.get('conference', '?')} "
        f"({_get_conf_tier_label(game.stats_b.get('conference', ''))}), "
        f"KenPom={game.stats_b.get('kenpom_rank', '?')}"
        + (f", last_10={game.stats_b['last_10_record']}" if game.stats_b.get('last_10_record') else "")
        + (f", streak={game.stats_b['current_streak']}" if game.stats_b.get('current_streak') else "")
        + (f", conf_tourney={game.stats_b['conference_tourney_result']}" if game.stats_b.get('conference_tourney_result') else "")
        + (f", form_notes={game.stats_b['recent_form_notes']}" if game.stats_b.get('recent_form_notes') else "")
        + (f", turnover_rate={game.stats_b['turnover_rate']}" if game.stats_b.get('turnover_rate') else "")
        + (f", opp_fg_pct={game.stats_b['opp_fg_pct']}" if game.stats_b.get('opp_fg_pct') else "")
        + (f", experience={game.stats_b['experience_score']}/10" if game.stats_b.get('experience_score') else "")
        + (f", tournament_wins={' → '.join(game.stats_b['tournament_wins'])}" if game.stats_b.get('tournament_wins') else "")
        + (f"\n  *** INJURY ALERT: {game.stats_b['injury_notes']} ***" if game.stats_b.get('injury_notes') else "")
        + (f"\n  SITUATION: rest_days={game.stats_b.get('rest_days', '?')}, travel={game.stats_b.get('travel_distance_miles', '?')}mi" if game.stats_b.get('rest_days') else "")
        + (f"\n  KEY PLAYERS: {game.stats_b['key_players']}" if game.stats_b.get('key_players') else "")
        + "\n"
    )

    if memory_context:
        user_message += f"\nYOUR PRIOR CALLS THIS SESSION:\n{memory_context}\n"

    if extra_prompt:
        user_message += f"\n{extra_prompt}\n"

    start = time.monotonic()

    if dry_run:
        await asyncio.sleep(random.uniform(0.1, 0.5))
        raw = get_mock_response(agent.name, game.team_a, game.team_b)
        input_tokens, output_tokens = 500, 150
        await cost_tracker.add(input_tokens, output_tokens, agent.model)
    else:
        # Dynamic temperature: close games get more creative/varied responses
        temp = _game_temperature(agent.temperature, game.seed_a, game.seed_b)
        try:
            if agent.model == "gemini":
                raw, input_tokens, output_tokens = await call_gemini_api(
                    client, agent.system_prompt, user_message,
                    temperature=temp,
                )
            else:
                raw, input_tokens, output_tokens = await call_claude_api(
                    client, agent.system_prompt, user_message,
                    temperature=temp,
                )
        except Exception as e:
            elapsed = time.monotonic() - start
            log.error(f"  {agent.name} FAILED ({agent.model}): {e}")
            return AgentVote(
                agent_name=agent.name, pick="", confidence=0, reasoning="",
                response_time=elapsed, model=agent.model, error=str(e),
            )

    elapsed = time.monotonic() - start

    parsed = parse_agent_response(raw, game.team_a, game.team_b)
    if parsed is None:
        log.warning(f"  {agent.name} returned unparseable response")
        return AgentVote(
            agent_name=agent.name, pick="", confidence=0, reasoning="",
            response_time=elapsed, input_tokens=input_tokens,
            output_tokens=output_tokens, model=agent.model,
            error=f"Unparseable response: {raw[:200]}",
        )

    # Apply bias boost — only in the toss-up zone (55-68) to act as tie-breaker,
    # not double-counting when the agent is already confident from its prompt bias
    bias_a = game.stats_a.get(agent.bias_field, 0)
    bias_b = game.stats_b.get(agent.bias_field, 0)

    # Handle non-numeric bias fields
    if agent.bias_field == "record":
        # Extract wins from "W-L" format; more wins = better
        def _parse_wins(val):
            if isinstance(val, str) and "-" in val:
                try:
                    return int(val.split("-")[0])
                except ValueError:
                    return 0
            return 0
        bias_a, bias_b = _parse_wins(bias_a), _parse_wins(bias_b)
    elif agent.bias_field == "current_streak":
        # Parse streak: "W7" > "W3" > "L2"; winning streaks positive, losing negative
        def _parse_streak(val):
            if isinstance(val, str) and len(val) >= 2:
                try:
                    num = int(val[1:])
                    return num if val[0].upper() == "W" else -num
                except ValueError:
                    return 0
            return 0
        bias_a, bias_b = _parse_streak(bias_a), _parse_streak(bias_b)

    if agent.bias_field == "adj_d":
        bias_team = game.team_a if bias_a < bias_b else game.team_b
    else:
        bias_team = game.team_a if bias_a > bias_b else game.team_b

    if parsed["pick"] == bias_team and 55 <= parsed["confidence"] <= 68:
        parsed["confidence"] = min(99, parsed["confidence"] + agent.bias_boost)

    return AgentVote(
        agent_name=agent.name,
        pick=parsed["pick"],
        confidence=parsed["confidence"],
        reasoning=parsed["reasoning"],
        key_stat=parsed.get("key_stat", ""),
        response_time=elapsed,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=agent.model,
        win_probability=parsed.get("team_a_win_prob", 0.5),
        uncertainty=parsed.get("uncertainty", 0.10),
    )


# ---------------------------------------------------------------------------
# Round 2: Cross-attention debate
# ---------------------------------------------------------------------------
def format_round1_outputs(votes: list[AgentVote], game: Game) -> str:
    """Format all Round 1 outputs for cross-attention in Round 2."""
    lines = []
    for v in votes:
        if v.error or not v.pick:
            continue
        emoji = AGENT_EMOJIS.get(v.agent_name, "")
        prob_str = f"team_a_win_prob={v.win_probability:.2f}" if v.win_probability else ""
        lines.append(
            f"{emoji} {v.agent_name}: Picked {v.pick} ({prob_str}, uncertainty={v.uncertainty:.2f})\n"
            f"   Reasoning: {v.reasoning}\n"
            f"   Key stat: {v.key_stat}"
        )
    return "\n\n".join(lines)


ROUND2_PROMPT_TEMPLATE = (
    "You gave your initial analysis in Round 1. Now here's what every other agent said:\n\n"
    "{round1_summary}\n\n"
    "ROUND 2 — CROSS-EXAMINATION:\n"
    "1. STRONGEST DISAGREEMENT: Which agent's argument is most wrong? Name them and rebut with ONE specific data point.\n"
    "2. STRONGEST AGREEMENT: Which agent reinforced your view? Why?\n"
    "3. POSITION UPDATE: strengthened, weakened, flipped, or unchanged?\n"
    "4. UPDATED WIN PROBABILITY: Your updated team_a_win_prob and uncertainty.\n\n"
    "ROUND 2 RULES — YOU MUST FOLLOW THESE:\n"
    "- If you picked the SAME team as the majority in Round 1, you MUST play devil's advocate: "
    "identify the STRONGEST argument for the OTHER side before confirming your pick.\n"
    "- If you FLIP your position in Round 2, your probability MUST be between 0.50-0.58 "
    "(you can't be confident in a position you just adopted).\n"
    "- You are NOT allowed to simply agree with other agents. You MUST add NEW information "
    "from YOUR specialty or hold your ground with a specific rebuttal.\n"
    "- 'I agree with [agent]' is BANNED. You must say something ORIGINAL from your lane.\n"
    "- STAY IN YOUR LANE: Your rebuttal must come from YOUR analytical specialty, not someone else's.\n\n"
    "IF YOU PICKED THE UNDERDOG IN ROUND 1:\n"
    "You are now the underdog's ADVOCATE. Your job is to DEFEND your upset pick against the "
    "chalk-picking agents. Do NOT flip back to chalk just because the majority disagreed. "
    "HOLD YOUR GROUND unless someone presented a specific data point that invalidates your thesis. "
    "'The other agents disagree' is NOT a reason to flip.\n\n"
    "YOUR REBUTTAL MUST BE:\n"
    "- Maximum 30 words\n"
    "- Name the agent you're rebutting\n"
    "- One specific data point proving them wrong\n"
    "- Whether you flipped, strengthened, or held\n"
    "- Updated probability\n\n"
    "The first team listed is: {team_a}\n"
    "The second team listed is: {team_b}\n\n"
    "Respond with ONLY a JSON object:\n"
    '{{"team_a_win_prob": <0.0-1.0>, "uncertainty": <0.0-0.20>, '
    '"reasoning": "<max 30 words — your rebuttal IN YOUR VOICE>", '
    '"key_stat": "<specific number or fact>", '
    '"position_change": "<strengthened|weakened|flipped|unchanged>", '
    '"strongest_disagreement": "<which agent BY NAME and why they are wrong — one sentence>", '
    '"strongest_agreement": "<which agent BY NAME reinforced your view — one sentence>"}}\n'
)


async def run_agent_round2(
    client: httpx.AsyncClient,
    agent: AgentConfig,
    game: Game,
    round1_summary: str,
    dry_run: bool = False,
) -> AgentVote:
    """Run an agent's Round 2 cross-examination response."""

    user_message = ROUND2_PROMPT_TEMPLATE.format(
        round1_summary=round1_summary,
        team_a=game.team_a,
        team_b=game.team_b,
    )

    start = time.monotonic()

    if dry_run:
        await asyncio.sleep(random.uniform(0.05, 0.2))
        raw = get_mock_response(agent.name, game.team_a, game.team_b, round_num=2)
        input_tokens, output_tokens = 800, 200
        await cost_tracker.add(input_tokens, output_tokens, agent.model)
    else:
        temp = _game_temperature(agent.temperature, game.seed_a, game.seed_b)
        try:
            if agent.model == "gemini":
                raw, input_tokens, output_tokens = await call_gemini_api(
                    client, agent.system_prompt, user_message,
                    temperature=temp,
                )
            else:
                raw, input_tokens, output_tokens = await call_claude_api(
                    client, agent.system_prompt, user_message,
                    temperature=temp,
                )
        except Exception as e:
            elapsed = time.monotonic() - start
            log.error(f"  {agent.name} Round 2 FAILED ({agent.model}): {e}")
            return AgentVote(
                agent_name=agent.name, pick="", confidence=0, reasoning="",
                response_time=elapsed, model=agent.model, error=str(e),
                round_number=2,
            )

    elapsed = time.monotonic() - start

    parsed = parse_agent_response(raw, game.team_a, game.team_b)
    if parsed is None:
        log.warning(f"  {agent.name} Round 2 returned unparseable response")
        return AgentVote(
            agent_name=agent.name, pick="", confidence=0, reasoning="",
            response_time=elapsed, input_tokens=input_tokens,
            output_tokens=output_tokens, model=agent.model,
            error=f"Unparseable R2 response: {raw[:200]}",
            round_number=2,
        )

    return AgentVote(
        agent_name=agent.name,
        pick=parsed["pick"],
        confidence=parsed["confidence"],
        reasoning=parsed["reasoning"],
        key_stat=parsed.get("key_stat", ""),
        response_time=elapsed,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=agent.model,
        win_probability=parsed.get("team_a_win_prob", 0.5),
        uncertainty=parsed.get("uncertainty", 0.10),
        round_number=2,
        position_change=parsed.get("position_change", "unchanged"),
        rebuttal_target=parsed.get("strongest_disagreement", ""),
        rebuttal_text=parsed.get("strongest_agreement", ""),
    )


# ---------------------------------------------------------------------------
# Probability combination
# ---------------------------------------------------------------------------
AGENT_WEIGHTS = {
    "Tempo Hawk": 1.0,
    "Iron Curtain": 1.0,
    "Glass Cannon": 1.0,
    "Road Dog": 1.0,
    "Whisper": 1.0,
    "Oracle": 1.2,   # Oracle gets slight base weight boost for calibration
    "Streak": 1.0,
}


def combine_probabilities(
    votes: list[AgentVote],
    agent_accuracy: dict[str, dict],
    game_weights: dict[str, float] | None = None,
) -> tuple[float, float]:
    """
    Combine agent probabilities into a single team_a_win_prob and uncertainty.
    Uses feature-driven weights from get_game_weights() when provided,
    falling back to static AGENT_WEIGHTS for backward compatibility.
    Returns (combined_prob, combined_uncertainty).
    """
    import math

    valid = [v for v in votes if not v.error and v.pick]
    if not valid:
        return 0.5, 0.15

    use_weights = game_weights if game_weights else AGENT_WEIGHTS

    weights = []
    probs = []
    uncertainties = []

    for v in valid:
        w = use_weights.get(v.agent_name, 1.0)

        # Accuracy track record adjustment (only when not using game_weights,
        # since get_game_weights already handles accuracy)
        if not game_weights:
            stats = agent_accuracy.get(v.agent_name, {})
            total = stats.get("total", 0)
            correct = stats.get("correct", 0)
            if total >= 5:
                acc = correct / total
                if acc >= 0.70:
                    w *= 1.5
                elif acc < 0.40:
                    w *= 0.5

        weights.append(w)
        probs.append(v.win_probability)
        uncertainties.append(v.uncertainty)

    total_weight = sum(weights)
    if total_weight == 0:
        return 0.5, 0.15

    # Weighted average of probabilities
    combined_prob = sum(w * p for w, p in zip(weights, probs)) / total_weight

    # Combined uncertainty: agent disagreement + average individual uncertainty
    disagreement = (sum(w * (p - combined_prob) ** 2 for w, p in zip(weights, probs)) / total_weight) ** 0.5
    avg_uncertainty = sum(w * u for w, u in zip(weights, uncertainties)) / total_weight
    combined_uncertainty = math.sqrt(disagreement ** 2 + avg_uncertainty ** 2)

    return (
        max(0.01, min(0.99, combined_prob)),
        max(0.0, min(0.25, combined_uncertainty)),
    )


async def run_conductor(
    client: httpx.AsyncClient,
    game: Game,
    votes: list[AgentVote],
    agent_accuracy: dict[str, dict],
    agent_memory: dict[str, list[str]] | None = None,
    dry_run: bool = False,
    round2_votes: list[AgentVote] | None = None,
) -> ConductorDecision:
    system_prompt = build_conductor_prompt(game, votes, agent_accuracy, agent_memory, round2_votes)
    user_message = "Make your final decision. Respond with ONLY the JSON object."

    # Compute feature-driven weights for this specific matchup
    round_num = {"R64": 1, "R32": 2, "S16": 3, "E8": 4, "F4": 5, "NCG": 6}.get(game.round_name, 1)
    game_wts = get_game_weights(game, agent_accuracy, round_number=round_num)

    # Compute mathematical probability combination from the FINAL round votes
    final_votes = round2_votes if round2_votes else votes
    combined_prob, combined_unc = combine_probabilities(
        final_votes, agent_accuracy, game_weights=game_wts
    )

    if dry_run:
        await asyncio.sleep(random.uniform(0.1, 0.3))
        # Use probability math to determine pick
        winner = game.team_a if combined_prob > 0.5 else game.team_b
        confidence = max(50, min(99, int(abs(combined_prob - 0.5) * 200)))
        raw = json.dumps({
            "pick": winner,
            "confidence": confidence,
            "reasoning": f"Combined probability analysis yields {combined_prob:.2f} for {game.team_a}. "
                         f"The panel's weighted consensus with uncertainty {combined_unc:.2f} favors {winner}.",
            "key_factor": "Weighted probability combination from 2-round debate",
            "weighted_agent": "Oracle — probability anchoring was most stable across both rounds",
            "dissent_report": "Glass Cannon's shooting variance argument is valid but weakened in Round 2 cross-examination.",
        })
        await cost_tracker.add(600, 200, "claude")
    else:
        raw, _, _ = await call_claude_api(
            client, system_prompt, user_message, temperature=0.4
        )

    parsed = parse_agent_response(raw, game.team_a, game.team_b)
    if parsed is None:
        log.warning("Conductor returned unparseable response, falling back to probability math")
        winner = game.team_a if combined_prob > 0.5 else game.team_b
        confidence = max(50, min(99, int(abs(combined_prob - 0.5) * 200)))
        return ConductorDecision(
            pick=winner, confidence=confidence,
            reasoning="Fallback to mathematical probability combination.",
            combined_prob=combined_prob, combined_uncertainty=combined_unc,
        )

    try:
        full = json.loads(raw) if isinstance(raw, str) else {}
    except Exception:
        full = {}

    # The PICK is determined by the math, not the conductor's qualitative judgment
    math_pick = game.team_a if combined_prob > 0.5 else game.team_b
    math_confidence = max(50, min(99, int(abs(combined_prob - 0.5) * 200)))

    return ConductorDecision(
        pick=math_pick,
        confidence=math_confidence,
        reasoning=parsed["reasoning"],
        key_factor=full.get("key_factor", ""),
        weighted_agent=full.get("weighted_agent", ""),
        dissent_report=full.get("dissent_report", ""),
        combined_prob=combined_prob,
        combined_uncertainty=combined_unc,
    )


# ---------------------------------------------------------------------------
# Anti-convergence
# ---------------------------------------------------------------------------
async def devils_advocate(
    client: httpx.AsyncClient,
    agent: AgentConfig,
    game: Game,
    unanimous_pick: str,
    dry_run: bool = False,
) -> AgentVote:
    other_team = game.team_b if unanimous_pick == game.team_a else game.team_a
    extra = (
        f"DEVIL'S ADVOCATE MODE: The other 6 agents ALL picked {unanimous_pick}. "
        f"Your job is to argue for {other_team}. Make the strongest possible case. "
        f"If you genuinely cannot make a case for {other_team}, explain why "
        f"{unanimous_pick} is such a lock — but you must TRY first."
    )
    return await run_agent(client, agent, game, dry_run=dry_run, extra_prompt=extra)


# ---------------------------------------------------------------------------
# Debate transcript generation
# ---------------------------------------------------------------------------
def generate_debate_transcript(debate: GameDebate) -> str:
    g = debate.game
    lines = [
        f"# \U0001f3c0 #{g.seed_a} {g.team_a} vs #{g.seed_b} {g.team_b} — {g.region} Region, {ROUND_DISPLAY.get(g.round_name, g.round_name)}",
        f"*{debate.timestamp}*\n",
        "---\n",
    ]

    # Round 1 — Independent Analysis
    lines.append("## Round 1 — Independent Analysis\n")
    for vote in debate.votes:
        if vote.error:
            continue
        emoji = AGENT_EMOJIS.get(vote.agent_name, "")
        model_tag = f" `[{vote.model}]`" if vote.model != "claude" else ""
        lines.append(
            f"{emoji} **{vote.agent_name.upper()}**{model_tag}: "
            f"\"{vote.reasoning}\"\n"
            f"   Win probability: {g.team_a} {vote.win_probability:.2f} \u00b1 {vote.uncertainty:.2f}\n"
            f"   *Key stat: {vote.key_stat}*\n"
        )

    # Round 2 — Cross-Examination
    if debate.round2_votes:
        lines.append("\n## Round 2 — Cross-Examination\n")
        for vote in debate.round2_votes:
            if vote.error:
                continue
            emoji = AGENT_EMOJIS.get(vote.agent_name, "")
            model_tag = f" `[{vote.model}]`" if vote.model != "claude" else ""
            pos_tag = vote.position_change.upper() if vote.position_change else "UNCHANGED"
            lines.append(
                f"{emoji} **{vote.agent_name.upper()}** (position: {pos_tag}){model_tag}:\n"
            )
            if vote.rebuttal_target:
                lines.append(f"   *Disagrees with:* {vote.rebuttal_target}\n")
            if vote.rebuttal_text:
                lines.append(f"   *Agrees with:* {vote.rebuttal_text}\n")
            lines.append(
                f"   \"{vote.reasoning}\"\n"
                f"   Updated probability: {g.team_a} {vote.win_probability:.2f} \u00b1 {vote.uncertainty:.2f}\n"
            )

    if debate.devils_advocate and not debate.devils_advocate.error:
        da = debate.devils_advocate
        emoji = AGENT_EMOJIS.get(da.agent_name, "")
        lines.append(
            f"\n### Devil's Advocate (unanimous vote triggered)\n"
            f"{emoji} **{da.agent_name.upper()}** *(forced contrarian)*: \"{da.reasoning}\"\n"
            f"   *Pick: **{da.pick}** ({da.confidence}%) | Key stat: {da.key_stat}*\n"
        )

    if debate.upset_score and debate.upset_score.score > 25:
        us = debate.upset_score
        lines.append(
            f"\n### Upset Watch\n"
            f"**Upset Score: {us.score}/100** | {us.reasoning}\n"
            f"   *Agent split: {us.vote_split} | Historical upset rate: {us.historical_upset_rate}%*\n"
            f"   *Statistical edges: {us.stat_edge}*\n"
        )

    if debate.vegas_comparison and debate.vegas_comparison.get("available"):
        vc = debate.vegas_comparison
        lines.append(
            f"\n### Swarm vs Vegas\n"
            f"   *{vc['summary']}*\n"
        )

    if debate.conductor:
        c = debate.conductor
        emoji = AGENT_EMOJIS.get("The Conductor", "")
        lines.append(f"\n---\n## \U0001f3bc The Conductor — Final Analysis\n")
        lines.append(
            f"Combined probability: {g.team_a} {c.combined_prob:.2f} \u00b1 {c.combined_uncertainty:.2f}\n"
        )
        lines.append(
            f"**PICK: {c.pick}** ({c.combined_prob*100:.0f}% — "
            f"{'dominant favorite' if abs(c.combined_prob - 0.5) > 0.25 else 'clear favorite' if abs(c.combined_prob - 0.5) > 0.15 else 'lean' if abs(c.combined_prob - 0.5) > 0.05 else 'genuine toss-up'}"
            f", {'low' if c.combined_uncertainty < 0.08 else 'moderate' if c.combined_uncertainty < 0.12 else 'high'} uncertainty)\n"
        )
        lines.append(
            f"\n{emoji} **THE CONDUCTOR**: \"{c.reasoning}\"\n"
        )
        if c.key_factor:
            lines.append(f"   *Key factor: {c.key_factor}*\n")
        if c.weighted_agent:
            lines.append(f"   *Most weighted: {c.weighted_agent}*\n")
        if c.dissent_report:
            lines.append(f"   *Dissent report: {c.dissent_report}*\n")

    # Use Round 2 final positions if available, otherwise Round 1
    final_vote_list = debate.round2_votes if debate.round2_votes else debate.votes
    # Build a map from agent name to their final pick (R2 overrides R1)
    final_picks: dict[str, str] = {}
    for v in debate.votes:
        if v.pick and not v.error:
            final_picks[v.agent_name] = v.pick
    if debate.round2_votes:
        for v in debate.round2_votes:
            if v.pick and not v.error:
                final_picks[v.agent_name] = v.pick  # R2 overrides R1

    pick_counts: dict[str, list[str]] = {}
    for agent_name, pick in final_picks.items():
        pick_counts.setdefault(pick, []).append(agent_name)

    # Specialist vote split (show emoji-name pairs)
    if pick_counts:
        sorted_teams = sorted(pick_counts.items(), key=lambda x: len(x[1]), reverse=True)
        majority_team = sorted_teams[0][0]
        majority_count = len(sorted_teams[0][1])
        minority_count = sum(len(agents) for _, agents in sorted_teams[1:])
        vote_emojis = []
        # Maintain original agent order from R1 votes
        for v in debate.votes:
            if v.agent_name in final_picks and not v.error:
                emoji = AGENT_EMOJIS.get(v.agent_name, "")
                vote_emojis.append(f"{emoji}{final_picks[v.agent_name]}")
        lines.append(f"\n---\n### Specialist Vote: {majority_count}-{minority_count} {majority_team}\n")
        lines.append(" ".join(vote_emojis) + "\n")

        # Show if Conductor agreed or disagreed
        if debate.conductor:
            if debate.conductor.pick == majority_team:
                lines.append(f"CONDUCTOR AGREES: {debate.conductor.pick} ({debate.conductor.confidence}%)\n")
            else:
                lines.append(
                    f"CONDUCTOR OVERRIDE: {debate.conductor.pick} ({debate.conductor.confidence}%) "
                    f"— sided with the minority\n"
                )

    lines.append("\n---\n### Vote Tally\n")
    for team, agents in pick_counts.items():
        lines.append(f"- **{team}**: {', '.join(agents)} ({len(agents)} votes)")

    # Market analysis section
    if debate.market_edge is not None:
        try:
            from market_analyzer import generate_market_section
            lines.append("\n" + generate_market_section(debate.market_edge))
        except Exception:
            pass

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main game analysis
# ---------------------------------------------------------------------------
async def analyze_game(
    client: httpx.AsyncClient,
    game: Game,
    agents: list[AgentConfig],
    agent_accuracy: dict[str, dict],
    game_index: int,
    total_games: int,
    dry_run: bool = False,
    groupthink_tracker: dict | None = None,
    agent_memory: dict[str, list[str]] | None = None,
    odds_data: list | None = None,
    verbose: bool = False,
    tournament_memory: TournamentMemoryStore | None = None,
    live_mode: bool = False,
) -> GameDebate:

    # Pillar 5: Create trace for this game
    tracer = GameTracer(game_id=game.id)
    tracer.log_round1_start(game.team_a, game.team_b, game.seed_a, game.seed_b)
    game_start_time = time.monotonic()

    log.info(
        f"[{tracer.trace_id}] Game {game_index}/{total_games} | {game.round_name} {game.region} | "
        f"#{game.seed_a} {game.team_a} vs #{game.seed_b} {game.team_b}"
    )

    # Build memory context per agent
    # Pillar 1: Tournament memory only provides context in live mode (real results exist)
    tasks = []
    for agent in agents:
        mem_ctx = ""
        if live_mode and tournament_memory:
            round_num = {"R64": 1, "R32": 2, "S16": 3, "E8": 4, "F4": 5, "NCG": 6}.get(game.round_name, 1)
            mem_ctx = tournament_memory.get_context(agent.name, round_num)
        elif agent_memory and agent.name in agent_memory:
            recent = agent_memory[agent.name][-5:]
            mem_ctx = "\n".join(recent)
        tasks.append(run_agent(client, agent, game, dry_run=dry_run, memory_context=mem_ctx))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Handle any exceptions returned by gather
    processed_results = []
    for i, r in enumerate(results):
        if isinstance(r, BaseException):
            agent_name = agents[i].name if i < len(agents) else f"agent_{i}"
            log.error(f"  {agent_name} raised exception: {r}")
            processed_results.append(AgentVote(
                agent_name=agent_name, pick="", confidence=0, reasoning="",
                model=agents[i].model if i < len(agents) else "claude",
                error=f"Exception: {r}",
            ))
        else:
            processed_results.append(r)
    results = processed_results

    valid_votes = [v for v in results if not v.error and v.pick]
    failed = [v for v in results if v.error]

    # Retry failed agents up to 2 more times
    for retry_round in range(2):
        if not failed:
            break
        log.info(f"  Retrying {len(failed)} failed agents (attempt {retry_round + 2}/3)")
        retry_tasks = []
        retry_agents_map = {}
        for fv in failed:
            agent = next((a for a in agents if a.name == fv.agent_name), None)
            if agent:
                mem_ctx = ""
                if agent_memory and agent.name in agent_memory:
                    recent = agent_memory[agent.name][-5:]
                    mem_ctx = "\n".join(recent)
                retry_tasks.append(run_agent(client, agent, game, dry_run=dry_run, memory_context=mem_ctx))
                retry_agents_map[len(retry_tasks) - 1] = fv.agent_name
        retry_results = await asyncio.gather(*retry_tasks, return_exceptions=True)

        # Filter out exceptions from retry results
        processed_retries = []
        for idx, rr in enumerate(retry_results):
            if isinstance(rr, BaseException):
                agent_name = retry_agents_map.get(idx, f"retry_{idx}")
                log.error(f"  Retry for {agent_name} raised exception: {rr}")
                processed_retries.append(AgentVote(
                    agent_name=agent_name, pick="", confidence=0, reasoning="",
                    error=f"Retry exception: {rr}",
                ))
            else:
                processed_retries.append(rr)
        retry_results = processed_retries

        # Replace failed results with successful retries
        new_results = list(results)
        for rr in retry_results:
            # Find and replace the failed entry
            for i, r in enumerate(new_results):
                if r.agent_name == rr.agent_name and r.error:
                    new_results[i] = rr
                    break
        results = new_results
        valid_votes = [v for v in results if not v.error and v.pick]
        failed = [v for v in results if v.error]

    for f in failed:
        log.warning(f"  {f.agent_name} failed: {f.error}")
    for v in valid_votes:
        model_tag = f" [{v.model}]" if v.model != "claude" else ""
        log.info(
            f"  {v.agent_name}{model_tag}: {v.pick} ({v.confidence}%) [{v.response_time:.1f}s]"
        )
        # Pillar 5: Trace agent votes
        tracer.log_agent_vote(
            v.agent_name, v.pick, v.win_probability, v.uncertainty,
            v.response_time, v.input_tokens + v.output_tokens, v.model,
        )

    if verbose:
        print(f"\n{'─'*60}")
        print(f"  DETAILED AGENT RESPONSES ({len(valid_votes)} valid, {len(failed)} failed)")
        print(f"{'─'*60}")
        for v in valid_votes:
            emoji = AGENT_EMOJIS.get(v.agent_name, "")
            model_tag = f" [{v.model}]" if v.model != "claude" else ""
            print(f"\n  {emoji} {v.agent_name}{model_tag}")
            print(f"     Pick: {v.pick} ({v.confidence}%)")
            print(f"     Reasoning: {v.reasoning}")
            print(f"     Key stat: {v.key_stat}")
            print(f"     Response time: {v.response_time:.1f}s")
        for f_vote in failed:
            emoji = AGENT_EMOJIS.get(f_vote.agent_name, "")
            print(f"\n  {emoji} {f_vote.agent_name} — FAILED")
            print(f"     Error: {f_vote.error}")
        print(f"{'─'*60}")

    if len(valid_votes) < 5:
        log.error(f"  Only {len(valid_votes)} valid votes — need at least 5. Skipping game.")
        return GameDebate(
            game=game, votes=list(results),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    # -----------------------------------------------------------------------
    # Pillar 2A: Adaptive Debate Rounds
    # Skip Round 2 for blowouts with unanimous consensus (saves ~30% API cost)
    # -----------------------------------------------------------------------
    seed_diff = abs(game.seed_a - game.seed_b)
    r1_picks = set(v.pick for v in valid_votes)
    skip_round2 = (seed_diff >= 10 and len(r1_picks) == 1)

    if skip_round2:
        log.info(f"  [ADAPTIVE] Skipping Round 2: seed diff={seed_diff}, unanimous R1 — saving API cost")
        round2_votes = []
        valid_r2 = []
        position_changes = []
        r1_summary = ""
    else:
        log.info(f"  Round 2: Cross-examination ({len(valid_votes)} agents)")
        r1_summary = format_round1_outputs(valid_votes, game)
        tracer.log_round2_start(len(valid_votes))

        r2_tasks = []
        for agent in agents:
            if any(v.agent_name == agent.name and not v.error for v in results):
                r2_tasks.append(run_agent_round2(client, agent, game, r1_summary, dry_run=dry_run))

        r2_results_raw = await asyncio.gather(*r2_tasks, return_exceptions=True)
        round2_votes = []
        for i, r in enumerate(r2_results_raw):
            if isinstance(r, BaseException):
                log.error(f"  Round 2 exception: {r}")
            elif r.error:
                log.warning(f"  {r.agent_name} Round 2 failed: {r.error}")
                round2_votes.append(r)
            else:
                round2_votes.append(r)

        valid_r2 = [v for v in round2_votes if not v.error and v.pick]
        position_changes = [v for v in valid_r2 if v.position_change in ("weakened", "flipped")]

        for v in valid_r2:
            model_tag = f" [{v.model}]" if v.model != "claude" else ""
            log.info(
                f"  R2 {v.agent_name}{model_tag}: {v.pick} (prob={v.win_probability:.2f}) "
                f"[{v.position_change}] [{v.response_time:.1f}s]"
            )
            # Pillar 5: Trace position changes
            if v.position_change in ("weakened", "flipped"):
                r1_pick = next((rv.pick for rv in valid_votes if rv.agent_name == v.agent_name), "?")
                tracer.log_position_change(v.agent_name, r1_pick, v.pick, v.position_change)
        if position_changes:
            log.info(f"  {len(position_changes)} agent(s) changed position in Round 2")

        if verbose and valid_r2:
            print(f"\n{'─'*60}")
            print(f"  ROUND 2 CROSS-EXAMINATION ({len(valid_r2)} responses)")
            print(f"{'─'*60}")
            for v in valid_r2:
                emoji = AGENT_EMOJIS.get(v.agent_name, "")
                print(f"\n  {emoji} {v.agent_name} (position: {v.position_change.upper()})")
                print(f"     Prob: {game.team_a} {v.win_probability:.2f} ± {v.uncertainty:.2f}")
                print(f"     Disagrees with: {v.rebuttal_target[:80]}...")
                print(f"     Agrees with: {v.rebuttal_text[:80]}...")
                print(f"     Reasoning: {v.reasoning}")
            print(f"{'─'*60}")

    # Anti-convergence: check for unanimity (using Round 2 picks if available)
    final_votes = valid_r2 if valid_r2 else valid_votes
    devils_advocate_vote = None
    picks = set(v.pick for v in final_votes)
    if len(picks) == 1:
        unanimous_pick = list(picks)[0]
        log.info(f"  UNANIMOUS for {unanimous_pick} — triggering devil's advocate")

        if groupthink_tracker is not None:
            groupthink_tracker["unanimous"] = groupthink_tracker.get("unanimous", 0) + 1
            groupthink_tracker["total"] = groupthink_tracker.get("total", 0) + 1
            rate = groupthink_tracker["unanimous"] / groupthink_tracker["total"]
            if rate > 0.6 and groupthink_tracker["total"] >= 5:
                log.warning(
                    f"  GROUPTHINK WARNING: {rate:.0%} unanimous rate "
                    f"({groupthink_tracker['unanimous']}/{groupthink_tracker['total']})"
                )

        da_agent = random.choice(agents)
        devils_advocate_vote = await devils_advocate(
            client, da_agent, game, unanimous_pick, dry_run=dry_run
        )
        if not devils_advocate_vote.error:
            log.info(
                f"  Devil's advocate ({da_agent.name}): "
                f"{devils_advocate_vote.pick} ({devils_advocate_vote.confidence}%)"
            )
    else:
        if groupthink_tracker is not None:
            groupthink_tracker["total"] = groupthink_tracker.get("total", 0) + 1

    # Calculate upset score
    upset_score = calculate_upset_score(game, valid_votes)
    if upset_score and upset_score.score >= 40:
        log.info(f"  UPSET WATCH: {upset_score.score}/100 — {upset_score.reasoning}")

    # If devil's advocate made a valid case, include it as a half-weighted 8th vote
    conductor_votes = list(valid_votes)
    if devils_advocate_vote and not devils_advocate_vote.error and devils_advocate_vote.pick:
        # Halve the DA's confidence to represent its reduced weight
        da_for_conductor = AgentVote(
            agent_name=f"{devils_advocate_vote.agent_name} (Devil's Advocate)",
            pick=devils_advocate_vote.pick,
            confidence=max(50, devils_advocate_vote.confidence // 2),
            reasoning=f"[DEVIL'S ADVOCATE] {devils_advocate_vote.reasoning}",
            key_stat=devils_advocate_vote.key_stat,
            model=devils_advocate_vote.model,
        )
        conductor_votes.append(da_for_conductor)

    # Run The Conductor (sees BOTH rounds)
    conductor_decision = await run_conductor(
        client, game, conductor_votes, agent_accuracy, agent_memory, dry_run=dry_run,
        round2_votes=valid_r2 if valid_r2 else None,
    )

    # On unanimous original votes, cap conductor confidence (DA exists for a reason)
    if devils_advocate_vote and not devils_advocate_vote.error and devils_advocate_vote.pick:
        if conductor_decision.confidence > 82:
            conductor_decision.confidence = 82

    # Upset score influences conductor confidence: high upset score caps the favorite
    if upset_score and upset_score.score >= 60:
        # Determine if conductor picked the favorite
        fav_seed = min(game.seed_a, game.seed_b)
        fav_name = game.team_a if game.seed_a == fav_seed else game.team_b
        if conductor_decision.pick == fav_name and conductor_decision.confidence > 72:
            log.info(
                f"  UPSET SCORE CAP: Score {upset_score.score}/100 → "
                f"capping favorite confidence from {conductor_decision.confidence} to 72"
            )
            conductor_decision.confidence = 72

    # Enforce majority override rule: Conductor cannot override 5-2 or wider splits
    # But first — use agent accuracy to mechanically adjust the override threshold
    # If high-accuracy agents are in the minority, lower the override bar
    pick_counts_check: dict[str, int] = {}
    for v in valid_votes:
        if v.pick:
            pick_counts_check[v.pick] = pick_counts_check.get(v.pick, 0) + 1
    if pick_counts_check:
        majority_team = max(pick_counts_check, key=pick_counts_check.get)
        majority_count = pick_counts_check[majority_team]
        minority_count = len(valid_votes) - majority_count
        if majority_count >= 5 and conductor_decision.pick != majority_team:
            log.warning(
                f"  CONDUCTOR OVERRIDE BLOCKED: Tried to pick {conductor_decision.pick} "
                f"against {majority_count}-{minority_count} majority for {majority_team}. "
                f"Forcing majority pick."
            )
            # Calculate average confidence of majority agents
            majority_confs = [v.confidence for v in valid_votes if v.pick == majority_team]
            avg_conf = int(sum(majority_confs) / len(majority_confs)) if majority_confs else 65
            conductor_decision.pick = majority_team
            conductor_decision.confidence = avg_conf
            conductor_decision.dissent_report = (
                f"[OVERRIDE: Conductor was overridden — original pick disagreed with "
                f"{majority_count}-{minority_count} specialist majority] "
                + conductor_decision.dissent_report
            )

    # Pillar 5: Trace conductor decision
    tracer.log_conductor_decision(
        conductor_decision.pick, conductor_decision.confidence,
        conductor_decision.combined_prob, conductor_decision.combined_uncertainty,
    )
    log.info(
        f"  [{tracer.trace_id}] CONDUCTOR: {conductor_decision.pick} ({conductor_decision.confidence}%)"
    )

    if verbose:
        # Print vote tally and conductor decision (use R2 final positions)
        final_picks_v: dict[str, str] = {}
        for v in valid_votes:
            if v.pick:
                final_picks_v[v.agent_name] = v.pick
        if valid_r2:
            for v in valid_r2:
                if v.pick:
                    final_picks_v[v.agent_name] = v.pick
        pc = {}
        for pick in final_picks_v.values():
            pc[pick] = pc.get(pick, 0) + 1
        majority_team_v = max(pc, key=pc.get) if pc else "?"
        majority_n = pc.get(majority_team_v, 0)
        minority_n = len(final_picks_v) - majority_n
        print(f"\n  VOTE TALLY: {majority_n}-{minority_n} for {majority_team_v}")
        for v in valid_votes:
            emoji = AGENT_EMOJIS.get(v.agent_name, "")
            final_pick = final_picks_v.get(v.agent_name, v.pick)
            print(f"    {emoji} {v.agent_name}: {final_pick}")
        print(f"\n  🎼 CONDUCTOR: {conductor_decision.pick} ({conductor_decision.confidence}%)")
        if conductor_decision.pick == majority_team_v:
            print(f"     Status: AGREES with majority")
        else:
            print(f"     Status: OVERRIDES majority (picked minority)")
        print(f"     Key factor: {conductor_decision.key_factor}")
        print(f"     Dissent report: {conductor_decision.dissent_report}")
        print()

    # Blind spot check
    if conductor_decision.confidence > 85:
        high_dissent = [
            v for v in valid_votes
            if v.pick != conductor_decision.pick and v.confidence > 70
        ]
        if high_dissent:
            names = ", ".join(v.agent_name for v in high_dissent)
            log.warning(
                f"  BLIND SPOT: Conductor at {conductor_decision.confidence}% "
                f"but {names} dissented with >70% confidence"
            )

    # Vegas comparison + Market Inefficiency Analysis
    vegas_comp = None
    market_edge = None
    if odds_data:
        try:
            from odds_tracker import find_game_odds, compare_swarm_to_vegas
            game_odds = find_game_odds(game.team_a, game.team_b, odds_data)
            if game_odds:
                vegas_comp = compare_swarm_to_vegas(
                    conductor_decision.pick, conductor_decision.confidence,
                    game_odds, game.team_a, game.team_b,
                )
                if vegas_comp.get("available"):
                    log.info(f"  VEGAS: {vegas_comp['summary']}")

                # Market inefficiency detection
                try:
                    from market_analyzer import analyze_game as ma_analyze
                    agent_votes_for_market = [
                        {"agent_name": v.agent_name, "win_probability": v.win_probability}
                        for v in final_votes
                        if not v.error and v.pick
                    ]
                    market_edge = ma_analyze(
                        game_id=game.id,
                        team_a=game.team_a, team_b=game.team_b,
                        seed_a=game.seed_a, seed_b=game.seed_b,
                        region=game.region, round_name=game.round_name,
                        swarm_prob=conductor_decision.combined_prob,
                        combined_uncertainty=conductor_decision.combined_uncertainty,
                        agent_votes=agent_votes_for_market,
                        game_odds=game_odds,
                    )
                    if market_edge and abs(market_edge.edge) > 0.05:
                        log.info(
                            f"  MARKET EDGE: {abs(market_edge.edge):.1%} — "
                            f"{market_edge.recommendation}"
                        )
                except Exception as e:
                    log.debug(f"  Market analysis failed: {e}")
        except Exception as e:
            log.debug(f"  Vegas comparison failed: {e}")

    # Update agent memory (legacy format)
    if agent_memory is not None:
        for v in valid_votes:
            if v.agent_name not in agent_memory:
                agent_memory[v.agent_name] = []
            agent_memory[v.agent_name].append(
                f"{game.round_name}: picked {v.pick} ({v.confidence}%) "
                f"in #{game.seed_a} {game.team_a} vs #{game.seed_b} {game.team_b}"
            )

    # Pillar 1A: Record picks in tournament memory (predictions only, no fake results)
    game_label = f"#{game.seed_a} {game.team_a} vs #{game.seed_b} {game.team_b}"
    game_type = classify_game_type(game.seed_a, game.seed_b)
    if tournament_memory:
        for v in valid_votes:
            r2_v = next((r2 for r2 in valid_r2 if r2.agent_name == v.agent_name), None)
            pos_change = r2_v.position_change if r2_v else "unchanged"
            tournament_memory.record_pick(
                agent_name=v.agent_name,
                game_label=game_label,
                pick=v.pick,
                probability=v.win_probability,
                round_name=game.round_name,
                game_type=game_type,
                position_change=pos_change,
            )

    # Pillar 5B: Record agent performance metrics
    for v in valid_votes:
        r2_v = next((r2 for r2 in valid_r2 if r2.agent_name == v.agent_name), None)
        perf_tracker.record_from_votes(game.id, v, r2_v)

    # Pillar 5: Log game completion
    game_elapsed = time.monotonic() - game_start_time
    game_tokens = sum(v.input_tokens + v.output_tokens for v in valid_votes)
    game_tokens += sum(v.input_tokens + v.output_tokens for v in valid_r2)
    tracer.log_game_complete(game_elapsed, game_tokens, 0.0)

    debate = GameDebate(
        game=game,
        votes=list(results),
        conductor=conductor_decision,
        devils_advocate=devils_advocate_vote,
        upset_score=upset_score,
        vegas_comparison=vegas_comp,
        timestamp=datetime.now(timezone.utc).isoformat(),
        round2_votes=round2_votes,
        market_edge=market_edge,
    )

    # Write to Supabase immediately
    # R1/R2 vote splits for Supabase
    r1_a = sum(1 for v in valid_votes if v.pick == game.team_a)
    r1_b = len(valid_votes) - r1_a
    r2_a = sum(1 for v in valid_r2 if v.pick == game.team_a) if valid_r2 else 0
    r2_b = len(valid_r2) - r2_a if valid_r2 else 0

    game_record = {
        "id": game.id,
        "team_a": game.team_a,
        "team_b": game.team_b,
        "seed_a": game.seed_a,
        "seed_b": game.seed_b,
        "region": game.region,
        "round": game.round_name,
        "pick": conductor_decision.pick,
        "confidence": conductor_decision.confidence,
        "reasoning": conductor_decision.reasoning,
        "key_factor": conductor_decision.key_factor,
        "dissent_report": conductor_decision.dissent_report,
        "upset_score": upset_score.score if upset_score else None,
        "vote_count_a": r1_a,
        "vote_count_b": r1_b,
        "analyzed_at": debate.timestamp,
        # New v3 fields
        "team_a_win_prob": round(conductor_decision.combined_prob, 4),
        "combined_uncertainty": round(conductor_decision.combined_uncertainty, 4),
        "round1_vote_split": f"{r1_a}-{r1_b}",
        "round2_vote_split": f"{r2_a}-{r2_b}" if valid_r2 else "",
        "position_changes": len(position_changes),
    }
    # Add vegas/market fields if available
    if vegas_comp and vegas_comp.get("available"):
        game_record["vegas_spread"] = vegas_comp.get("spread")
        game_record["swarm_edge"] = round(
            conductor_decision.combined_prob - vegas_comp.get("vegas_implied_prob", 0.5), 4
        ) if vegas_comp.get("vegas_implied_prob") else None
    if odds_data:
        try:
            from odds_tracker import find_game_odds
            go = find_game_odds(game.team_a, game.team_b, odds_data)
            if go:
                mls = go.get("moneylines", {})
                for tk, ml in mls.items():
                    from odds_tracker import _team_match
                    if _team_match(game.team_a, tk):
                        game_record["vegas_moneyline_a"] = ml.get("price")
                    elif _team_match(game.team_b, tk):
                        game_record["vegas_moneyline_b"] = ml.get("price")
        except Exception:
            pass
    if not supabase_client.write_game_result(game_record):
        log.warning(f"  Supabase: failed to write game result for {game.id}")

    vote_records = []
    for v in valid_votes:
        vote_records.append({
            "game_id": game.id,
            "agent_name": v.agent_name,
            "pick": v.pick,
            "confidence": v.confidence,
            "reasoning": v.reasoning,
            "key_stat": v.key_stat,
            "model": v.model,
            "round_number": 1,
            "win_probability": round(v.win_probability, 4),
            "uncertainty": round(v.uncertainty, 4),
        })
    # Add Round 2 votes
    for v in valid_r2:
        vote_records.append({
            "game_id": game.id,
            "agent_name": v.agent_name,
            "pick": v.pick,
            "confidence": v.confidence,
            "reasoning": v.reasoning,
            "key_stat": v.key_stat,
            "model": v.model,
            "round_number": 2,
            "win_probability": round(v.win_probability, 4),
            "uncertainty": round(v.uncertainty, 4),
            "position_change": v.position_change,
            "rebuttal_target": v.rebuttal_target[:500] if v.rebuttal_target else "",
            "rebuttal_text": v.rebuttal_text[:500] if v.rebuttal_text else "",
        })
    if vote_records:
        if not supabase_client.write_agent_votes(vote_records):
            log.warning(f"  Supabase: failed to write agent votes for {game.id}")

    # Update status.json
    try:
        supabase_client.write_status({
            "current_game": game_index,
            "total_games": total_games,
            "last_completed": f"#{game.seed_a} {game.team_a} vs #{game.seed_b} {game.team_b}",
            "last_pick": conductor_decision.pick,
            "last_confidence": conductor_decision.confidence,
        })
    except Exception as e:
        log.warning(f"  Failed to write status.json: {e}")

    # Save debate transcript
    transcript = generate_debate_transcript(debate)
    transcript_dir = Path(__file__).parent / "debates"
    transcript_dir.mkdir(exist_ok=True)
    safe_name = re.sub(r"[^a-zA-Z0-9]", "_", f"{game.team_a}_vs_{game.team_b}")
    transcript_file = transcript_dir / f"{game.round_name}_{safe_name}.md"
    with open(transcript_file, "w") as f:
        f.write(transcript)

    return debate


# ---------------------------------------------------------------------------
# Bracket loading and progression
# ---------------------------------------------------------------------------
ROUND_NAMES = ["R64", "R32", "S16", "E8", "F4", "NCG"]
ROUND_DISPLAY = {
    "R64": "Round of 64", "R32": "Round of 32", "S16": "Sweet 16",
    "E8": "Elite 8", "F4": "Final Four", "NCG": "National Championship",
}

# Standard NCAA first-round matchup seeds
FIRST_ROUND_MATCHUPS = [(1, 16), (8, 9), (5, 12), (4, 13), (6, 11), (3, 14), (7, 10), (2, 15)]


def load_bracket() -> dict | None:
    bracket_file = Path(__file__).parent / "bracket_loader.py"
    if not bracket_file.exists():
        return None
    import importlib.util
    spec = importlib.util.spec_from_file_location("bracket_loader", bracket_file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, "BRACKET_2026", None)


def generate_first_round_games(bracket: dict) -> list[Game]:
    games = []
    for region, teams in bracket.items():
        seed_map = {t["seed"]: t for t in teams}
        for seed_a, seed_b in FIRST_ROUND_MATCHUPS:
            team_a = seed_map.get(seed_a)
            team_b = seed_map.get(seed_b)
            if team_a and team_b:
                games.append(Game(
                    id=str(uuid.uuid4()),
                    team_a=team_a["name"], team_b=team_b["name"],
                    seed_a=seed_a, seed_b=seed_b,
                    region=region, round_name="R64",
                    stats_a=team_a, stats_b=team_b,
                ))
    return games


def advance_bracket(
    current_round_results: list[GameDebate],
    current_round_name: str,
) -> list[Game]:
    """
    Generate next-round matchups from current round results.
    Winners are paired in bracket order (game 1 winner vs game 2 winner, etc).
    """
    next_round_idx = ROUND_NAMES.index(current_round_name) + 1
    if next_round_idx >= len(ROUND_NAMES):
        return []
    next_round_name = ROUND_NAMES[next_round_idx]

    # Group results by region
    by_region: dict[str, list[GameDebate]] = {}
    for debate in current_round_results:
        region = debate.game.region
        by_region.setdefault(region, []).append(debate)

    next_games = []

    if next_round_name == "F4":
        # Final Four: winners of each region play each other
        # Convention: East vs West, South vs Midwest
        region_winners = {}
        for debate in current_round_results:
            if debate.conductor:
                region_winners[debate.game.region] = debate
        pairings = [("East", "West"), ("South", "Midwest")]
        for r1, r2 in pairings:
            d1 = region_winners.get(r1)
            d2 = region_winners.get(r2)
            if d1 and d2 and d1.conductor and d2.conductor:
                w1 = _get_winner_data(d1)
                w2 = _get_winner_data(d2)
                next_games.append(Game(
                    id=str(uuid.uuid4()),
                    team_a=w1["name"], team_b=w2["name"],
                    seed_a=w1["seed"], seed_b=w2["seed"],
                    region="Final Four", round_name="F4",
                    stats_a=w1, stats_b=w2,
                ))
    elif next_round_name == "NCG":
        # Championship: two F4 winners
        for debate in current_round_results:
            pass  # will be handled as just 2 debates -> 1 game
        if len(current_round_results) == 2:
            d1, d2 = current_round_results[0], current_round_results[1]
            if d1.conductor and d2.conductor:
                w1 = _get_winner_data(d1)
                w2 = _get_winner_data(d2)
                next_games.append(Game(
                    id=str(uuid.uuid4()),
                    team_a=w1["name"], team_b=w2["name"],
                    seed_a=w1["seed"], seed_b=w2["seed"],
                    region="Championship", round_name="NCG",
                    stats_a=w1, stats_b=w2,
                ))
    else:
        # Within a region: pair adjacent games
        for region, debates in by_region.items():
            for i in range(0, len(debates) - 1, 2):
                d1 = debates[i]
                d2 = debates[i + 1]
                if d1.conductor and d2.conductor:
                    w1 = _get_winner_data(d1)
                    w2 = _get_winner_data(d2)
                    next_games.append(Game(
                        id=str(uuid.uuid4()),
                        team_a=w1["name"], team_b=w2["name"],
                        seed_a=w1["seed"], seed_b=w2["seed"],
                        region=region, round_name=next_round_name,
                        stats_a=w1, stats_b=w2,
                    ))

    return next_games


def _get_winner_data(debate: GameDebate) -> dict:
    """Extract winner's data from a completed debate, updating tournament context."""
    pick = debate.conductor.pick
    g = debate.game
    if pick == g.team_a:
        stats = g.stats_a.copy()
        stats["name"] = g.team_a
        stats["seed"] = g.seed_a
        opponent_seed = g.seed_b
        opponent_name = g.team_b
    else:
        stats = g.stats_b.copy()
        stats["name"] = g.team_b
        stats["seed"] = g.seed_b
        opponent_seed = g.seed_a
        opponent_name = g.team_a

    # --- Update tournament context for later rounds ---
    round_display = ROUND_DISPLAY.get(g.round_name, g.round_name)

    # Track tournament wins for momentum agents
    tourney_wins = stats.get("tournament_wins", [])
    tourney_wins.append(f"Beat #{opponent_seed} {opponent_name} in {round_display}")
    stats["tournament_wins"] = tourney_wins

    # Update streak: every win extends it
    streak = stats.get("current_streak", "W0")
    if isinstance(streak, str) and streak.startswith("W"):
        try:
            n = int(streak[1:])
            stats["current_streak"] = f"W{n + 1}"
        except ValueError:
            stats["current_streak"] = "W1"
    else:
        stats["current_streak"] = "W1"

    # Update last_10 to reflect the tournament win
    last_10 = stats.get("last_10_record", "5-5")
    if isinstance(last_10, str) and "-" in last_10:
        try:
            w, l = last_10.split("-")
            w, l = int(w), int(l)
            # Slide the window: add a W, drop oldest assumed split
            w = min(10, w + 1)
            total = w + l
            if total > 10:
                l = max(0, l - 1)
            stats["last_10_record"] = f"{w}-{l}"
        except ValueError:
            pass

    # Add tournament journey to form notes so narrative agents can use it
    journey = " → ".join(tourney_wins)
    stats["recent_form_notes"] = (
        f"NCAA Tournament run: {journey}. "
        f"Confidence: {debate.conductor.confidence}% in last win."
    )
    stats["conference_tourney_result"] = stats.get("conference_tourney_result", "") + \
        f" | NCAA: {len(tourney_wins)} win(s)"

    return stats


def make_sample_games() -> list[Game]:
    return [
        Game(
            id=str(uuid.uuid4()),
            team_a="Duke", team_b="American",
            seed_a=1, seed_b=16, region="East", round_name="R64",
            stats_a={"adj_o": 123.5, "adj_d": 89.2, "adj_tempo": 68.1,
                      "three_pt_pct": 38.2, "record": "30-3", "conference": "ACC", "kenpom_rank": 1},
            stats_b={"adj_o": 101.2, "adj_d": 104.5, "adj_tempo": 65.3,
                      "three_pt_pct": 33.1, "record": "21-12", "conference": "Patriot", "kenpom_rank": 180},
        ),
        Game(
            id=str(uuid.uuid4()),
            team_a="Michigan", team_b="UCF",
            seed_a=5, seed_b=12, region="Midwest", round_name="R64",
            stats_a={"adj_o": 115.3, "adj_d": 95.8, "adj_tempo": 67.5,
                      "three_pt_pct": 37.8, "record": "22-10", "conference": "Big Ten", "kenpom_rank": 28},
            stats_b={"adj_o": 113.9, "adj_d": 96.2, "adj_tempo": 70.1,
                      "three_pt_pct": 36.9, "record": "25-7", "conference": "Big 12", "kenpom_rank": 35},
        ),
        Game(
            id=str(uuid.uuid4()),
            team_a="Arizona", team_b="Grand Canyon",
            seed_a=3, seed_b=14, region="West", round_name="R64",
            stats_a={"adj_o": 118.7, "adj_d": 93.4, "adj_tempo": 69.2,
                      "three_pt_pct": 36.5, "record": "26-7", "conference": "Big 12", "kenpom_rank": 10},
            stats_b={"adj_o": 108.3, "adj_d": 98.7, "adj_tempo": 66.8,
                      "three_pt_pct": 35.2, "record": "27-6", "conference": "WAC", "kenpom_rank": 72},
        ),
    ]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
async def run_bracket(args):
    multi_model = args.multi_model
    agents = build_agents(multi_model=multi_model)
    agent_accuracy: dict[str, dict] = {}
    agent_memory: dict[str, list[str]] = {}
    groupthink_tracker: dict = {"unanimous": 0, "total": 0}

    # Pillar 3: Override budget if specified
    if args.budget is not None:
        cost_guard.max_budget = args.budget
        log.info(f"Budget set to ${args.budget:.2f}")

    # Pillar 1: Initialize tournament memory store
    agent_names = [a.name for a in agents]
    tournament_memory = TournamentMemoryStore(agent_names)
    live_mode = args.live_update is not None

    if live_mode:
        # Load existing memory with real results from prior rounds
        if tournament_memory.load():
            log.info(f"Live-update mode: loaded tournament memory")
            log.info(tournament_memory.summary())
        else:
            log.warning("Live-update mode but no tournament_memory.json found. Starting fresh.")

    # Validate Supabase configuration
    sb_client = supabase_client.get_client()
    if sb_client is None:
        log.warning("Supabase is not configured — game results will NOT be persisted to the database.")
    else:
        log.info("Supabase client initialized successfully.")

    # Load odds data if available
    odds_data = None
    if not args.dry_run:
        try:
            from odds_tracker import fetch_current_odds
            odds_data = fetch_current_odds()
        except Exception:
            pass

    # Load games
    if args.game:
        # Run a specific game by team name
        bracket = load_bracket()
        if bracket:
            all_games = generate_first_round_games(bracket)
            game_filter = args.game.lower()
            matched = [g for g in all_games
                       if g.team_a.lower() in game_filter or g.team_b.lower() in game_filter
                       or game_filter in g.team_a.lower() or game_filter in g.team_b.lower()]
            if not matched:
                log.error(f"No game found matching '{args.game}'. Available teams:")
                for g in all_games:
                    log.error(f"  #{g.seed_a} {g.team_a} vs #{g.seed_b} {g.team_b}")
                return
            all_rounds = {"R64": matched[:1]}
            log.info(f"Running specific game: #{matched[0].seed_a} {matched[0].team_a} vs #{matched[0].seed_b} {matched[0].team_b}")
        else:
            log.error("No bracket_loader.py found.")
            return
    elif args.single_game:
        bracket = load_bracket()
        if bracket:
            all_rounds = {"R64": generate_first_round_games(bracket)[:1]}
        else:
            all_rounds = {"R64": make_sample_games()[:1]}
    elif args.full_bracket:
        bracket = load_bracket()
        if bracket:
            all_rounds = {"R64": generate_first_round_games(bracket)}
            log.info(f"Loaded {len(all_rounds['R64'])} first-round games from bracket")
        else:
            log.warning("No bracket_loader.py found. Using sample games.")
            all_rounds = {"R64": make_sample_games()}
    else:
        bracket = load_bracket()
        if bracket:
            all_rounds = {"R64": generate_first_round_games(bracket)}
        else:
            all_rounds = {"R64": make_sample_games()}

    # Count total games across all potential rounds
    first_round_count = len(all_rounds["R64"])
    if args.full_bracket:
        # 32 + 16 + 8 + 4 + 2 + 1 = 63 total games (or scaled)
        total_games = first_round_count
        r = first_round_count
        while r > 1:
            r = r // 2
            total_games += r
    else:
        total_games = first_round_count

    # ~15 calls per game with 2-round debate (7 R1 + 7 R2 + 1 conductor)
    est_calls = int(total_games * 15)
    est_cost = est_calls * (500 * COST_PER_INPUT_TOKEN + 150 * COST_PER_OUTPUT_TOKEN)

    if not args.dry_run and not args.yes:
        print(f"\nThis will analyze ~{total_games} games with ~{est_calls} API calls (2-round debate).")
        print(f"Estimated cost: ${est_cost:.2f}")
        if multi_model:
            print(f"Multi-model mode: 3 agents on Claude, 4 on Gemini")
        confirm = input("Proceed? [y/n] ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            return

    log.info(f"Starting swarm: ~{total_games} games, dry_run={args.dry_run}, multi_model={multi_model}")
    start_time = time.monotonic()

    game_counter = 0
    all_debates: list[GameDebate] = []
    upset_watch: list[dict] = []
    conductor_override_count = 0
    full_agent_count = 0

    async with httpx.AsyncClient() as client:
        current_round = "R64"
        current_games = all_rounds.get("R64", [])

        while current_games:
            round_display = ROUND_DISPLAY.get(current_round, current_round)
            log.info(f"\n{'='*60}")
            log.info(f"  {round_display} — {len(current_games)} games")
            log.info(f"{'='*60}")

            round_debates = []
            for game in current_games:
                game_counter += 1
                debate = await analyze_game(
                    client, game, agents, agent_accuracy,
                    game_counter, total_games,
                    dry_run=args.dry_run,
                    groupthink_tracker=groupthink_tracker,
                    agent_memory=agent_memory,
                    odds_data=odds_data,
                    verbose=getattr(args, 'verbose', False),
                    tournament_memory=tournament_memory,
                    live_mode=live_mode,
                )
                round_debates.append(debate)
                all_debates.append(debate)

                # Track agent completion and conductor overrides
                valid = [v for v in debate.votes if not v.error and v.pick]
                if len(valid) == 7:
                    full_agent_count += 1
                if debate.conductor and valid:
                    pc = {}
                    for v in valid:
                        if v.pick:
                            pc[v.pick] = pc.get(v.pick, 0) + 1
                    if pc:
                        majority_t = max(pc, key=pc.get)
                        if debate.conductor.pick != majority_t:
                            conductor_override_count += 1

                # Track upsets
                if debate.upset_score and debate.upset_score.score >= 40:
                    upset_watch.append({
                        "game": f"#{game.seed_a} {game.team_a} vs #{game.seed_b} {game.team_b}",
                        "round": current_round,
                        "score": debate.upset_score.score,
                        "pick": debate.conductor.pick if debate.conductor else "?",
                    })

                print()

            # Advance to next round if running full bracket
            if args.full_bracket:
                next_games = advance_bracket(round_debates, current_round)

                # Run Monte Carlo simulation after R64 completes
                if current_round == "R64" and len(round_debates) >= 16:
                    try:
                        from monte_carlo import (
                            GameProb, TeamSim, simulate_bracket as mc_simulate,
                            print_monte_carlo_report, print_full_advancement_table,
                        )
                        mc_games = []
                        for d in round_debates:
                            if d.conductor:
                                g = d.game
                                t_a = TeamSim(g.team_a, g.seed_a, g.region, g.stats_a.get("kenpom_rank", 100))
                                t_b = TeamSim(g.team_b, g.seed_b, g.region, g.stats_b.get("kenpom_rank", 100))
                                mc_games.append(GameProb(
                                    game_id=g.id, team_a=t_a, team_b=t_b,
                                    team_a_win_prob=d.conductor.combined_prob,
                                    round_name="R64",
                                ))
                        if mc_games:
                            log.info(f"\nRunning Monte Carlo simulation ({len(mc_games)} R64 games)...")
                            mc_result = mc_simulate(mc_games, n_sims=10000)
                            print_monte_carlo_report(mc_result)
                            if getattr(args, 'verbose', False):
                                print_full_advancement_table(mc_result)

                            # Write to Supabase if available
                            try:
                                sb = supabase_client.get_client()
                                if sb:
                                    mc_records = []
                                    for team_name, probs in mc_result.advancement_probs.items():
                                        team = mc_result.team_info[team_name]
                                        mc_records.append({
                                            "team_name": team_name,
                                            "seed": team.seed,
                                            "region": team.region,
                                            "prob_r32": round(probs.get("R32", 0), 4),
                                            "prob_s16": round(probs.get("S16", 0), 4),
                                            "prob_e8": round(probs.get("E8", 0), 4),
                                            "prob_f4": round(probs.get("F4", 0), 4),
                                            "prob_championship": round(probs.get("NCG", 0), 4),
                                            "prob_winner": round(probs.get("Winner", 0), 4),
                                            "n_simulations": mc_result.n_simulations,
                                        })
                                    # We'd write to mm_monte_carlo table here if it exists
                                    log.info(f"  Monte Carlo: {len(mc_records)} team probabilities computed")
                            except Exception as e:
                                log.warning(f"  Monte Carlo Supabase write failed: {e}")
                    except Exception as e:
                        log.warning(f"Monte Carlo simulation failed: {e}")

                # Market Inefficiency Report after R64
                if odds_data and round_debates:
                    try:
                        from market_analyzer import analyze_bracket, print_market_report
                        market_report = analyze_bracket(round_debates, odds_data)
                        print_market_report(market_report)
                    except Exception as e:
                        log.warning(f"Market report failed: {e}")

                if next_games:
                    current_round_idx = ROUND_NAMES.index(current_round)
                    current_round = ROUND_NAMES[current_round_idx + 1]
                    current_games = next_games
                    log.info(f"\nAdvancing {len(next_games)} winners to {ROUND_DISPLAY.get(current_round, current_round)}")
                else:
                    current_games = []
            else:
                current_games = []

    elapsed = time.monotonic() - start_time

    # Pillar 1: Save tournament memory for future live-update runs
    tournament_memory.save()

    # Final summary
    print("=" * 60)
    print("SWARM COMPLETE")
    print("=" * 60)
    print(f"Games analyzed: {game_counter}")
    print(f"Total time: {elapsed:.1f}s ({elapsed/max(game_counter,1):.1f}s per game)")
    print(f"{cost_tracker.summary()}")
    print(f"{cost_guard.summary()}")  # Pillar 3: Budget status

    gt = groupthink_tracker
    if gt["total"] > 0:
        rate = gt["unanimous"] / gt["total"]
        print(f"Groupthink rate: {rate:.0%} ({gt['unanimous']}/{gt['total']} unanimous)")
    print(f"Full agent responses (7/7): {full_agent_count}/{game_counter}")
    print(f"Conductor overrides of majority: {conductor_override_count}/{game_counter}")

    if upset_watch:
        print(f"\nUPSET WATCH ({len(upset_watch)} flagged):")
        for u in sorted(upset_watch, key=lambda x: x["score"], reverse=True):
            print(f"  [{u['score']}/100] {u['game']} ({u['round']}) — Pick: {u['pick']}")

    # Calibration report for R64
    r64_debates = [d for d in all_debates if d.game.round_name == "R64" and d.conductor]
    if len(r64_debates) >= 16:
        print(f"\n{'='*60}")
        print("R64 CALIBRATION REPORT")
        print(f"{'='*60}")
        expected = {
            (1,16): (0, 4, 0.007), (2,15): (0, 4, 0.062), (3,14): (0, 4, 0.148),
            (4,13): (1, 4, 0.209), (5,12): (1, 4, 0.358), (6,11): (1, 4, 0.375),
            (7,10): (1, 4, 0.392), (8,9): (2, 4, 0.486),
        }
        total_upsets = 0
        for seeds_key in sorted(expected.keys()):
            exp_upsets, total, rate = expected[seeds_key]
            actual_upsets = 0
            matchups = [d for d in r64_debates
                        if tuple(sorted([d.game.seed_a, d.game.seed_b])) == seeds_key]
            for d in matchups:
                fav_seed = min(d.game.seed_a, d.game.seed_b)
                fav_name = d.game.team_a if d.game.seed_a == fav_seed else d.game.team_b
                if d.conductor.pick != fav_name:
                    actual_upsets += 1
            total_upsets += actual_upsets
            status = "OK" if actual_upsets >= exp_upsets else "LOW"
            print(f"  {seeds_key[0]}v{seeds_key[1]}: {actual_upsets}/{len(matchups)} upsets "
                  f"(expected ~{rate:.0%} = {exp_upsets}/{total}) [{status}]")
        print(f"\n  TOTAL UPSETS: {total_upsets}/32 (expected 7-10)")
        if total_upsets < 5:
            print("  WARNING: Too few upsets — system is miscalibrated toward chalk")
        elif total_upsets > 14:
            print("  WARNING: Too many upsets — system is miscalibrated toward chaos")

    # Champion announcement for full bracket
    if args.full_bracket and all_debates:
        last = all_debates[-1]
        if last.conductor and last.game.round_name == "NCG":
            print(f"\n{'*'*60}")
            print(f"  PREDICTED CHAMPION: {last.conductor.pick}")
            print(f"  Confidence: {last.conductor.confidence}%")
            print(f"{'*'*60}")

    # Pillar 5B: Agent Performance Summary
    agent_perf = perf_tracker.get_agent_summary()
    if agent_perf:
        print(f"\n{'='*60}")
        print("AGENT PERFORMANCE METRICS")
        print(f"{'='*60}")
        for name, stats in sorted(agent_perf.items()):
            acc_str = f"{stats['accuracy']:.0%}" if stats['accuracy'] is not None else "N/A"
            print(
                f"  {name}: {stats['total_games']} games | "
                f"Accuracy: {acc_str} | "
                f"Avg response: {stats['avg_response_ms']:.0f}ms | "
                f"Position changes: {stats['position_changes']} | "
                f"Cost: ${stats['total_cost']:.3f}"
            )

    # Pillar 1: Tournament Memory Summary
    if tournament_memory.has_real_data():
        print(f"\n{tournament_memory.summary()}")

    print(f"\nDebate transcripts: {Path(__file__).parent / 'debates'}/")
    print(f"Logs: {LOG_DIR}/")

    # Save game results for live_tracker
    results_file = Path(__file__).parent / "game_results.json"
    game_results = []
    for d in all_debates:
        if d.conductor:
            game_results.append({
                "team_a": d.game.team_a,
                "team_b": d.game.team_b,
                "pick": d.conductor.pick,
                "confidence": d.conductor.confidence,
                "round": d.game.round_name,
                "region": d.game.region,
            })
    with open(results_file, "w") as f:
        json.dump(game_results, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="March Madness Agent Swarm Engine v2")
    parser.add_argument("--dry-run", action="store_true", help="Use mock responses (no API calls)")
    parser.add_argument("--single-game", action="store_true", help="Run only one sample game")
    parser.add_argument("--full-bracket", action="store_true",
                        help="Run all rounds (R64 through Championship) with bracket progression")
    parser.add_argument("--multi-model", action="store_true",
                        help="Split agents across Claude and Gemini for model diversity")
    parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")
    parser.add_argument("--verbose", action="store_true", help="Print detailed agent responses")
    parser.add_argument("--game", type=str, default=None,
                        help="Run a specific game by team name (e.g. 'UCLA vs UCF')")
    parser.add_argument("--live-update", type=str, default=None, metavar="ROUND",
                        help="Live-update mode: re-run from ROUND (R32, S16, etc.) using "
                        "real results from prior rounds. Agents get tournament memory.")
    parser.add_argument("--budget", type=float, default=None,
                        help="Override API budget limit (default: $100)")
    args = parser.parse_args()

    asyncio.run(run_bracket(args))


if __name__ == "__main__":
    main()
