#!/usr/bin/env python3
"""
Pillar 3A: Cost Guardrails — Budget enforcement for API spending.

Thread-safe budget tracker that prevents overspending.
Raises BudgetExceededError if a call would push past the limit.
"""

import asyncio
import logging

log = logging.getLogger("swarm")


class BudgetExceededError(RuntimeError):
    """Raised when an API call would exceed the budget."""
    pass


class CostGuard:
    """
    Async-safe cost guardrail. Checks estimated cost before each API call
    and raises BudgetExceededError if the budget would be exceeded.
    """

    def __init__(self, max_budget: float = 100.0):
        self.max_budget = max_budget
        self.spent = 0.0
        self._lock = asyncio.Lock()
        self._call_count = 0
        self._warnings_issued = 0

    async def check_and_spend(self, estimated_cost: float, label: str = "") -> float:
        """
        Check if we can afford this call, then reserve the cost.
        Returns total spent so far.
        Raises BudgetExceededError if budget would be exceeded.
        """
        async with self._lock:
            if self.spent + estimated_cost > self.max_budget:
                raise BudgetExceededError(
                    f"Budget exceeded: ${self.spent:.2f} spent + ${estimated_cost:.2f} estimated "
                    f"> ${self.max_budget:.2f} limit. {label}"
                )
            self.spent += estimated_cost
            self._call_count += 1

            # Warn at thresholds
            pct = self.spent / self.max_budget
            if pct >= 0.9 and self._warnings_issued < 3:
                log.warning(
                    f"COST GUARD: {pct:.0%} of budget used "
                    f"(${self.spent:.2f}/${self.max_budget:.2f})"
                )
                self._warnings_issued += 1
            elif pct >= 0.75 and self._warnings_issued < 2:
                log.warning(
                    f"COST GUARD: {pct:.0%} of budget used "
                    f"(${self.spent:.2f}/${self.max_budget:.2f})"
                )
                self._warnings_issued += 1
            elif pct >= 0.50 and self._warnings_issued < 1:
                log.info(
                    f"COST GUARD: {pct:.0%} of budget used "
                    f"(${self.spent:.2f}/${self.max_budget:.2f})"
                )
                self._warnings_issued += 1

            return self.spent

    async def record_actual(self, actual_cost: float, estimated_cost: float):
        """
        After a call completes, adjust for the difference between
        estimated and actual cost. This keeps the budget accurate.
        """
        async with self._lock:
            adjustment = actual_cost - estimated_cost
            self.spent += adjustment

    @property
    def remaining(self) -> float:
        return max(0.0, self.max_budget - self.spent)

    @property
    def usage_pct(self) -> float:
        return self.spent / self.max_budget if self.max_budget > 0 else 1.0

    def summary(self) -> str:
        return (
            f"Budget: ${self.spent:.2f}/${self.max_budget:.2f} "
            f"({self.usage_pct:.0%}) | {self._call_count} calls | "
            f"${self.remaining:.2f} remaining"
        )


def estimate_call_cost(
    model: str,
    estimated_input_tokens: int = 500,
    estimated_output_tokens: int = 200,
) -> float:
    """Estimate cost for an API call before making it."""
    if model == "gemini":
        return (
            estimated_input_tokens * 0.075 / 1_000_000
            + estimated_output_tokens * 0.30 / 1_000_000
        )
    else:  # claude
        return (
            estimated_input_tokens * 15.0 / 1_000_000
            + estimated_output_tokens * 75.0 / 1_000_000
        )


def sanitize_team_name(name: str) -> str:
    """
    Pillar 3B: Prompt injection protection via team name sanitization.
    Strips anything that looks like prompt manipulation.
    """
    if not isinstance(name, str):
        return str(name)[:100]

    dangerous_patterns = [
        "ignore previous", "ignore above", "system:", "assistant:",
        "```", "human:", "user:", "IMPORTANT:", "OVERRIDE:",
        "forget everything", "disregard",
    ]
    name_lower = name.lower()
    for pattern in dangerous_patterns:
        if pattern.lower() in name_lower:
            raise ValueError(f"Suspicious team name blocked: {name[:50]}")

    # Length limit and strip
    return name.strip()[:100]
