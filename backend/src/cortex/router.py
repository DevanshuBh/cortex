"""Question router: content / relationship / both (guide step 3.3).

Two implementations behind one signature so they can be compared on the labelled router set
(eval/router_queries.jsonl): a rule-based router (free, instant) and an LLM classifier. The cheaper one ships
unless the other is clearly more accurate (docs/adr/0006).
"""

from __future__ import annotations

import re
from typing import Literal, Protocol

from pydantic import BaseModel

from cortex.models.client import Message
from cortex.models.llm import LLM, CallContext, StructuredOutputError

Route = Literal["content", "relationship", "both"]
ROUTES: tuple[Route, ...] = ("content", "relationship", "both")


class Router(Protocol):
    name: str

    def route(self, question: str) -> Route: ...


_REL_PATTERNS = [
    r"\brelat(?:e|es|ed|ion|ionship|ionships)\b",
    r"\b(?:connect(?:s|ed|ion)?|link(?:s|ed)?)\b.*\b(?:to|with|between)\b",
    r"\bbetween\b.+\band\b",
    r"\bdepend(?:s|ency|encies|ent)?\b",
    r"\bwhich\b.+\b(?:manage|manages|managed|create|creates|created|control|controls|own|owns|owned|"
    r"schedule|schedules|run|runs|use|uses|expose|exposes|contain|contains)\b",
    r"\bwhat\b.+\b(?:manages|creates|controls|owns|schedules|runs on|uses|exposes|contains)\b",
    r"\b(?:manage[sd]?|create[sd]?|control(?:s|led)?|own(?:s|ed)?)\s+by\b",
    r"\bchain\b|\bhierarch(?:y|ies)\b|\bpath from\b|\bhops?\b",
    r"\bwho\b.+\b(?:responsible|in charge)\b",
]
_CONTENT_PATTERNS = [
    r"^\s*(?:how do i|how to|how can|how does|why|explain|describe|what is|what are|what does|when should|can i|"
    r"list|give)\b",
    r"\b(?:example|default|configure|configuration|field|flag|option|limit|value|command|syntax|steps?)\b",
]
_REL = [re.compile(p, re.IGNORECASE) for p in _REL_PATTERNS]
# Case-sensitive: a control verb followed by a capitalised resource name ("controls Pods").
_REL_CASED = [
    re.compile(
        r"\b(?:control|controls|manage|manages|create|creates|own|owns|schedule|schedules|expose|exposes|"
        r"run|runs)\s+(?:the\s+|its\s+|a\s+)?[A-Z][A-Za-z]+"
    )
]
_CONTENT = [re.compile(p, re.IGNORECASE) for p in _CONTENT_PATTERNS]


class RuleRouter:
    name = "rules"

    def route(self, question: str) -> Route:
        rel = sum(1 for p in [*_REL, *_REL_CASED] if p.search(question))
        content = sum(1 for p in _CONTENT if p.search(question))
        if rel == 0:
            return "content"
        if content >= 1 and rel == 1:
            return "both"
        return "relationship"


class _RouteOut(BaseModel):
    route: Route


ROUTER_PROMPT_VERSION = "route-v1"
ROUTER_SYSTEM = (
    "Classify a question about a document collection.\n"
    "- content: answered by reading passages (definitions, how-to, configuration, explanations).\n"
    "- relationship: asks how named things are connected (what manages/creates/depends on what, chains of "
    "ownership, which component uses another).\n"
    "- both: needs the connections AND explanatory detail from passages.\n"
    'Reply with JSON only: {"route": "content" | "relationship" | "both"}'
)


class LLMRouter:
    name = "llm"

    def __init__(self, llm: LLM, ctx: CallContext, fallback: Router | None = None) -> None:
        self._llm, self._ctx = llm, ctx
        self._fallback = fallback or RuleRouter()

    def route(self, question: str) -> Route:
        try:
            out = self._llm.complete_json(
                self._ctx,
                _RouteOut,
                step="route",
                prompt_version=ROUTER_PROMPT_VERSION,
                messages=[Message("system", ROUTER_SYSTEM), Message("user", question[:2000])],
                max_tokens=40,
            )
            return out.route
        except StructuredOutputError:
            return self._fallback.route(question)
