#!/usr/bin/env python3
"""
Pillar 5: Observability — Structured Logging, Trace IDs, and Calibration Curves.

GameTracer: Per-game trace ID with structured event logging.
CalibrationTracker: Tracks predicted probability vs actual outcome frequency.
AgentPerformanceTracker: Per-agent metrics for dashboard data.
"""

import json
import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

log = logging.getLogger("swarm")


# ---------------------------------------------------------------------------
# 5A: Structured Logging with Trace IDs
# ---------------------------------------------------------------------------
@dataclass
class GameTracer:
    """Per-game tracing with structured events."""
    game_id: str
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    events: list[dict] = field(default_factory=list)

    def log_event(self, event_type: str, agent: str | None = None, data: dict | None = None):
        event = {
            "trace_id": self.trace_id,
            "game_id": self.game_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "agent": agent,
            "data": data,
        }
        self.events.append(event)
        log.info(f"[{self.trace_id}] {event_type}" + (f" | {agent}" if agent else ""))

    def log_round1_start(self, team_a: str, team_b: str, seed_a: int, seed_b: int):
        self.log_event("round1_start", data={
            "team_a": team_a, "team_b": team_b,
            "seed_a": seed_a, "seed_b": seed_b,
        })

    def log_agent_vote(self, agent_name: str, pick: str, probability: float,
                       uncertainty: float, response_time: float, tokens: int, model: str):
        self.log_event("agent_vote", agent=agent_name, data={
            "pick": pick, "probability": probability, "uncertainty": uncertainty,
            "response_time_ms": int(response_time * 1000),
            "tokens_used": tokens, "model": model,
        })

    def log_round2_start(self, n_agents: int):
        self.log_event("round2_start", data={"n_agents": n_agents})

    def log_position_change(self, agent_name: str, old_pick: str, new_pick: str, change_type: str):
        self.log_event("position_change", agent=agent_name, data={
            "old_pick": old_pick, "new_pick": new_pick, "change_type": change_type,
        })

    def log_conductor_decision(self, pick: str, confidence: int,
                               combined_prob: float, combined_unc: float):
        self.log_event("conductor_decision", data={
            "pick": pick, "confidence": confidence,
            "combined_prob": combined_prob, "combined_uncertainty": combined_unc,
        })

    def log_devils_advocate(self, agent_name: str, pick: str, confidence: int):
        self.log_event("devils_advocate", agent=agent_name, data={
            "pick": pick, "confidence": confidence,
        })

    def log_upset_score(self, score: float, vote_split: str):
        self.log_event("upset_score", data={"score": score, "vote_split": vote_split})

    def log_market_edge(self, edge: float, recommendation: str):
        self.log_event("market_edge", data={"edge": edge, "recommendation": recommendation})

    def log_game_complete(self, total_time: float, total_tokens: int, total_cost: float):
        self.log_event("game_complete", data={
            "total_time_ms": int(total_time * 1000),
            "total_tokens": total_tokens, "total_cost": total_cost,
        })

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "game_id": self.game_id,
            "events": self.events,
        }


# ---------------------------------------------------------------------------
# 5B: Agent Performance Tracker (per-agent metrics for dashboard)
# ---------------------------------------------------------------------------
@dataclass
class AgentGameMetric:
    """Per-agent, per-game metric record."""
    agent_name: str
    game_id: str
    round1_prob: float
    round2_prob: float | None
    position_change: str
    rebuttal_target: str
    response_time_ms: int
    tokens_used: int
    cost: float
    model: str
    correct: bool | None = None  # filled in after real result


class AgentPerformanceTracker:
    """Aggregates per-agent metrics across all games."""

    def __init__(self):
        self.metrics: list[AgentGameMetric] = []

    def record(self, metric: AgentGameMetric):
        self.metrics.append(metric)

    def record_from_votes(self, game_id: str, r1_vote, r2_vote=None):
        """Record from AgentVote objects."""
        r2_prob = r2_vote.win_probability if r2_vote and not r2_vote.error else None
        pos_change = r2_vote.position_change if r2_vote and not r2_vote.error else "no_r2"
        rebuttal = r2_vote.rebuttal_target[:100] if r2_vote and r2_vote.rebuttal_target else ""
        total_tokens = r1_vote.input_tokens + r1_vote.output_tokens
        if r2_vote and not r2_vote.error:
            total_tokens += r2_vote.input_tokens + r2_vote.output_tokens

        # Estimate cost
        if r1_vote.model == "gemini":
            # Aligned with cost_guard.py: ~0.075/M input + 0.30/M output ≈ 0.19/M avg
            cost = total_tokens * 0.19e-6
        else:
            # Aligned with cost_guard.py: ~15/M input + 75/M output ≈ 45/M avg
            cost = total_tokens * 45e-6

        self.record(AgentGameMetric(
            agent_name=r1_vote.agent_name,
            game_id=game_id,
            round1_prob=r1_vote.win_probability,
            round2_prob=r2_prob,
            position_change=pos_change,
            rebuttal_target=rebuttal,
            response_time_ms=int(r1_vote.response_time * 1000),
            tokens_used=total_tokens,
            cost=cost,
            model=r1_vote.model,
        ))

    def update_correctness(self, game_id: str, actual_winner: str, team_a: str):
        """Mark whether each agent was correct for a game."""
        for m in self.metrics:
            if m.game_id == game_id:
                # round1_prob > 0.5 means agent picked team_a
                agent_picked_a = m.round1_prob > 0.5
                team_a_won = actual_winner == team_a
                m.correct = (agent_picked_a == team_a_won)

    def get_agent_summary(self) -> dict[str, dict]:
        """Per-agent aggregated stats."""
        by_agent: dict[str, list[AgentGameMetric]] = defaultdict(list)
        for m in self.metrics:
            by_agent[m.agent_name].append(m)

        summaries = {}
        for name, metrics in by_agent.items():
            correct = [m for m in metrics if m.correct is True]
            incorrect = [m for m in metrics if m.correct is False]
            total_judged = len(correct) + len(incorrect)
            summaries[name] = {
                "total_games": len(metrics),
                "correct": len(correct),
                "incorrect": len(incorrect),
                "accuracy": len(correct) / total_judged if total_judged > 0 else None,
                "avg_response_ms": (sum(m.response_time_ms for m in metrics) / len(metrics)) if metrics else 0,
                "total_tokens": sum(m.tokens_used for m in metrics),
                "total_cost": sum(m.cost for m in metrics),
                "position_changes": sum(1 for m in metrics if m.position_change in ("weakened", "flipped")),
            }
        return summaries

    def to_supabase_records(self) -> list[dict]:
        """Export as records suitable for Supabase insertion."""
        return [
            {
                "agent_name": m.agent_name,
                "game_id": m.game_id,
                "round1_prob": round(m.round1_prob, 4),
                "round2_prob": round(m.round2_prob, 4) if m.round2_prob is not None else None,
                "position_change": m.position_change,
                "rebuttal_target": m.rebuttal_target,
                "response_time_ms": m.response_time_ms,
                "tokens_used": m.tokens_used,
                "cost": round(m.cost, 4),
                "model": m.model,
                "correct": m.correct,
            }
            for m in self.metrics
        ]


# ---------------------------------------------------------------------------
# 5C: Calibration Curves
# ---------------------------------------------------------------------------
class CalibrationTracker:
    """
    Track predicted probability vs actual outcome frequency.
    Perfect calibration: 70% predictions should win 70% of the time.
    """

    def __init__(self):
        self.predictions: list[dict] = []

    def record(self, game_id: str, predicted_prob: float, actual_outcome: int,
               agent_name: str | None = None):
        """
        predicted_prob: team_a win probability (0.0-1.0)
        actual_outcome: 1 if team_a won, 0 if team_b won
        """
        self.predictions.append({
            "game_id": game_id,
            "predicted_prob": predicted_prob,
            "actual_outcome": actual_outcome,
            "agent_name": agent_name,
        })

    def calibration_curve(self, min_samples: int = 3) -> dict[float, dict]:
        """
        Bin predictions by probability bucket and compute actual win rate.

        Returns: {0.5: {"predicted": 0.50, "actual": 0.48, "n": 12}, ...}
        """
        bins: dict[float, list[int]] = defaultdict(list)
        for pred in self.predictions:
            # Bin to nearest 0.1
            bucket = round(pred["predicted_prob"] * 10) / 10
            bins[bucket].append(pred["actual_outcome"])

        curve = {}
        for prob, outcomes in sorted(bins.items()):
            if len(outcomes) >= min_samples:
                curve[prob] = {
                    "predicted": prob,
                    "actual": sum(outcomes) / len(outcomes),
                    "n": len(outcomes),
                }
        return curve

    def brier_score(self) -> float | None:
        """Brier score: mean squared error of probability forecasts. Lower = better."""
        if not self.predictions:
            return None
        return sum(
            (p["predicted_prob"] - p["actual_outcome"]) ** 2
            for p in self.predictions
        ) / len(self.predictions)

    def log_loss(self) -> float | None:
        """Log loss (cross-entropy). Lower = better."""
        import math
        if not self.predictions:
            return None
        eps = 1e-15
        total = 0.0
        for p in self.predictions:
            prob = max(eps, min(1 - eps, p["predicted_prob"]))
            outcome = p["actual_outcome"]
            total -= outcome * math.log(prob) + (1 - outcome) * math.log(1 - prob)
        return total / len(self.predictions)

    def calibration_error(self) -> float | None:
        """Expected Calibration Error (ECE). Lower = better."""
        curve = self.calibration_curve(min_samples=1)
        if not curve:
            return None
        total_n = sum(v["n"] for v in curve.values())
        ece = sum(
            v["n"] / total_n * abs(v["predicted"] - v["actual"])
            for v in curve.values()
        )
        return ece

    def print_calibration_report(self):
        """Print a formatted calibration report."""
        curve = self.calibration_curve(min_samples=2)
        brier = self.brier_score()
        ll = self.log_loss()
        ece = self.calibration_error()

        print(f"\n{'='*60}")
        print("CALIBRATION REPORT")
        print(f"{'='*60}")
        print(f"  Total predictions: {len(self.predictions)}")
        if brier is not None:
            print(f"  Brier score: {brier:.4f} (lower = better, random = 0.25)")
        if ll is not None:
            print(f"  Log loss: {ll:.4f} (lower = better, random = 0.693)")
        if ece is not None:
            print(f"  Expected Calibration Error: {ece:.4f} (lower = better)")

        if curve:
            print(f"\n  {'Predicted':>10} {'Actual':>10} {'N':>5} {'Deviation':>10}")
            print(f"  {'-'*40}")
            for prob, data in sorted(curve.items()):
                dev = data["actual"] - data["predicted"]
                bar = "+" * int(abs(dev) * 50)
                direction = "over" if dev > 0 else "under"
                print(f"  {data['predicted']:>9.0%} {data['actual']:>9.0%} {data['n']:>5} "
                      f"  {dev:>+.0%} ({direction})")
        else:
            print("  Not enough data for calibration curve yet.")
        print(f"{'='*60}")

    def to_dict(self) -> dict:
        return {
            "predictions": self.predictions,
            "brier_score": self.brier_score(),
            "log_loss": self.log_loss(),
            "calibration_error": self.calibration_error(),
            "calibration_curve": {
                str(k): v for k, v in self.calibration_curve().items()
            },
        }
