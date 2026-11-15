"""API flow against real Postgres and Redis: uploads, tenant isolation over HTTP, idempotent ask, SSE resume.

Celery and object storage are replaced by in-memory fakes; tokens are signed by a test key.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator
from typing import Any

import jwt
import pytest
import redis
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from cortex.config import get_settings

pytestmark = pytest.mark.integration

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _Jwks:
    def get_signing_key_from_jwt(self, _token: str) -> Any:
        return jwt.PyJWK.from_dict(
            {
                **jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key(), as_dict=True),
                "alg": "RS256",
                "kid": "k1",
            }
        )


def bearer(tenant: str, roles: tuple[str, ...] = ("member",), sub: str = "u1") -> dict[str, str]:
    s = get_settings()
    now = int(time.time())
    tok = jwt.encode(
        {
            "sub": sub,
            "iss": s.oidc_issuer,
            "aud": s.oidc_audience,
            "iat": now,
            "exp": now + 300,
            "tenant_id": tenant,
            "realm_access": {"roles": list(roles)},
        },
        KEY,
        algorithm="RS256",
        headers={"kid": "k1"},
    )
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def client(
    pg: dict[str, str], redis_url: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, dict[str, Any]]]:
    from cortex import storage
    from cortex.api import auth
    from cortex.worker import tasks

    monkeypatch.setattr(auth, "_jwks_client", lambda _url: _Jwks())
    objects: dict[str, bytes] = {}
    queued: dict[str, list[tuple[Any, ...]]] = {"ingest": [], "ask": [], "delete": []}
    monkeypatch.setattr(storage, "put_bytes", lambda k, d, _m: objects.__setitem__(k, d))
    monkeypatch.setattr(storage, "head", lambda k: len(objects[k]) if k in objects else None)
    monkeypatch.setattr(storage, "presign_put", lambda k, _m, _e=900: f"http://s3.test/{k}")
    monkeypatch.setattr(tasks.ingest_task, "delay", lambda *a: queued["ingest"].append(a))
    monkeypatch.setattr(tasks.ask_task, "delay", lambda *a: queued["ask"].append(a))
    monkeypatch.setattr(tasks.delete_document_task, "delay", lambda *a: queued["delete"].append(a))
    from cortex.api.main import app

    return TestClient(app), {"objects": objects, "queued": queued}


def test_upload_lists_only_in_own_tenant(
    client: tuple[TestClient, dict[str, Any]], tenant: str, other_tenant: str
) -> None:
    c, state = client
    r = c.post(
        "/v1/documents/upload",
        headers=bearer(tenant),
        files={"file": ("runbook.md", b"# Runbook\n\nRestart the API.", "text/markdown")},
    )
    assert r.status_code == 202, r.text
    doc_id = r.json()["document_id"]
    assert (
        state["queued"]["ingest"][-1][0] == tenant
    )  # the worker gets the tenant from the token, not the client
    assert c.get("/v1/documents", headers=bearer(tenant)).json()["total"] == 1
    # another tenant sees nothing and gets 404 (not 403) for the id: existence is not revealed
    assert c.get("/v1/documents", headers=bearer(other_tenant)).json()["total"] == 0
    assert c.get(f"/v1/documents/{doc_id}", headers=bearer(other_tenant)).status_code == 404
    assert c.get(f"/v1/documents/{doc_id}/file", headers=bearer(other_tenant)).status_code == 404


def test_unsupported_and_oversized_uploads_are_rejected(
    client: tuple[TestClient, dict[str, Any]], tenant: str
) -> None:
    c, _ = client
    r = c.post(
        "/v1/documents/upload",
        headers=bearer(tenant),
        files={"file": ("x.exe", b"MZ", "application/octet-stream")},
    )
    assert r.status_code == 415
    assert r.headers["content-type"].startswith("application/problem+json")
    r = c.post(
        "/v1/documents",
        headers=bearer(tenant),
        json={"filename": "big.pdf", "content_type": "application/pdf", "size_bytes": 999_999_999},
    )
    assert r.status_code == 413


def test_presigned_upload_flow(client: tuple[TestClient, dict[str, Any]], tenant: str) -> None:
    c, state = client
    r = c.post(
        "/v1/documents",
        headers=bearer(tenant),
        json={"filename": "notes.md", "content_type": "text/markdown", "size_bytes": 10},
    )
    assert r.status_code == 201
    doc = r.json()
    assert (
        c.post(f"/v1/documents/{doc['document_id']}/complete", headers=bearer(tenant)).status_code == 409
    )  # not uploaded yet
    key = doc["upload_url"].removeprefix("http://s3.test/")
    state["objects"][key] = b"# Notes\n\nhello"
    first = c.post(f"/v1/documents/{doc['document_id']}/complete", headers=bearer(tenant)).json()
    again = c.post(f"/v1/documents/{doc['document_id']}/complete", headers=bearer(tenant)).json()
    assert first["task_id"] == again["task_id"]  # completing twice queues ingestion once
    assert len([q for q in state["queued"]["ingest"] if q[2] == doc["document_id"]]) == 1


def test_ask_is_idempotent_with_a_key(client: tuple[TestClient, dict[str, Any]], tenant: str) -> None:
    c, state = client
    h = {**bearer(tenant), "Idempotency-Key": f"retry-{uuid.uuid4().hex}"}
    a = c.post("/v1/ask", headers=h, json={"question": "What is a Pod?"}).json()
    b = c.post("/v1/ask", headers=h, json={"question": "What is a Pod?"}).json()
    assert a["task_id"] == b["task_id"]
    assert a["created"]
    assert not b["created"]
    assert len([q for q in state["queued"]["ask"] if q[1] == a["task_id"]]) == 1
    assert (
        c.post(
            "/v1/ask", headers={**bearer(tenant), "Idempotency-Key": "bad key!"}, json={"question": "x?x"}
        ).status_code
        == 400
    )


def test_delete_requires_admin(client: tuple[TestClient, dict[str, Any]], tenant: str) -> None:
    c, _ = client
    doc = c.post(
        "/v1/documents/upload",
        headers=bearer(tenant),
        files={"file": ("a.md", b"# A\n\ntext", "text/markdown")},
    ).json()
    assert (
        c.delete(f"/v1/documents/{doc['document_id']}", headers=bearer(tenant, ("member",))).status_code
        == 403
    )
    assert (
        c.delete(f"/v1/documents/{doc['document_id']}", headers=bearer(tenant, ("admin",))).status_code == 202
    )


def test_task_events_resume_from_last_event_id(
    client: tuple[TestClient, dict[str, Any]], tenant: str, other_tenant: str, redis_url: str
) -> None:
    from cortex.streaming import EventSink

    c, _ = client
    task_id = c.post("/v1/ask", headers=bearer(tenant), json={"question": "What is a Pod?"}).json()["task_id"]
    sink = EventSink(task_id, redis.Redis.from_url(redis_url, decode_responses=True))
    first_id = sink.emit("step", {"i": 1})
    sink.emit("step", {"i": 2})
    sink.emit("done", {})
    with c.stream(
        "GET", f"/v1/tasks/{task_id}/events", headers={**bearer(tenant), "Last-Event-ID": first_id}
    ) as r:
        body = "".join(r.iter_text())
    events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]
    assert events == [{"i": 2}, {}], "resumed after the first event, nothing lost or repeated"
    assert c.get(f"/v1/tasks/{task_id}/events", headers=bearer(other_tenant)).status_code == 404
