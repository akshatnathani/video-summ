"""Redis queue and pub/sub for job processing."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Optional


QUEUE_INGEST = "vs:queue:ingest"


def redis_url_from_env() -> str:
    return os.environ.get("REDIS_URL", "redis://redis:6379/0")


def new_client(redis_url: str, async_mode: bool = False):
    if async_mode:
        from redis.asyncio import Redis
        return Redis.from_url(redis_url, decode_responses=True)
    import redis
    return redis.Redis.from_url(redis_url, decode_responses=True)


def channel_for(job_id: str) -> str:
    """Each job gets its own pub/sub channel, so an SSE stream only ever receives
    events for the one job it's watching instead of every job in the system."""
    return f"vs:events:{job_id}"


def _build_payload(
    job_id: str,
    event_type: str,
    stage: Optional[str] = None,
    progress: Optional[float] = None,
    message: Optional[str] = None,
    data: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "type": event_type,
        "stage": stage,
        "progress": progress,
        "message": message,
        "data": data or {},
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def publish(
    client: Any,
    job_id: str,
    event_type: str,
    stage: Optional[str] = None,
    progress: Optional[float] = None,
    message: Optional[str] = None,
    data: Optional[dict[str, Any]] = None,
) -> None:
    payload = _build_payload(job_id, event_type, stage, progress, message, data)
    try:
        client.publish(channel_for(job_id), json.dumps(payload))
    except Exception:
        pass


async def publish_async(
    client: Any,
    job_id: str,
    event_type: str,
    stage: Optional[str] = None,
    progress: Optional[float] = None,
    message: Optional[str] = None,
    data: Optional[dict[str, Any]] = None,
) -> None:
    payload = _build_payload(job_id, event_type, stage, progress, message, data)
    try:
        await client.publish(channel_for(job_id), json.dumps(payload))
    except Exception:
        pass


def enqueue(client: Any, queue: str, payload: dict[str, Any]) -> None:
    client.lpush(queue, json.dumps(payload))


async def enqueue_async(client: Any, queue: str, payload: dict[str, Any]) -> None:
    await client.lpush(queue, json.dumps(payload))


def dequeue_blocking(client: Any, queue: str, timeout_s: int) -> Optional[dict[str, Any]]:
    try:
        item = client.blpop(queue, timeout=timeout_s)
    except Exception:
        return None
    if item is None:
        return None
    _, raw = item
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None
