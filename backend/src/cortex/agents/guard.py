"""Loop guard: the conditions that guarantee every agent run ends (guide step 4.2, design §8.5).

A run stops when it has used its step budget, its token budget or its wall-clock budget; when the last N steps
added no new evidence; or when a tool call repeats exactly. The supervisor then writes the best answer it can from
the evidence so far, marked partial.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Budget:
    max_steps: int
    max_tokens: int
    no_progress_steps: int
    wall_clock_seconds: float


def call_signature(tool: str, args: dict[str, Any]) -> str:
    norm = json.dumps({"tool": tool, "args": args}, sort_keys=True, default=str).lower()
    return hashlib.sha256(norm.encode()).hexdigest()[:16]


@dataclass
class LoopGuard:
    budget: Budget
    started: float = field(default_factory=time.monotonic)
    steps: int = 0
    no_progress: int = 0
    signatures: set[str] = field(default_factory=set)
    stop_reason: str | None = None

    def record_step(self, new_evidence: int) -> None:
        self.steps += 1
        self.no_progress = 0 if new_evidence > 0 else self.no_progress + 1

    def note_call(self, tool: str, args: dict[str, Any]) -> bool:
        """Record a tool call; returns False (and sets the stop reason) if it is an exact repeat."""
        sig = call_signature(tool, args)
        if sig in self.signatures:
            self.stop_reason = "repeated_tool_call"
            return False
        self.signatures.add(sig)
        return True

    def check(self, tokens_used: int) -> str | None:
        if self.stop_reason:
            return self.stop_reason
        b = self.budget
        if self.steps >= b.max_steps:
            self.stop_reason = "step_budget"
        elif tokens_used >= b.max_tokens:
            self.stop_reason = "token_budget"
        elif self.no_progress >= b.no_progress_steps:
            self.stop_reason = "no_progress"
        elif time.monotonic() - self.started >= b.wall_clock_seconds:
            self.stop_reason = "wall_clock"
        return self.stop_reason

    def remaining(self, tokens_used: int) -> dict[str, float]:
        return {
            "steps": max(0, self.budget.max_steps - self.steps),
            "tokens": max(0, self.budget.max_tokens - tokens_used),
            "seconds": max(0.0, self.budget.wall_clock_seconds - (time.monotonic() - self.started)),
        }
