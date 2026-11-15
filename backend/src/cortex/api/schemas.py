"""Request and response models. They define the OpenAPI spec the front end generates its types from."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

DocumentStatus = Literal[
    "pending_upload", "uploaded", "parsing", "embedding", "extracting", "ready", "failed"
]
TaskStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class Problem(BaseModel):
    """RFC 9457 problem details."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None


class Me(BaseModel):
    user_id: str
    tenant_id: str
    roles: list[str]


class CreateDocumentRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=100)
    size_bytes: int = Field(gt=0)
    title: str | None = Field(default=None, max_length=300)


class CreateDocumentResponse(BaseModel):
    document_id: str
    upload_url: str
    upload_headers: dict[str, str]
    expires_in: int


class TaskAccepted(BaseModel):
    task_id: str
    status: TaskStatus = "queued"
    created: bool = True


class UploadAccepted(TaskAccepted):
    document_id: str


class Document(BaseModel):
    id: str
    title: str
    filename: str
    mime: str
    size_bytes: int | None
    status: DocumentStatus
    error: str | None
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class DocumentPage(BaseModel):
    items: list[Document]
    total: int
    limit: int
    offset: int


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    router: Literal["llm", "rules"] = "llm"


class EvidenceItem(BaseModel):
    n: int
    chunk_id: str
    document_id: str
    title: str
    heading: str
    text: str
    source: str


class GraphPathOut(BaseModel):
    text: str
    nodes: list[str]
    relations: list[str]
    chunk_ids: list[str]


class Answer(BaseModel):
    question: str
    answer: str
    evidence: list[EvidenceItem]
    graph_paths: list[GraphPathOut]
    route: str
    partial: bool
    not_found: bool
    steps: int
    input_tokens: int
    output_tokens: int
    cost_usd: float = Field(
        description="Notional cost at reference list prices; real spend on local models is zero"
    )
    latency_ms: int
    trace: list[dict[str, Any]]
    created_at: datetime


class Task(BaseModel):
    id: str
    kind: str
    status: TaskStatus
    input: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    attempts: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    answer: Answer | None = None


class FeedbackRequest(BaseModel):
    rating: Literal[-1, 1]
    comment: str | None = Field(default=None, max_length=2000)


class ChunkOut(BaseModel):
    id: str
    document_id: str
    document_title: str
    position: int
    heading_path: str
    text: str
    char_start: int
    char_end: int
    filename: str
    mime: str
    page: int | None = None


class UsageTier(BaseModel):
    tier: str
    provider: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    errors: int


class UsageDay(BaseModel):
    day: str
    answers: int
    avg_cost_usd: float
    avg_latency_ms: float
    not_found: int
    partial: int


class UsageRoute(BaseModel):
    route: str
    answers: int
    avg_cost_usd: float


class FeedbackDay(BaseModel):
    day: str
    up: int
    down: int


class Usage(BaseModel):
    by_tier: list[UsageTier]
    daily: list[UsageDay]
    routes: list[UsageRoute]
    feedback: list[FeedbackDay]
    cost_note: str = "Costs are notional, at reference list prices; local models cost nothing to run."


class EvalRun(BaseModel):
    id: int
    created_at: datetime
    name: str
    git_commit: str | None
    config: dict[str, Any]
    metrics: dict[str, Any]


class GraphStats(BaseModel):
    entities: int
    relations: int
    chunks: int
