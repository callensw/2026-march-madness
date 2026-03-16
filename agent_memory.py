#!/usr/bin/env python3
"""
Pillar 1A: Agent Tournament Memory

Persistent memory for each agent across the tournament.
Tracks past picks, accuracy by game type, confidence calibration,
and cross-attention flips.

DESIGN NOTE — Two modes:
1. PREDICTION MODE (--full-bracket): Memory is EMPTY. Agents operate
   purely on pre-tournament data. No self-awareness, no feedback loops.
   This is the initial bracket fill before games are played.

2. LIVE-UPDATE MODE (--live-update R32): Memory is POPULATED with real
   results from completed rounds. Agents get self-awareness context:
   "In R64 I went 6/8, my biggest miss was..."
   Re-runs remaining rounds with informed agents.
"""

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("swarm")


@dataclass
class AgentMemory:
    """Persistent memory for a single agent across the tournament."""
    agent_name: str
    past_picks: list[dict] = field(default_factory=list)
    accuracy_by_type: dict[str, dict] = field(default_factory=dict)
    biggest_misses: list[dict] = field(default_factory=list)
    confidence_calibration: list[tuple[float, int]] = field(default_factory=list)
    cross_attention_memory: list[dict] = field(default_factory=list)

    def has_real_results(self) -> bool:
        """True only if we have actual game outcomes, not just predictions."""
        return any(p.get("actual_result") is not None for p in self.past_picks)

    def get_context_for_game(self, round_number: int) -> str:
        """
        Generate contextual summary for the agent's prompt.
        Only returns content if we have REAL results (live-update mode).
        In prediction mode, returns empty string — no fake self-awareness.
        """
        if not self.has_real_results():
            return ""

        accuracy = self._get_accuracy()
        if accuracy["total"] == 0:
            return ""

        recent_misses = self._get_recent_misses(3)
        calibration = self._get_calibration_summary()
        good_flips = self._count_good_flips()
        bad_flips = self._count_bad_flips()
        best_type = self._best_game_type()
        worst_type = self._worst_game_type()

        lines = [
            f"TOURNAMENT MEMORY (Round {round_number}) — based on REAL results:",
            f"- My accuracy so far: {accuracy['correct']}/{accuracy['total']} ({accuracy['pct']:.0%})",
        ]

        if recent_misses:
            miss = recent_misses[0]
            lines.append(
                f"- My biggest recent miss: Picked {miss.get('pick', '?')} "
                f"in {miss.get('game_label', '?')} — {miss.get('actual_result', '?')} won"
            )

        if calibration:
            for bucket, actual in sorted(calibration.items()):
                lines.append(f"- When I say {bucket}%, outcomes happen {actual:.0f}% of the time")

        if good_flips or bad_flips:
            lines.append(f"- Times I changed my mind in Round 2 and was RIGHT: {good_flips}")
            lines.append(f"- Times I changed my mind in Round 2 and was WRONG: {bad_flips}")

        if best_type:
            lines.append(f"- My best game type: {best_type}")
        if worst_type:
            lines.append(f"- My worst game type: {worst_type}")

        lines.append(
            "\nUse this self-awareness to adjust your analysis. If you've been "
            "wrong about a specific type of game, acknowledge it and consider "
            "weighting other factors more heavily."
        )

        return "\n".join(lines) + "\n"

    def record_pick(
        self,
        game_label: str,
        pick: str,
        probability: float,
        round_name: str,
        game_type: str = "",
        position_change: str = "unchanged",
    ):
        """Record a prediction (no actual result yet)."""
        self.past_picks.append({
            "game_label": game_label,
            "pick": pick,
            "probability": probability,
            "round_name": round_name,
            "game_type": game_type,
            "position_change": position_change,
            "actual_result": None,
        })
        if position_change in ("weakened", "flipped"):
            self.cross_attention_memory.append(self.past_picks[-1])

    def record_real_result(self, game_label: str, actual_winner: str):
        """Called when real game results come in. THIS is what enables self-awareness."""
        for pick in self.past_picks:
            if pick["game_label"] == game_label and pick["actual_result"] is None:
                pick["actual_result"] = actual_winner
                correct = pick["pick"] == actual_winner

                if not correct:
                    self.biggest_misses.append(pick)

                # Update calibration
                self.confidence_calibration.append((pick["probability"], 1 if correct else 0))

                # Update accuracy by game type
                game_type = pick.get("game_type", "unknown")
                if game_type not in self.accuracy_by_type:
                    self.accuracy_by_type[game_type] = {"correct": 0, "total": 0}
                self.accuracy_by_type[game_type]["total"] += 1
                if correct:
                    self.accuracy_by_type[game_type]["correct"] += 1

                # Update cross-attention entries
                for cam in self.cross_attention_memory:
                    if cam["game_label"] == game_label:
                        cam["actual_result"] = actual_winner
                break

    def _get_accuracy(self) -> dict:
        picks_with_results = [p for p in self.past_picks if p.get("actual_result")]
        total = len(picks_with_results)
        correct = sum(1 for p in picks_with_results if p["pick"] == p["actual_result"])
        pct = correct / total if total > 0 else 0.0
        return {"correct": correct, "total": total, "pct": pct}

    def _get_recent_misses(self, n: int) -> list[dict]:
        return self.biggest_misses[-n:]

    def _get_calibration_summary(self) -> dict[int, float]:
        if not self.confidence_calibration:
            return {}
        bins: dict[int, list[int]] = defaultdict(list)
        for prob, outcome in self.confidence_calibration:
            bucket = int(round(prob * 10) * 10)
            bins[bucket].append(outcome)
        return {
            bucket: (sum(outcomes) / len(outcomes) * 100)
            for bucket, outcomes in bins.items()
            if len(outcomes) >= 2
        }

    def _count_good_flips(self) -> int:
        return sum(
            1 for p in self.cross_attention_memory
            if p.get("actual_result") and p["pick"] == p["actual_result"]
        )

    def _count_bad_flips(self) -> int:
        return sum(
            1 for p in self.cross_attention_memory
            if p.get("actual_result") and p["pick"] != p["actual_result"]
        )

    def _best_game_type(self) -> str:
        best, best_pct = "", 0.0
        for gtype, stats in self.accuracy_by_type.items():
            if stats["total"] >= 2:
                pct = stats["correct"] / stats["total"]
                if pct > best_pct:
                    best_pct = pct
                    best = f"{gtype} ({stats['correct']}/{stats['total']})"
        return best

    def _worst_game_type(self) -> str:
        worst, worst_pct = "", 1.0
        for gtype, stats in self.accuracy_by_type.items():
            if stats["total"] >= 2:
                pct = stats["correct"] / stats["total"]
                if pct < worst_pct:
                    worst_pct = pct
                    worst = f"{gtype} ({stats['correct']}/{stats['total']})"
        return worst

    def to_dict(self) -> dict:
        return {
            "agent_name": self.agent_name,
            "past_picks": self.past_picks,
            "accuracy_by_type": self.accuracy_by_type,
            "biggest_misses": self.biggest_misses[-10:],
            "confidence_calibration": self.confidence_calibration[-50:],
            "cross_attention_memory": self.cross_attention_memory[-20:],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgentMemory":
        mem = cls(agent_name=data["agent_name"])
        mem.past_picks = data.get("past_picks", [])
        mem.accuracy_by_type = data.get("accuracy_by_type", {})
        mem.biggest_misses = data.get("biggest_misses", [])
        mem.confidence_calibration = [tuple(x) for x in data.get("confidence_calibration", [])]
        mem.cross_attention_memory = data.get("cross_attention_memory", [])
        return mem


class TournamentMemoryStore:
    """
    Manages AgentMemory instances for all agents, with persistence.

    In prediction mode: memories exist but are empty. get_context() returns "".
    In live-update mode: memories are loaded from disk with real results.
    """

    def __init__(self, agents: list[str], save_path: Path | None = None):
        self.memories: dict[str, AgentMemory] = {
            name: AgentMemory(agent_name=name) for name in agents
        }
        self.save_path = save_path or Path(__file__).parent / "tournament_memory.json"

    def get(self, agent_name: str) -> AgentMemory:
        if agent_name not in self.memories:
            self.memories[agent_name] = AgentMemory(agent_name=agent_name)
        return self.memories[agent_name]

    def get_context(self, agent_name: str, round_number: int) -> str:
        """Get tournament memory context. Returns "" in prediction mode."""
        return self.get(agent_name).get_context_for_game(round_number)

    def record_pick(self, agent_name: str, **kwargs):
        self.get(agent_name).record_pick(**kwargs)

    def record_result(self, game_label: str, actual_winner: str):
        """Update ALL agents with a real game result."""
        for mem in self.memories.values():
            mem.record_real_result(game_label, actual_winner)

    def has_real_data(self) -> bool:
        """True if any agent has real results (i.e., we're in live-update mode)."""
        return any(mem.has_real_results() for mem in self.memories.values())

    def save(self):
        data = {name: mem.to_dict() for name, mem in self.memories.items()}
        with open(self.save_path, "w") as f:
            json.dump(data, f, indent=2)
        log.info(f"Tournament memory saved to {self.save_path}")

    def load(self) -> bool:
        """Load from disk. Returns True if loaded successfully."""
        if self.save_path.exists():
            try:
                with open(self.save_path) as f:
                    data = json.load(f)
                for name, mem_data in data.items():
                    self.memories[name] = AgentMemory.from_dict(mem_data)
                log.info(f"Tournament memory loaded: {len(self.memories)} agents")
                return True
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                log.warning(f"Corrupt tournament memory file, starting fresh: {e}")
                return False
        return False

    def summary(self) -> str:
        lines = ["Tournament Memory Summary:"]
        for name, mem in sorted(self.memories.items()):
            acc = mem._get_accuracy()
            if acc["total"] > 0:
                lines.append(
                    f"  {name}: {acc['correct']}/{acc['total']} ({acc['pct']:.0%}) | "
                    f"Misses: {len(mem.biggest_misses)} | Flips: {len(mem.cross_attention_memory)}"
                )
            else:
                lines.append(f"  {name}: No results yet (prediction mode)")
        return "\n".join(lines)


def classify_game_type(seed_a: int, seed_b: int) -> str:
    """Classify a game for accuracy tracking."""
    diff = abs(seed_a - seed_b)
    if diff >= 12:
        return "blowout"
    elif diff >= 8:
        return "heavy_favorite"
    elif diff >= 4:
        return "moderate_favorite"
    elif diff >= 2:
        return "tossup_lean"
    else:
        return "coin_flip"
