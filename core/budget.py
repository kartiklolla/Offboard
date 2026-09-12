from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Budget:
    max_steps: int = 400
    max_live_calls: int = 60
    max_cost_usd: float = 2.0
    max_writes: int = 40

    steps: int = 0
    live_calls: int = 0
    cost_usd: float = 0.0
    writes: int = 0

    def charge(self, step: Any) -> None:
        self.steps += 1
        self.cost_usd += step.cost_usd
        if step.mode == "live" and step.kind == "tool_call":
            self.live_calls += 1
        if step.kind == "tool_call" and step.risk in ("reversible", "irreversible"):
            self.writes += 1
        self._assert()

    def _assert(self) -> None:
        if self.steps > self.max_steps:
            raise BudgetExceeded(f"steps {self.steps} > {self.max_steps}")
        if self.live_calls > self.max_live_calls:
            raise BudgetExceeded(f"live calls {self.live_calls} > {self.max_live_calls}")
        if self.cost_usd > self.max_cost_usd:
            raise BudgetExceeded(f"cost {self.cost_usd:.4f} > {self.max_cost_usd}")
        if self.writes > self.max_writes:
            raise BudgetExceeded(f"writes {self.writes} > {self.max_writes}")

    def summary(self) -> dict:
        return {
            "steps": self.steps,
            "live_calls": self.live_calls,
            "writes": self.writes,
            "cost_usd": round(self.cost_usd, 6),
        }
