"""Tiered model gateway: routing by step and tenant, token/cost accounting, call logging, JSON validation."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Literal

from pydantic import BaseModel, ValidationError
from sqlalchemy import text

from cortex.config import Settings, get_settings
from cortex.db.session import tenant_session
from cortex.models.client import (
    BedrockClient,
    Completion,
    FakeClient,
    Message,
    ModelClient,
    ModelError,
    OllamaClient,
    OpenAICompatClient,
    TokenCallback,
)
from cortex.observability import metrics

log = logging.getLogger(__name__)

Tier = Literal["small", "large", "judge"]

# Which tier each step uses under the "routed" policy (guide step 4.4). Cheap, structured steps go to the small
# model; writing the final cited answer goes to the large one.
STEP_TIERS: dict[str, Tier] = {
    "route": "small",
    "extract": "small",
    "question_entities": "small",
    "plan": "small",
    "rewrite": "small",
    "code": "large",
    "answer": "large",
    "judge": "judge",
}


class StructuredOutputError(ValueError):
    pass


@dataclass(slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, c: Completion, cost: float) -> None:
        self.input_tokens += c.input_tokens
        self.output_tokens += c.output_tokens
        self.cost_usd += cost
        self.calls += 1


@dataclass
class CallContext:
    """Who a call is for. Every LLM call is logged with tenant, task, step and prompt version."""

    tenant_id: str
    task_id: str | None = None
    confidential: bool = False
    usage: Usage = field(default_factory=Usage)
    log_calls: bool = True


def _price(settings: Settings, tier: str) -> tuple[float, float]:
    if tier == "small":
        return settings.price_small_in, settings.price_small_out
    return settings.price_large_in, settings.price_large_out


def notional_cost(settings: Settings, tier: str, input_tokens: int, output_tokens: int) -> float:
    pin, pout = _price(settings, tier)
    return (input_tokens * pin + output_tokens * pout) / 1_000_000


class LLM:
    def __init__(self, settings: Settings, clients: dict[str, ModelClient]) -> None:
        self.settings = settings
        self._clients = clients

    # ---- routing -------------------------------------------------------------------------------------------
    def resolve(self, step: str, ctx: CallContext) -> tuple[ModelClient, str, Tier]:
        s = self.settings
        tier: Tier = STEP_TIERS.get(step, "small")
        if tier != "judge":
            if s.routing_policy == "small-only":
                tier = "small"
            elif s.routing_policy == "large-only":
                tier = "large"
        provider = s.model_provider
        if tier == "large" and s.model_provider_large and not ctx.confidential:
            provider = s.model_provider_large
        if ctx.confidential and provider not in ("ollama", "fake"):
            provider = "ollama"  # confidential tenants never leave the machine
        client = self._clients.get(provider) or self._clients[s.model_provider]
        model = self._model_name(client.provider, tier)
        return client, model, tier

    def _model_name(self, provider: str, tier: Tier) -> str:
        s = self.settings
        if provider == "bedrock":
            return s.bedrock_model_small if tier == "small" else s.bedrock_model_large
        if provider == "openai_compat":
            return s.openai_compat_model_large
        if tier == "judge":
            return s.model_judge
        return s.model_small if tier == "small" else s.model_large

    # ---- calls ---------------------------------------------------------------------------------------------
    def complete(
        self,
        ctx: CallContext,
        *,
        step: str,
        prompt_version: str,
        messages: Sequence[Message],
        max_tokens: int = 1024,
        json_schema: dict[str, Any] | None = None,
        on_token: TokenCallback | None = None,
    ) -> Completion:
        client, model, tier = self.resolve(step, ctx)
        try:
            completion = client.complete(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                json_schema=json_schema,
                on_token=on_token,
            )
        except ModelError as exc:
            metrics.LLM_ERRORS.labels(provider=client.provider, throttled=str(exc.throttled).lower()).inc()
            self._log(ctx, step, client.provider, model, tier, prompt_version, None, 0.0, error=str(exc))
            raise
        cost = notional_cost(self.settings, tier, completion.input_tokens, completion.output_tokens)
        ctx.usage.add(completion, cost)
        metrics.LLM_CALLS.labels(provider=client.provider, tier=tier, step=step).inc()
        metrics.LLM_TOKENS.labels(tier=tier, kind="input").inc(completion.input_tokens)
        metrics.LLM_TOKENS.labels(tier=tier, kind="output").inc(completion.output_tokens)
        metrics.LLM_COST.labels(tier=tier).inc(cost)
        metrics.LLM_LATENCY.labels(tier=tier).observe(completion.latency_ms / 1000)
        self._log(ctx, step, client.provider, model, tier, prompt_version, completion, cost)
        return completion

    def complete_json[T: BaseModel](
        self,
        ctx: CallContext,
        schema: type[T],
        *,
        step: str,
        prompt_version: str,
        messages: Sequence[Message],
        max_tokens: int = 1024,
        retries: int = 1,
    ) -> T:
        """Structured output validated by Pydantic. Invalid output is retried once with the error, then raised."""
        json_schema = schema.model_json_schema()
        convo = list(messages)
        last_error = ""
        for _attempt in range(retries + 1):
            c = self.complete(
                ctx,
                step=step,
                prompt_version=prompt_version,
                messages=convo,
                max_tokens=max_tokens,
                json_schema=json_schema,
            )
            try:
                return schema.model_validate_json(_extract_json(c.text))
            except (ValidationError, ValueError) as exc:
                last_error = str(exc)[:500]
                convo = [
                    *messages,
                    Message("assistant", c.text[:2000]),
                    Message(
                        "user", f"That was not valid JSON for the schema: {last_error}. Reply with JSON only."
                    ),
                ]
        metrics.STRUCTURED_OUTPUT_FAILURES.labels(step=step).inc()
        raise StructuredOutputError(f"{step}: invalid structured output: {last_error}")

    def _log(
        self,
        ctx: CallContext,
        step: str,
        provider: str,
        model: str,
        tier: str,
        prompt_version: str,
        c: Completion | None,
        cost: float,
        error: str | None = None,
    ) -> None:
        if not ctx.log_calls:
            return
        try:
            with tenant_session(ctx.tenant_id) as db:
                db.execute(
                    text(
                        "INSERT INTO llm_calls (tenant_id, task_id, step, provider, model, tier, prompt_version,"
                        " input_tokens, output_tokens, cost_usd, latency_ms, ok, error) VALUES (:t, :task, :step,"
                        " :p, :m, :tier, :pv, :i, :o, :cost, :lat, :ok, :err)"
                    ),
                    {
                        "t": ctx.tenant_id,
                        "task": ctx.task_id,
                        "step": step,
                        "p": provider,
                        "m": model,
                        "tier": tier,
                        "pv": prompt_version,
                        "i": c.input_tokens if c else 0,
                        "o": c.output_tokens if c else 0,
                        "cost": cost,
                        "lat": c.latency_ms if c else 0,
                        "ok": error is None,
                        "err": error,
                    },
                )
        except Exception:  # logging must never break an answer
            log.exception("failed to record llm call")


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _extract_json(raw: str) -> str:
    """Accept a bare JSON object, or one wrapped in a code fence or prose (common with small models)."""
    raw = raw.strip()
    if raw.startswith(("{", "[")):
        return raw
    m = _FENCE.search(raw)
    if m:
        return m.group(1).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        candidate = raw[start : end + 1]
        json.loads(candidate)
        return candidate
    raise ValueError("no JSON object in model output")


ClientFactory = Callable[[Settings], dict[str, ModelClient]]


def default_clients(settings: Settings) -> dict[str, ModelClient]:
    clients: dict[str, ModelClient] = {
        "ollama": OllamaClient(settings.ollama_url, settings.llm_timeout_seconds),
    }
    if settings.openai_compat_api_key is not None:
        clients["openai_compat"] = OpenAICompatClient(
            settings.openai_compat_base_url,
            settings.openai_compat_api_key.get_secret_value(),
            settings.llm_timeout_seconds,
        )
    if "bedrock" in (settings.model_provider, settings.model_provider_large):
        clients["bedrock"] = BedrockClient(settings.bedrock_region)
    if settings.model_provider == "fake":
        clients["fake"] = FakeClient(lambda _m, _msgs: "")
    return clients


_override: LLM | None = None


def set_llm(llm: LLM | None) -> None:
    """Tests install an LLM built on a FakeClient."""
    global _override
    _override = llm


@lru_cache
def _default_llm() -> LLM:
    s = get_settings()
    return LLM(s, default_clients(s))


def get_llm() -> LLM:
    return _override or _default_llm()
