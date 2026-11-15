"""Tools and the per-agent allow-list, enforced in code rather than by prompt (guide step 4.6).

Every tool call goes through ``Toolbox.call``: it checks the calling agent's allow-list, records the call with the
loop guard, and keeps an idempotency ledger in ``tool_effects`` keyed by (run_id, step, tool, args) — so a task
redelivered after a worker crash replays recorded results instead of repeating side effects (guide step 4.5,
staff step S.5).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import text

from cortex.agents.guard import LoopGuard, call_signature
from cortex.db.session import tenant_session

log = logging.getLogger(__name__)

ToolFn = Callable[[dict[str, Any]], dict[str, Any]]

ALLOW_LIST: dict[str, frozenset[str]] = {
    "researcher": frozenset({"hybrid_search", "graph_search"}),
    "coder": frozenset({"run_code"}),
    "analyst": frozenset(),
}
SIDE_EFFECT_TOOLS = frozenset({"run_code"})


class ToolNotAllowed(PermissionError):
    pass


class RepeatedCall(RuntimeError):
    pass


class Toolbox:
    def __init__(
        self,
        tenant_id: str,
        run_id: str | None,
        guard: LoopGuard,
        tools: dict[str, ToolFn],
        *,
        ledger: bool = True,
    ) -> None:
        self.tenant_id = tenant_id
        self.run_id = run_id
        self.guard = guard
        self._tools = tools
        self._ledger = ledger and run_id is not None
        self.calls: list[dict[str, Any]] = []

    def call(self, agent: str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool not in ALLOW_LIST.get(agent, frozenset()):
            raise ToolNotAllowed(f"agent {agent!r} may not call {tool!r}")
        if tool not in self._tools:
            raise ToolNotAllowed(f"tool {tool!r} is not available")
        if not self.guard.note_call(tool, args):
            raise RepeatedCall(f"{tool} called again with the same arguments")
        step = len(self.calls)
        args_hash = call_signature(tool, args)
        if self._ledger and tool in SIDE_EFFECT_TOOLS:
            recorded = self._recorded(step, tool, args_hash)
            if recorded is not None:
                log.info("replaying recorded %s result for run %s step %d", tool, self.run_id, step)
                self.calls.append({"agent": agent, "tool": tool, "args": args, "replayed": True})
                return recorded
        result = self._tools[tool](args)
        if self._ledger and tool in SIDE_EFFECT_TOOLS:
            self._record(step, tool, args_hash, result)
        self.calls.append({"agent": agent, "tool": tool, "args": args})
        return result

    def _recorded(self, step: int, tool: str, args_hash: str) -> dict[str, Any] | None:
        with tenant_session(self.tenant_id) as db:
            row = db.execute(
                text(
                    "SELECT result FROM tool_effects WHERE tenant_id = :t AND run_id = CAST(:r AS uuid) AND step = :s"
                    " AND tool = :tool AND args_hash = :h"
                ),
                {"t": self.tenant_id, "r": self.run_id, "s": step, "tool": tool, "h": args_hash},
            ).first()
        return dict(row[0]) if row else None

    def _record(self, step: int, tool: str, args_hash: str, result: dict[str, Any]) -> None:
        with tenant_session(self.tenant_id) as db:
            db.execute(
                text(
                    "INSERT INTO tool_effects (tenant_id, run_id, step, tool, args_hash, result) VALUES (:t,"
                    " CAST(:r AS uuid), :s, :tool, :h, CAST(:res AS jsonb)) ON CONFLICT DO NOTHING"
                ),
                {
                    "t": self.tenant_id,
                    "r": self.run_id,
                    "s": step,
                    "tool": tool,
                    "h": args_hash,
                    "res": json.dumps(result),
                },
            )
