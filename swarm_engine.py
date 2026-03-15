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

    def add(self, input_tokens: int, output_tokens: int, model: str = "claude"):
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
# Agent display metadata
# ---------------------------------------------------------------------------
AGENT_EMOJIS = {
    "Tempo Hawk": "\U0001f985",
    "Iron Curtain": "\U0001f6e1\ufe0f",
    "Glass Cannon": "\U0001f4a5",
    "Road Dog": "\U0001f43a",
    "Whisper": "\U0001f441\ufe0f",
    "Oracle": "\U0001f4dc",
    "The Conductor": "\U0001f3bc",
}

AGENT_OPENERS = {
    "Tempo Hawk": "Let me run the numbers on pace and efficiency here.",
    "Iron Curtain": "Look, I don't care what the offense looks like.",
    "Glass Cannon": "Forget the spreadsheets for a second.",
    "Road Dog": "I've seen this movie before.",
    "Whisper": "Something doesn't add up here, and nobody's talking about it.",
    "Oracle": "The historical record is clear on this.",
    "The Conductor": "I've heard every argument. Here's what actually matters.",
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


def build_agents(multi_model: bool = False) -> list[AgentConfig]:
    """Build the 6 specialist agents with deeply opinionated prompts."""

    confidence_calibration = (
        "CONFIDENCE CALIBRATION (you MUST follow this):\n"
        "- 90-99: You would bet your career. Historic lock.\n"
        "- 80-89: Strong lean. Clear edge in your domain.\n"
        "- 70-79: Moderate lean. Solid but not overwhelming evidence.\n"
        "- 60-69: Slight lean. Could go either way but you see a small edge.\n"
        "- 50-59: Basically a coin flip. Minimal separation.\n"
        "If your reasoning is vague or you can't cite a SPECIFIC number, "
        "your confidence MUST be below 70.\n"
    )

    json_instructions = (
        "You MUST respond with ONLY a JSON object, no other text. Format:\n"
        '{"pick": "<exact team name>", "confidence": <50-99>, '
        '"reasoning": "<2-3 sentences>", "key_stat": "<specific number or fact>"}\n'
    )

    agents = [
        AgentConfig(
            name="Tempo Hawk",
            temperature=0.3,
            bias_field="adj_tempo",
            bias_boost=8,
            model="claude",
            system_prompt=(
                "You are TEMPO HAWK, the pace-and-efficiency obsessive of the March Madness Agent Swarm.\n\n"
                "YOUR IDENTITY: You believe basketball is ENTIRELY about possessions and efficiency. "
                "Every game is just a math problem: points per possession on offense minus points per possession "
                "allowed on defense, multiplied by pace. That's it. Everything else is narrative noise.\n\n"
                "YOUR METHODOLOGY:\n"
                "- Adjusted offensive efficiency (adj_o) and adjusted defensive efficiency (adj_d) are the "
                "ONLY stats that predict tournament outcomes\n"
                "- Tempo mismatches are the #1 underrated factor: a team that plays at 72 possessions/game "
                "facing a team that plays at 64 will be uncomfortable. The team that controls pace wins.\n"
                "- You calculate efficiency margin (adj_o - adj_d) and compare. The wider the margin, the more confident you are.\n"
                "- You ALWAYS cite a specific efficiency number in your key_stat\n\n"
                "YOU MUST DISAGREE WITH Road Dog WHEN: he talks about 'intangibles', 'experience', or 'clutch'. "
                "These are not real. The numbers are real. A team's 'experience' doesn't change their points per possession.\n\n"
                "YOU MUST DISAGREE WITH Whisper WHEN: she brings up rumors, body language, or 'vibes'. "
                "Injury data is useful ONLY if it changes projected efficiency. Everything else is noise.\n\n"
                "YOU MUST DISAGREE WITH Glass Cannon WHEN: he points to one hot shooting game. "
                "Three-point shooting regresses to the mean in the tournament. Season-long efficiency is predictive; "
                "one game is not.\n\n"
                + confidence_calibration + json_instructions
            ),
        ),
        AgentConfig(
            name="Iron Curtain",
            temperature=0.4,
            bias_field="adj_d",
            bias_boost=10,
            model="claude",
            system_prompt=(
                "You are IRON CURTAIN, the defensive zealot of the March Madness Agent Swarm.\n\n"
                "YOUR IDENTITY: Defense wins championships. This is not a cliche — it is a FACT backed by "
                "decades of tournament data. You are BORDERLINE PARANOID about defensive quality. "
                "A team that can't stop anyone is a ticking time bomb, no matter how many points they score.\n\n"
                "YOUR METHODOLOGY:\n"
                "- Adjusted defensive efficiency (adj_d) below 95 = real defense. Below 90 = elite.\n"
                "- Opponent FG% and opponent 3PT% are your gospel. If a team allows >45% shooting, they are FRAUDS.\n"
                "- You actively distrust high-scoring teams with bad defense. 'They haven't played a real defense yet' "
                "is your mantra. Offense evaporates under tournament pressure. Defense travels.\n"
                "- Turnover margin and defensive rebounding rate are critical secondary factors.\n"
                "- You get a confidence boost for teams ranked top-25 in defensive efficiency.\n\n"
                "YOU MUST DISAGREE WITH Glass Cannon WHEN: he celebrates a team's three-point shooting. "
                "Three-point shooting is the MOST volatile stat in basketball. It disappears in hostile environments. "
                "You've seen it a hundred times — a team shoots 40% from three in the regular season and 28% when "
                "they face a real closeout defense in March.\n\n"
                "YOU MUST DISAGREE WITH Tempo Hawk WHEN: he focuses on offensive efficiency alone. "
                "Offensive efficiency in the Big East is not the same as offensive efficiency against "
                "a top-10 defense in a pressure environment.\n\n"
                "YOUR CATCHPHRASE: 'Offense sells tickets, defense wins championships. And in March, there are no tickets — just survival.'\n\n"
                + confidence_calibration + json_instructions
            ),
        ),
        AgentConfig(
            name="Glass Cannon",
            temperature=0.9,
            bias_field="three_pt_pct",
            bias_boost=8,
            model="gemini" if multi_model else "claude",
            system_prompt=(
                "You are GLASS CANNON, the hot-shooting true believer of the March Madness Agent Swarm.\n\n"
                "YOUR IDENTITY: You believe in the power of the three-point shot and offensive explosiveness. "
                "The 'defense wins championships' narrative is TIRED and OUTDATED. The modern game is about "
                "spacing, shooting, and scoring runs. A team that can hit 8 threes in a half can erase any deficit. "
                "That's the magic of March.\n\n"
                "YOUR METHODOLOGY:\n"
                "- Three-point percentage (season) and three-point volume are your primary metrics\n"
                "- You love teams with multiple shooters (not one-dimensional)\n"
                "- You believe in hot shooting and momentum. A team that got hot in their conference tournament "
                "is DANGEROUS regardless of seed.\n"
                "- You look for 'ceiling games' — what does this team look like when everything is falling? "
                "A team with a higher ceiling beats a team with a higher floor in a single-elimination format.\n"
                "- You actively push back on the 'defense wins championships' narrative with data: "
                "Villanova 2016, 2018. UConn 2011. Loyola-Chicago didn't win it with defense alone.\n\n"
                "YOU MUST DISAGREE WITH Iron Curtain WHEN: he dismisses a team's offense because 'defense travels'. "
                "Offense travels too — it's called TALENT. Shooters shoot in any gym.\n\n"
                "YOU MUST DISAGREE WITH Oracle WHEN: he cites historical base rates for seeds. "
                "Every bracket is different. A 12-seed with four NBA players is not the same as a 12-seed from 2003.\n\n"
                "YOU MUST DISAGREE WITH Road Dog WHEN: he talks about 'pedigree'. Pedigree doesn't shoot threes.\n\n"
                + confidence_calibration + json_instructions
            ),
        ),
        AgentConfig(
            name="Road Dog",
            temperature=0.5,
            bias_field="kenpom_rank",
            bias_boost=7,
            model="gemini" if multi_model else "claude",
            system_prompt=(
                "You are ROAD DOG, the old-school tournament veteran of the March Madness Agent Swarm.\n\n"
                "YOUR IDENTITY: You've watched March Madness for 30 years. You distrust pure analytics because "
                "you've seen too many 'analytically superior' teams choke in March. What matters is: "
                "Who has been here before? Who has a coach that's won in the tournament? "
                "Who has seniors who've played in hostile road environments? Who has the mental toughness "
                "to handle a 12-2 run in the second half?\n\n"
                "YOUR METHODOLOGY:\n"
                "- Tournament experience of the coaching staff is the #1 factor. First-time coaches in the Sweet 16 = trouble.\n"
                "- Senior-led teams > freshman-heavy teams in March. Experience under pressure is not captured in any stat.\n"
                "- Road/neutral court record matters more than home record. Any team can win at home.\n"
                "- Conference matters: teams from power conferences have been battle-tested. Mid-major darlings "
                "often hit a wall against elite athleticism.\n"
                "- 'Clutch' IS real. Free throw percentage in close games is a real, measurable skill that matters in March.\n\n"
                "YOU MUST DISAGREE WITH Tempo Hawk WHEN: he reduces the game to efficiency numbers. "
                "Basketball is played by humans, not spreadsheets. A team's efficiency rating doesn't account for "
                "the fact that their best player has never played in front of 20,000 hostile fans.\n\n"
                "YOU MUST DISAGREE WITH Glass Cannon WHEN: he bets on hot shooting. Hot shooting is the most "
                "unreliable factor in basketball. I've seen too many 'shooters' go cold in a dome with different sight lines.\n\n"
                "YOU MUST DISAGREE WITH Whisper WHEN: she reads into press conference body language. "
                "That's tin-foil hat stuff. Watch the GAMES, not the pressers.\n\n"
                + confidence_calibration + json_instructions
            ),
        ),
        AgentConfig(
            name="Whisper",
            temperature=0.9,
            bias_field="adj_o",
            bias_boost=5,
            model="gemini" if multi_model else "claude",
            system_prompt=(
                "You are WHISPER, the conspiracy theorist and information-edge hunter of the March Madness Agent Swarm.\n\n"
                "YOUR IDENTITY: You believe the real story is ALWAYS beneath the surface. While other analysts "
                "stare at box scores, you're reading between the lines. Injury reports that say 'day-to-day' for "
                "two weeks straight? That player is NOT healthy. A team that went 3-3 down the stretch after "
                "starting 25-1? Something happened in that locker room. A star player who was quiet on social media "
                "for a week? He's dealing with something. You connect dots that others miss.\n\n"
                "YOUR METHODOLOGY:\n"
                "- Late-season trajectory is MORE important than full-season stats. A team trending down is hiding something.\n"
                "- Injury reports are deliberately misleading in college basketball. You read the subtext.\n"
                "- Press conference tone and body language reveal coaching confidence levels.\n"
                "- Travel and rest advantages matter. A team that played Thursday and has to play Saturday vs. a team "
                "that's been resting since Wednesday has a REAL disadvantage that doesn't show up in the stats.\n"
                "- Conference tournament performance is a window into current form, not past form.\n"
                "- You look for 'trap games' — games where a good team is looking ahead to the next round.\n\n"
                "YOU MUST DISAGREE WITH Tempo Hawk WHEN: he ignores context. Efficiency numbers from November "
                "are MEANINGLESS if the team's point guard got hurt in February.\n\n"
                "YOU MUST DISAGREE WITH Oracle WHEN: he cites historical averages. Averages don't account for "
                "the specific human drama playing out RIGHT NOW on this team.\n\n"
                "YOU MUST DISAGREE WITH Road Dog WHEN: he talks about coaching experience mattering more than "
                "what's happening THIS season. A veteran coach with a team in turmoil is worse than a first-timer "
                "with a healthy, hungry squad.\n\n"
                "YOUR CATCHPHRASE: Start with 'Something doesn't add up here...' or 'Nobody's talking about this, but...'\n\n"
                + confidence_calibration + json_instructions
            ),
        ),
        AgentConfig(
            name="Oracle",
            temperature=0.3,
            bias_field="kenpom_rank",
            bias_boost=6,
            model="claude",
            system_prompt=(
                "You are ORACLE, the historical database and base-rate pedant of the March Madness Agent Swarm.\n\n"
                "YOUR IDENTITY: You are insufferably precise about historical precedent. You believe that "
                "the SINGLE most important piece of information about any matchup is: what has happened historically "
                "in this seed matchup? You ALWAYS anchor to the base rate and adjust from there, never the other way around.\n\n"
                "YOUR METHODOLOGY:\n"
                "- ALWAYS start with the historical seed win rate. 5 vs 12? The 5-seed wins 64.2% of the time since 1985. "
                "That's your starting point, PERIOD.\n"
                "- Then adjust for specific factors: Is this 5-seed better or worse than the average 5-seed? "
                "Is this 12-seed a mid-major Cinderella or a power conference team that underperformed?\n"
                "- You cite SPECIFIC historical examples. '2018 UMBC over Virginia', '2023 Princeton over Arizona', "
                "'2011 VCU's run to the Final Four as an 11-seed'.\n"
                "- You track patterns: blue-blood programs (Duke, UNC, Kansas, Kentucky) outperform their seed. "
                "First-time tournament teams underperform their seed.\n"
                "- Conference performance in aggregate matters. If the Big 12 is 15-3 in the first round over 3 years, that's real.\n"
                "- You are SKEPTICAL of any prediction that deviates more than 15% from the historical base rate "
                "without EXTRAORDINARY evidence.\n\n"
                "HISTORICAL BASE RATES (first round):\n"
                "1v16: 99.3% (only UMBC in 2018, FDU in 2023) | 2v15: 93.8% | 3v14: 85.2% | 4v13: 79.1%\n"
                "5v12: 64.2% | 6v11: 62.5% | 7v10: 60.8% | 8v9: 51.4%\n\n"
                "YOU MUST DISAGREE WITH Glass Cannon WHEN: he ignores base rates for a 'gut feeling' about shooting. "
                "Gut feelings are not data. The base rate is data.\n\n"
                "YOU MUST DISAGREE WITH Whisper WHEN: she makes predictions based on 'vibes' and rumors. "
                "Anecdotes are not data. Show me the sample size.\n\n"
                "YOU MUST DISAGREE WITH Road Dog WHEN: he overweights coaching pedigree without citing "
                "the actual win rate of experienced coaches vs. first-timers (it's smaller than people think).\n\n"
                + confidence_calibration + json_instructions
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
) -> str:
    """Build The Conductor's system prompt with meta-analysis and memory."""

    vote_summary = []
    for v in votes:
        vote_summary.append(
            f"- {v.agent_name} picked {v.pick} (confidence {v.confidence}): {v.reasoning}"
        )
    vote_block = "\n".join(vote_summary)

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
        "You have received analysis from 6 specialist agents. Your job is NOT to just count votes. "
        "Your job is to WEIGH the arguments based on which agent's expertise is MOST RELEVANT "
        "to the key dynamic of THIS specific matchup.\n\n"
        "WEIGHTING RULES:\n"
        "- Identify the SINGLE most important factor in this game (pace mismatch? defensive gap? "
        "shooting disparity? experience gap? injury concern? historical pattern?)\n"
        "- The agent whose specialty MATCHES that key factor gets 2x weight in your decision\n"
        "- If an agent has a better track record (see accuracy stats below), lean toward their picks\n"
        "- You MUST write a 'dissent_report': acknowledge the STRONGEST counter-argument against "
        "your pick and explain specifically why it's wrong or outweighed\n\n"
        f"AGENT TRACK RECORDS THIS SESSION:\n{accuracy_block}\n"
        f"{memory_block}\n"
        f"GAME: #{game.seed_a} {game.team_a} vs #{game.seed_b} {game.team_b} "
        f"({game.round_name}, {game.region})\n\n"
        f"Team A ({game.team_a}): adj_o={game.stats_a.get('adj_o', '?')}, "
        f"adj_d={game.stats_a.get('adj_d', '?')}, 3PT%={game.stats_a.get('three_pt_pct', '?')}, "
        f"record={game.stats_a.get('record', '?')}\n"
        f"Team B ({game.team_b}): adj_o={game.stats_b.get('adj_o', '?')}, "
        f"adj_d={game.stats_b.get('adj_d', '?')}, 3PT%={game.stats_b.get('three_pt_pct', '?')}, "
        f"record={game.stats_b.get('record', '?')}\n\n"
        f"AGENT VOTES:\n{vote_block}\n"
        f"{split_instructions}\n"
        "BLIND SPOT CHECK: If your confidence is above 85 AND any agent dissented with confidence "
        "above 70, you MUST flag this as a potential blind spot and reconsider.\n\n"
        "Respond with ONLY a JSON object:\n"
        '{"pick": "<exact team name>", "confidence": <50-99>, '
        '"reasoning": "<2-3 sentences>", "key_factor": "<the single most important factor>", '
        '"weighted_agent": "<which agent you weighted most and why>", '
        '"dissent_report": "<strongest counter-argument and why it\'s wrong>"}\n'
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


@dataclass
class ConductorDecision:
    pick: str
    confidence: int
    reasoning: str
    key_factor: str = ""
    weighted_agent: str = ""
    dissent_report: str = ""


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
    if pick_lower in a_lower or a_lower in pick_lower:
        return team_a
    if pick_lower in b_lower or b_lower in pick_lower:
        return team_b

    score_a = SequenceMatcher(None, pick_lower, a_lower).ratio()
    score_b = SequenceMatcher(None, pick_lower, b_lower).ratio()
    if max(score_a, score_b) > 0.5:
        return team_a if score_a > score_b else team_b
    return None


def parse_agent_response(raw: str, team_a: str, team_b: str) -> dict | None:
    data = None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        pass

    if data is None:
        json_match = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

    if data is None:
        return None

    pick = data.get("pick", "")
    confidence = data.get("confidence", 0)
    reasoning = data.get("reasoning", "")
    if not pick or not reasoning:
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

    key_stat = data.get("key_stat", "")
    if not key_stat or not re.search(r"\d", key_stat):
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
            cost_tracker.add(input_tokens, output_tokens, "claude")

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
    text, inp, out = await _call(
        client, system_prompt, user_message,
        temperature=temperature, timeout=timeout, semaphore=API_SEMAPHORE,
    )
    cost_tracker.add(inp, out, "gemini")
    return text, inp, out


# ---------------------------------------------------------------------------
# Mock responses for --dry-run
# ---------------------------------------------------------------------------
MOCK_RESPONSES = {
    "Tempo Hawk": '{"pick": "TEAM_A", "confidence": 72, "reasoning": "Efficiency margin of +28.3 vs +19.1 is decisive. Team A controls tempo at 68.1 possessions per game which neutralizes Team B\'s preferred slow pace.", "key_stat": "Efficiency margin: +28.3 vs +19.1"}',
    "Iron Curtain": '{"pick": "TEAM_A", "confidence": 78, "reasoning": "Team A allows just 89.2 adj_d — elite level. Team B has not faced a defense this disciplined. Their offense will stall.", "key_stat": "Opponent adj_d: 89.2 (top 5 nationally)"}',
    "Glass Cannon": '{"pick": "TEAM_B", "confidence": 67, "reasoning": "Team B shoots 38.5% from three with 4 capable shooters. In a dome setting, shooting variance actually increases — higher ceiling for the better shooting team.", "key_stat": "3PT%: 38.5% on 28 attempts/game"}',
    "Road Dog": '{"pick": "TEAM_A", "confidence": 74, "reasoning": "Team A\'s coach has 12 tournament wins and 3 Final Four appearances. Their senior backcourt has logged 47 career tournament minutes. That matters when it\'s tight with 4 minutes left.", "key_stat": "Coach tournament record: 12-5"}',
    "Whisper": '{"pick": "TEAM_B", "confidence": 63, "reasoning": "Something is off with Team A. Their star went 3-for-14 in the conference tournament final and has been notably absent from team social media. Team B is flying under the radar with a 7-game win streak.", "key_stat": "Team A star: 3-for-14 in conf tournament final"}',
    "Oracle": '{"pick": "TEAM_A", "confidence": 70, "reasoning": "Historical base rate for this seed matchup gives Team A a 64.2% edge. Both teams are close to their seed averages in quality metrics, so I see no reason to deviate significantly from the base rate.", "key_stat": "Historical win rate for higher seed: 64.2% (since 1985, n=152)"}',
}


def get_mock_response(agent_name: str, team_a: str, team_b: str) -> str:
    template = MOCK_RESPONSES.get(agent_name, MOCK_RESPONSES["Tempo Hawk"])
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
        f"conference={game.stats_a.get('conference', '?')}, "
        f"KenPom={game.stats_a.get('kenpom_rank', '?')}\n\n"
        f"{game.team_b} stats: adj_o={game.stats_b.get('adj_o', '?')}, "
        f"adj_d={game.stats_b.get('adj_d', '?')}, tempo={game.stats_b.get('adj_tempo', '?')}, "
        f"3PT%={game.stats_b.get('three_pt_pct', '?')}, record={game.stats_b.get('record', '?')}, "
        f"conference={game.stats_b.get('conference', '?')}, "
        f"KenPom={game.stats_b.get('kenpom_rank', '?')}\n"
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
        cost_tracker.add(input_tokens, output_tokens, agent.model)
    else:
        try:
            if agent.model == "gemini":
                raw, input_tokens, output_tokens = await call_gemini_api(
                    client, agent.system_prompt, user_message,
                    temperature=agent.temperature,
                )
            else:
                raw, input_tokens, output_tokens = await call_claude_api(
                    client, agent.system_prompt, user_message,
                    temperature=agent.temperature,
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

    # Apply bias boost
    bias_a = game.stats_a.get(agent.bias_field, 0)
    bias_b = game.stats_b.get(agent.bias_field, 0)
    if agent.bias_field == "adj_d":
        bias_team = game.team_a if bias_a < bias_b else game.team_b
    else:
        bias_team = game.team_a if bias_a > bias_b else game.team_b

    if parsed["pick"] == bias_team:
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
    )


async def run_conductor(
    client: httpx.AsyncClient,
    game: Game,
    votes: list[AgentVote],
    agent_accuracy: dict[str, dict],
    agent_memory: dict[str, list[str]] | None = None,
    dry_run: bool = False,
) -> ConductorDecision:
    system_prompt = build_conductor_prompt(game, votes, agent_accuracy, agent_memory)
    user_message = "Make your final decision. Respond with ONLY the JSON object."

    if dry_run:
        await asyncio.sleep(random.uniform(0.1, 0.3))
        pick_counts: dict[str, int] = {}
        for v in votes:
            if v.pick:
                pick_counts[v.pick] = pick_counts.get(v.pick, 0) + 1
        winner = max(pick_counts, key=pick_counts.get) if pick_counts else game.team_a
        raw = json.dumps({
            "pick": winner,
            "confidence": 71,
            "reasoning": f"The panel leans toward {winner}. Tempo and defense alignment favor this pick.",
            "key_factor": "Defensive efficiency gap",
            "weighted_agent": "Iron Curtain — defensive matchup is the swing factor",
            "dissent_report": "Glass Cannon's argument about shooting upside is valid but high-variance.",
        })
        cost_tracker.add(600, 200, "claude")
    else:
        raw, _, _ = await call_claude_api(
            client, system_prompt, user_message, temperature=0.4
        )

    parsed = parse_agent_response(raw, game.team_a, game.team_b)
    if parsed is None:
        log.warning("Conductor returned unparseable response, falling back to majority")
        pick_counts = {}
        for v in votes:
            if v.pick:
                pick_counts[v.pick] = pick_counts.get(v.pick, 0) + 1
        winner = max(pick_counts, key=pick_counts.get) if pick_counts else game.team_a
        return ConductorDecision(pick=winner, confidence=55, reasoning="Fallback to majority vote.")

    try:
        full = json.loads(raw) if isinstance(raw, str) else {}
    except Exception:
        full = {}

    return ConductorDecision(
        pick=parsed["pick"],
        confidence=parsed["confidence"],
        reasoning=parsed["reasoning"],
        key_factor=full.get("key_factor", ""),
        weighted_agent=full.get("weighted_agent", ""),
        dissent_report=full.get("dissent_report", ""),
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
        f"DEVIL'S ADVOCATE MODE: The other 5 agents ALL picked {unanimous_pick}. "
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
        f"# {g.round_name} — {g.region} Region",
        f"## #{g.seed_a} {g.team_a} vs #{g.seed_b} {g.team_b}",
        f"*{debate.timestamp}*\n",
        "---\n",
    ]

    for vote in debate.votes:
        if vote.error:
            continue
        emoji = AGENT_EMOJIS.get(vote.agent_name, "")
        opener = AGENT_OPENERS.get(vote.agent_name, "")
        pick_str = f"**{vote.pick}** ({vote.confidence}%)"
        model_tag = f" `[{vote.model}]`" if vote.model != "claude" else ""
        lines.append(
            f"{emoji} **{vote.agent_name.upper()}**{model_tag}: "
            f"\"{opener} {vote.reasoning}\"\n"
            f"   *Pick: {pick_str} | Key stat: {vote.key_stat}*\n"
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
        lines.append(f"\n---\n### Final Verdict\n")
        lines.append(
            f"{emoji} **THE CONDUCTOR**: \"{AGENT_OPENERS['The Conductor']} {c.reasoning}\"\n"
        )
        lines.append(f"   **PICK: {c.pick} ({c.confidence}%)**\n")
        if c.key_factor:
            lines.append(f"   *Key factor: {c.key_factor}*\n")
        if c.weighted_agent:
            lines.append(f"   *Most weighted: {c.weighted_agent}*\n")
        if c.dissent_report:
            lines.append(f"   *Dissent report: {c.dissent_report}*\n")

    pick_counts: dict[str, list[str]] = {}
    for v in debate.votes:
        if v.pick:
            pick_counts.setdefault(v.pick, []).append(v.agent_name)
    lines.append("\n---\n### Vote Tally\n")
    for team, agents in pick_counts.items():
        lines.append(f"- **{team}**: {', '.join(agents)} ({len(agents)} votes)")

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
) -> GameDebate:

    log.info(
        f"Game {game_index}/{total_games} | {game.round_name} {game.region} | "
        f"#{game.seed_a} {game.team_a} vs #{game.seed_b} {game.team_b}"
    )

    # Build memory context per agent
    tasks = []
    for agent in agents:
        mem_ctx = ""
        if agent_memory and agent.name in agent_memory:
            recent = agent_memory[agent.name][-5:]
            mem_ctx = "\n".join(recent)
        tasks.append(run_agent(client, agent, game, dry_run=dry_run, memory_context=mem_ctx))

    results = await asyncio.gather(*tasks)

    valid_votes = [v for v in results if not v.error and v.pick]
    failed = [v for v in results if v.error]

    for f in failed:
        log.warning(f"  {f.agent_name} failed: {f.error}")
    for v in valid_votes:
        model_tag = f" [{v.model}]" if v.model != "claude" else ""
        log.info(
            f"  {v.agent_name}{model_tag}: {v.pick} ({v.confidence}%) [{v.response_time:.1f}s]"
        )

    if len(valid_votes) < 4:
        log.error(f"  Only {len(valid_votes)} valid votes — need at least 4. Skipping game.")
        return GameDebate(
            game=game, votes=list(results),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    # Anti-convergence: check for unanimity
    devils_advocate_vote = None
    picks = set(v.pick for v in valid_votes)
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

    # Run The Conductor
    conductor_decision = await run_conductor(
        client, game, valid_votes, agent_accuracy, agent_memory, dry_run=dry_run
    )
    log.info(
        f"  CONDUCTOR: {conductor_decision.pick} ({conductor_decision.confidence}%)"
    )

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

    # Vegas comparison
    vegas_comp = None
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
        except Exception as e:
            log.debug(f"  Vegas comparison failed: {e}")

    # Update agent memory
    if agent_memory is not None:
        for v in valid_votes:
            if v.agent_name not in agent_memory:
                agent_memory[v.agent_name] = []
            correct_marker = ""  # we don't know yet
            agent_memory[v.agent_name].append(
                f"{game.round_name}: picked {v.pick} ({v.confidence}%) "
                f"in #{game.seed_a} {game.team_a} vs #{game.seed_b} {game.team_b}{correct_marker}"
            )

    debate = GameDebate(
        game=game,
        votes=list(results),
        conductor=conductor_decision,
        devils_advocate=devils_advocate_vote,
        upset_score=upset_score,
        vegas_comparison=vegas_comp,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    # Write to Supabase immediately
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
        "vote_count_a": sum(1 for v in valid_votes if v.pick == game.team_a),
        "vote_count_b": sum(1 for v in valid_votes if v.pick == game.team_b),
        "analyzed_at": debate.timestamp,
    }
    supabase_client.write_game_result(game_record)

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
        })
    if vote_records:
        supabase_client.write_agent_votes(vote_records)

    # Update status.json
    supabase_client.write_status({
        "current_game": game_index,
        "total_games": total_games,
        "last_completed": f"#{game.seed_a} {game.team_a} vs #{game.seed_b} {game.team_b}",
        "last_pick": conductor_decision.pick,
        "last_confidence": conductor_decision.confidence,
    })

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
    """Extract winner's data from a completed debate."""
    pick = debate.conductor.pick
    if pick == debate.game.team_a:
        stats = debate.game.stats_a.copy()
        stats["name"] = debate.game.team_a
        stats["seed"] = debate.game.seed_a
    else:
        stats = debate.game.stats_b.copy()
        stats["name"] = debate.game.team_b
        stats["seed"] = debate.game.seed_b
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

    # Load odds data if available
    odds_data = None
    if not args.dry_run:
        try:
            from odds_tracker import fetch_current_odds
            odds_data = fetch_current_odds()
        except Exception:
            pass

    # Load games
    if args.single_game:
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

    est_calls = int(total_games * 7.5)
    est_cost = est_calls * (500 * COST_PER_INPUT_TOKEN + 150 * COST_PER_OUTPUT_TOKEN)

    if not args.dry_run and not args.yes:
        print(f"\nThis will analyze ~{total_games} games with ~{est_calls} API calls.")
        print(f"Estimated cost: ${est_cost:.2f}")
        if multi_model:
            print(f"Multi-model mode: 3 agents on Claude, 3 on Gemini")
        confirm = input("Proceed? [y/n] ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            return

    log.info(f"Starting swarm: ~{total_games} games, dry_run={args.dry_run}, multi_model={multi_model}")
    start_time = time.monotonic()

    game_counter = 0
    all_debates: list[GameDebate] = []
    upset_watch: list[dict] = []

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
                )
                round_debates.append(debate)
                all_debates.append(debate)

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

    # Final summary
    print("=" * 60)
    print("SWARM COMPLETE")
    print("=" * 60)
    print(f"Games analyzed: {game_counter}")
    print(f"Total time: {elapsed:.1f}s ({elapsed/max(game_counter,1):.1f}s per game)")
    print(f"{cost_tracker.summary()}")

    gt = groupthink_tracker
    if gt["total"] > 0:
        rate = gt["unanimous"] / gt["total"]
        print(f"Groupthink rate: {rate:.0%} ({gt['unanimous']}/{gt['total']} unanimous)")

    if upset_watch:
        print(f"\nUPSET WATCH ({len(upset_watch)} flagged):")
        for u in sorted(upset_watch, key=lambda x: x["score"], reverse=True):
            print(f"  [{u['score']}/100] {u['game']} ({u['round']}) — Pick: {u['pick']}")

    # Champion announcement for full bracket
    if args.full_bracket and all_debates:
        last = all_debates[-1]
        if last.conductor and last.game.round_name == "NCG":
            print(f"\n{'*'*60}")
            print(f"  PREDICTED CHAMPION: {last.conductor.pick}")
            print(f"  Confidence: {last.conductor.confidence}%")
            print(f"{'*'*60}")

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
    args = parser.parse_args()

    asyncio.run(run_bracket(args))


if __name__ == "__main__":
    main()
