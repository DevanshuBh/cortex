"""Per-task event streams in Redis Streams (guide step 4.5, design §8.4).

Workers XADD to ``task:{id}:events`` (capped, with a TTL). The API reads with XREAD and sends each entry as an
SSE event whose ``id`` is the stream id, so a browser that reconnects with ``Last-Event-ID`` resumes exactly
where it stopped — unlike Pub/Sub, which drops whatever was published while nobody was listening.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any, cast

import redis
import redis.asyncio as aioredis

from cortex.config import get_settings

TERMINAL_EVENTS = frozenset({"done", "error", "cancelled"})
_STREAM_ID = re.compile(r"^\d+-\d+$")


def stream_key(task_id: str) -> str:
    return f"task:{task_id}:events"


@lru_cache
def _sync() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


class EventSink:
    """Worker side. Tokens are batched into one stream entry per flush to keep the stream small."""

    def __init__(self, task_id: str, client: redis.Redis | None = None) -> None:
        self.task_id = task_id
        self._r = client or _sync()
        self._key = stream_key(task_id)
        self._tokens: list[str] = []
        s = get_settings()
        self._maxlen, self._ttl = s.stream_maxlen, s.stream_ttl_seconds

    def emit(self, event: str, data: dict[str, Any]) -> str:
        self.flush()
        return self._add(event, data)

    def token(self, piece: str) -> None:
        self._tokens.append(piece)
        if sum(len(t) for t in self._tokens) >= 24:
            self.flush()

    def flush(self) -> None:
        if self._tokens:
            text, self._tokens = "".join(self._tokens), []
            self._add("token", {"text": text})

    def _add(self, event: str, data: dict[str, Any]) -> str:
        pipe = self._r.pipeline()
        pipe.xadd(
            self._key, {"event": event, "data": json.dumps(data)}, maxlen=self._maxlen, approximate=True
        )
        pipe.expire(self._key, self._ttl)
        entry_id, _ = pipe.execute()
        return str(entry_id)


@lru_cache
def _async_client() -> aioredis.Redis:
    return aioredis.Redis.from_url(get_settings().redis_url, decode_responses=True)


async def read_events(
    task_id: str,
    last_id: str | None,
    *,
    block_ms: int = 15000,
    client: aioredis.Redis | None = None,
) -> AsyncIterator[tuple[str, str, dict[str, Any]] | None]:
    """Yield (stream_id, event, data) after ``last_id``; yields None on each idle block (for SSE keep-alives).

    Stops after a terminal event. ``last_id`` that is not a stream id restarts from the beginning.
    """
    r = client or _async_client()
    key = stream_key(task_id)
    cursor = last_id if last_id and _STREAM_ID.match(last_id) else "0-0"
    while True:
        resp = cast(
            list[tuple[str, list[tuple[str, dict[str, str]]]]],
            await r.xread({key: cursor}, count=200, block=block_ms),
        )
        if not resp:
            yield None
            continue
        for _key, entries in resp:
            for entry_id, fields in entries:
                cursor = entry_id
                event = fields.get("event", "message")
                data = json.loads(fields.get("data", "{}"))
                yield entry_id, event, data
                if event in TERMINAL_EVENTS:
                    return
