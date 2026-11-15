"""One ModelClient interface, several providers (docs/adr/0005).

Providers: local Ollama (default, free), any OpenAI-compatible endpoint, Amazon Bedrock (Converse API) and a
scripted fake for tests. Callers never see provider details: they ask for a tier through ``cortex.models.llm``.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx

Role = Literal["system", "user", "assistant"]
TokenCallback = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: str


@dataclass(slots=True)
class Completion:
    text: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0


class ModelError(RuntimeError):
    """Provider failure (network, HTTP error, throttling). ``throttled`` lets callers count throttling."""

    def __init__(self, message: str, *, throttled: bool = False) -> None:
        super().__init__(message)
        self.throttled = throttled


class ModelClient(Protocol):
    provider: str

    def complete(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        max_tokens: int,
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        on_token: TokenCallback | None = None,
    ) -> Completion: ...


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class OllamaClient:
    """Ollama native /api/chat. ``think: false`` keeps reasoning models from spending tokens on hidden thought."""

    provider = "ollama"

    def __init__(self, base_url: str, timeout: float) -> None:
        self._http = httpx.Client(base_url=base_url, timeout=httpx.Timeout(timeout, connect=10.0))

    def complete(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        max_tokens: int,
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        on_token: TokenCallback | None = None,
    ) -> Completion:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": on_token is not None,
            "think": False,
            "keep_alive": "30m",
            "options": {"temperature": temperature, "num_predict": max_tokens, "num_ctx": 8192, "seed": 7},
        }
        if json_schema is not None:
            payload["format"] = json_schema
        started = time.perf_counter()
        try:
            if on_token is None:
                resp = self._http.post("/api/chat", json=payload)
                self._raise(resp)
                body = resp.json()
                text = body.get("message", {}).get("content", "")
                return Completion(
                    text=text,
                    model=model,
                    provider=self.provider,
                    input_tokens=int(body.get("prompt_eval_count") or 0),
                    output_tokens=int(body.get("eval_count") or _approx_tokens(text)),
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )
            parts: list[str] = []
            final: dict[str, Any] = {}
            with self._http.stream("POST", "/api/chat", json=payload) as resp:
                if resp.status_code >= 400:
                    resp.read()
                    self._raise(resp)
                for line in resp.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    piece = chunk.get("message", {}).get("content", "")
                    if piece:
                        parts.append(piece)
                        on_token(piece)
                    if chunk.get("done"):
                        final = chunk
            text = "".join(parts)
            return Completion(
                text=text,
                model=model,
                provider=self.provider,
                input_tokens=int(final.get("prompt_eval_count") or 0),
                output_tokens=int(final.get("eval_count") or _approx_tokens(text)),
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        except httpx.HTTPError as exc:
            raise ModelError(f"ollama request failed: {exc}") from exc

    @staticmethod
    def _raise(resp: httpx.Response) -> None:
        if resp.status_code >= 400:
            raise ModelError(
                f"ollama HTTP {resp.status_code}: {resp.text[:300]}", throttled=resp.status_code in (429, 503)
            )


class OpenAICompatClient:
    """Any OpenAI-compatible chat endpoint (Groq, Gemini, OpenRouter, vLLM, …) over plain HTTP."""

    provider = "openai_compat"

    def __init__(self, base_url: str, api_key: str, timeout: float) -> None:
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout, connect=10.0),
            headers={"Authorization": f"Bearer {api_key}"},
        )

    def complete(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        max_tokens: int,
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        on_token: TokenCallback | None = None,
    ) -> Completion:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if json_schema is not None:
            # json_object is the widely supported mode; the caller validates against the schema.
            payload["response_format"] = {"type": "json_object"}
        started = time.perf_counter()
        try:
            if on_token is None:
                resp = self._http.post("/chat/completions", json=payload)
                self._raise(resp)
                body = resp.json()
                text = body["choices"][0]["message"].get("content") or ""
                usage = body.get("usage") or {}
                return Completion(
                    text=text,
                    model=model,
                    provider=self.provider,
                    input_tokens=int(usage.get("prompt_tokens") or 0),
                    output_tokens=int(usage.get("completion_tokens") or _approx_tokens(text)),
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}
            parts: list[str] = []
            usage = {}
            with self._http.stream("POST", "/chat/completions", json=payload) as resp:
                if resp.status_code >= 400:
                    resp.read()
                    self._raise(resp)
                for line in resp.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    if chunk.get("usage"):
                        usage = chunk["usage"]
                    for choice in chunk.get("choices") or []:
                        piece = (choice.get("delta") or {}).get("content") or ""
                        if piece:
                            parts.append(piece)
                            on_token(piece)
            text = "".join(parts)
            return Completion(
                text=text,
                model=model,
                provider=self.provider,
                input_tokens=int(usage.get("prompt_tokens") or 0),
                output_tokens=int(usage.get("completion_tokens") or _approx_tokens(text)),
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        except httpx.HTTPError as exc:
            raise ModelError(f"openai-compatible request failed: {exc}") from exc

    @staticmethod
    def _raise(resp: httpx.Response) -> None:
        if resp.status_code >= 400:
            raise ModelError(f"HTTP {resp.status_code}: {resp.text[:300]}", throttled=resp.status_code == 429)


class BedrockClient:
    """Amazon Bedrock Converse API. Credentials come from the IAM role — no stored API key (guide step 6.3)."""

    provider = "bedrock"

    def __init__(self, region: str) -> None:
        import boto3

        self._client = boto3.client("bedrock-runtime", region_name=region)

    def complete(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        max_tokens: int,
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        on_token: TokenCallback | None = None,
    ) -> Completion:
        system = [{"text": m.content} for m in messages if m.role == "system"]
        if json_schema is not None:
            system.append({"text": "Reply with a single JSON object matching: " + json.dumps(json_schema)})
        convo = [{"role": m.role, "content": [{"text": m.content}]} for m in messages if m.role != "system"]
        args: dict[str, Any] = {
            "modelId": model,
            "messages": convo,
            "system": system,
            "inferenceConfig": {"maxTokens": max_tokens, "temperature": temperature},
        }
        started = time.perf_counter()
        try:
            if on_token is None:
                out = self._client.converse(**args)
                text = "".join(b.get("text", "") for b in out["output"]["message"]["content"])
                usage = out.get("usage", {})
            else:
                parts: list[str] = []
                usage = {}
                for event in self._client.converse_stream(**args)["stream"]:
                    if "contentBlockDelta" in event:
                        piece = event["contentBlockDelta"]["delta"].get("text", "")
                        parts.append(piece)
                        on_token(piece)
                    elif "metadata" in event:
                        usage = event["metadata"].get("usage", {})
                text = "".join(parts)
        except Exception as exc:  # botocore raises many types; throttling is the one callers count
            name = type(exc).__name__
            raise ModelError(f"bedrock: {name}: {exc}", throttled="Throttling" in name) from exc
        return Completion(
            text=text,
            model=model,
            provider=self.provider,
            input_tokens=int(usage.get("inputTokens") or 0),
            output_tokens=int(usage.get("outputTokens") or _approx_tokens(text)),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


Responder = Callable[[str, Sequence[Message]], str]


@dataclass
class FakeClient:
    """Deterministic model for tests: ``responder(model, messages) -> text``. Records every call."""

    responder: Responder
    provider: str = "fake"
    calls: list[tuple[str, list[Message]]] = field(default_factory=list)

    def complete(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        max_tokens: int,
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        on_token: TokenCallback | None = None,
    ) -> Completion:
        self.calls.append((model, list(messages)))
        text = self.responder(model, messages)
        if on_token is not None:
            for word in text.split(" "):
                on_token(word + " ")
        prompt = "".join(m.content for m in messages)
        return Completion(
            text=text,
            model=model,
            provider=self.provider,
            input_tokens=_approx_tokens(prompt),
            output_tokens=_approx_tokens(text),
            latency_ms=1,
        )
