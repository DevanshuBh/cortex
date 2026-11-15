"""Resumable streaming: Redis Streams + Last-Event-ID lose nothing on reconnect; Pub/Sub would (guide step 4.5)."""

from __future__ import annotations

import asyncio
import uuid

import pytest
import redis
import redis.asyncio as aioredis

from cortex.streaming import EventSink, read_events

pytestmark = pytest.mark.integration


async def _collect(
    url: str, task_id: str, last_id: str | None, stop_after: int | None = None
) -> list[tuple[str, str]]:
    client = aioredis.Redis.from_url(url, decode_responses=True)
    out: list[tuple[str, str]] = []
    async for item in read_events(task_id, last_id, block_ms=200, client=client):
        if item is None:
            break
        entry_id, event, _data = item
        out.append((entry_id, event))
        if stop_after is not None and len(out) >= stop_after:
            break
    await client.aclose()
    return out


def test_reconnect_with_last_event_id_resumes_without_gaps(redis_url: str) -> None:
    task_id = str(uuid.uuid4())
    sink = EventSink(task_id, redis.Redis.from_url(redis_url, decode_responses=True))
    for i in range(5):
        sink.emit("step", {"i": i})
    first = asyncio.run(_collect(redis_url, task_id, None, stop_after=2))  # browser drops after 2 events
    for i in range(5, 8):  # tokens keep coming while the browser is away
        sink.emit("step", {"i": i})
    sink.emit("done", {})
    rest = asyncio.run(_collect(redis_url, task_id, first[-1][0]))
    events = [e for _, e in first + rest]
    assert events == ["step"] * 8 + ["done"]
    ids = [i for i, _ in first + rest]
    assert ids == sorted(ids, key=lambda x: tuple(int(p) for p in x.split("-")))
    assert len(set(ids)) == len(ids)


def test_tokens_are_batched_and_flushed_in_order(redis_url: str) -> None:
    task_id = str(uuid.uuid4())
    sink = EventSink(task_id, redis.Redis.from_url(redis_url, decode_responses=True))
    for word in [
        "A",
        "Pod",
        "runs",
        "one",
        "or",
        "more",
        "containers",
        "that",
        "share",
        "storage",
        "and",
        "network",
    ]:
        sink.token(word + " ")
    sink.emit("done", {})  # emit flushes pending tokens first
    client = redis.Redis.from_url(redis_url, decode_responses=True)
    entries = client.xrange(f"task:{task_id}:events")
    import json

    text = "".join(json.loads(f["data"])["text"] for _, f in entries if f["event"] == "token")
    assert text == "A Pod runs one or more containers that share storage and network "
    assert entries[-1][1]["event"] == "done"
    assert client.ttl(f"task:{task_id}:events") > 0


def test_pubsub_would_have_lost_the_events_sent_while_disconnected(redis_url: str) -> None:
    """The counterexample the first edition shipped: Pub/Sub drops messages for absent subscribers."""
    r = redis.Redis.from_url(redis_url, decode_responses=True)
    channel = f"demo:{uuid.uuid4()}"
    r.publish(channel, "token while nobody listens")
    sub = r.pubsub()
    sub.subscribe(channel)
    sub.get_message(timeout=1)  # subscription confirmation
    assert sub.get_message(timeout=0.5) is None, "the earlier message is gone for good"
    sub.close()
