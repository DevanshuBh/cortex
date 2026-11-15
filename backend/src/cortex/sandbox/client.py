"""Client for the sandbox-runner service. The worker never touches Docker itself (design §8.6)."""

from __future__ import annotations

from typing import Any

import httpx

from cortex.config import get_settings
from cortex.observability import metrics

MAX_CODE_BYTES = 16_000


def run_code(code: str, timeout_s: float = 10.0) -> dict[str, Any]:
    if len(code.encode()) > MAX_CODE_BYTES:
        metrics.SANDBOX_RUNS.labels(outcome="rejected").inc()
        return {
            "stdout": "",
            "stderr": "code too large",
            "exit_code": -1,
            "timed_out": False,
            "truncated": False,
        }
    s = get_settings()
    try:
        resp = httpx.post(
            f"{s.sandbox_runner_url}/run",
            json={"code": code, "timeout_s": timeout_s},
            headers={"Authorization": f"Bearer {s.sandbox_runner_token.get_secret_value()}"},
            timeout=timeout_s + 20,
        )
        resp.raise_for_status()
        out: dict[str, Any] = resp.json()
    except httpx.HTTPError as exc:
        metrics.SANDBOX_RUNS.labels(outcome="unavailable").inc()
        return {
            "stdout": "",
            "stderr": f"sandbox unavailable: {exc}",
            "exit_code": -1,
            "timed_out": False,
            "truncated": False,
        }
    outcome = "timeout" if out.get("timed_out") else ("ok" if out.get("exit_code") == 0 else "error")
    metrics.SANDBOX_RUNS.labels(outcome=outcome).inc()
    return out
