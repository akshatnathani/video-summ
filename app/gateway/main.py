"""Gateway API: job management, SSE, downloads, summarization."""

from __future__ import annotations

import asyncio
import json
import mimetypes
import uuid
from pathlib import Path
from typing import AsyncIterator, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from shared import bus
from shared.db import JobStore
from shared.obs import get_logger, setup
from shared.summarizer import Summarizer
from shared.urlcheck import is_allowed_video_url, is_playlist_url

from .config import cfg

log = get_logger(__name__)

app = FastAPI(title="Video Summarizer Gateway", version="1.0.0")
setup("gateway", app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)

store = JobStore(cfg.db_path)
redis = bus.new_client(cfg.redis_url, async_mode=True)
_http: Optional[httpx.AsyncClient] = None
_summarizer: Optional[Summarizer] = None


def http() -> httpx.AsyncClient:
    global _http
    if _http is None:
        _http = httpx.AsyncClient(timeout=httpx.Timeout(300.0))
    return _http


def summarizer() -> Summarizer:
    global _summarizer
    if _summarizer is None:
        _summarizer = Summarizer(cfg.google_api_key, cfg.llm_model)
    return _summarizer


# ── Rate limiting ────────────────────────────────────────────
# No auth on this API by design, but unlimited job creation / summarize calls
# means unlimited yt-dlp downloads, whisper transcriptions, and Gemini spend.
# Fixed-window counters in Redis, keyed by client IP, fail open if Redis hiccups.

async def rate_limit(request: Request, bucket: str, limit: int, window_s: int = 60, weight: int = 1) -> None:
    ip = request.client.host if request.client else "unknown"
    key = f"vs:ratelimit:{bucket}:{ip}"
    try:
        count = await redis.incrby(key, weight)
        if count == weight:  # first increment in this window — start the clock
            await redis.expire(key, window_s)
    except Exception:
        return
    if count > limit:
        raise HTTPException(429, f"Too many requests — max {limit} per {window_s}s. Try again shortly.")


MAX_BATCH_JOBS = 25


class CreateJobBody(BaseModel):
    url: str
    download_type: str = "merged"
    quality: str = "best"
    extract_transcript: bool = True
    summarize: bool = True


class CreateJobsBatchBody(BaseModel):
    urls: list[str]
    download_type: str = "merged"
    quality: str = "best"
    extract_transcript: bool = True
    summarize: bool = True


class SummarizeBody(BaseModel):
    force: bool = False


class PreviewBody(BaseModel):
    url: str


@app.get("/health")
async def health() -> dict:
    downstream = {}
    try:
        resp = await http().get(f"{cfg.ingest_url}/health", timeout=3.0)
        downstream["ingest"] = "up" if resp.status_code == 200 else f"http {resp.status_code}"
    except httpx.HTTPError:
        downstream["ingest"] = "down"
    return {"status": "healthy", "service": "gateway", "downstream": downstream}


@app.post("/api/preview")
async def preview(body: PreviewBody, request: Request) -> dict:
    """Metadata-only lookup (no download) so the UI can show title/duration/etc.
    as soon as a URL is pasted, before the user commits to a full job."""
    await rate_limit(request, "preview", limit=20, window_s=60)
    if not is_allowed_video_url(body.url):
        raise HTTPException(422, "URL must be an https:// YouTube or Instagram link.")
    try:
        resp = await http().post(f"{cfg.ingest_url}/preview", json={"url": body.url}, timeout=20.0)
    except httpx.HTTPError:
        raise HTTPException(502, "Could not reach the ingest service.")
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, resp.text)
    return resp.json()


@app.post("/api/playlist/preview")
async def playlist_preview(body: PreviewBody, request: Request) -> dict:
    """List a playlist's videos (no download) so the UI can offer a pick list."""
    await rate_limit(request, "playlist_preview", limit=6, window_s=60)
    if not is_allowed_video_url(body.url):
        raise HTTPException(422, "URL must be an https:// YouTube link.")
    if not is_playlist_url(body.url):
        raise HTTPException(422, "That doesn't look like a playlist URL.")
    try:
        resp = await http().post(f"{cfg.ingest_url}/playlist/preview", json={"url": body.url}, timeout=45.0)
    except httpx.HTTPError:
        raise HTTPException(502, "Could not reach the ingest service.")
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, resp.text)
    return resp.json()


async def _create_and_enqueue(
    url: str, download_type: str, quality: str, extract_transcript: bool, summarize: bool
) -> dict:
    job_id = uuid.uuid4().hex
    store.create(
        job_id, url,
        download_type=download_type,
        quality=quality,
        extract_transcript=extract_transcript,
        summarize=summarize,
    )
    await redis.set(f"vs:job:{job_id}:cancel", "0", ex=86400)
    await bus.enqueue_async(redis, bus.QUEUE_INGEST, {
        "job_id": job_id,
        "url": url,
        "download_type": download_type,
        "quality": quality,
        "extract_transcript": extract_transcript,
        "summarize": summarize,
    })
    await bus.publish_async(redis, job_id, "job.created", stage="queued", message="Job accepted")
    return store.get(job_id) or {}


@app.post("/api/jobs", status_code=201)
async def create_job(body: CreateJobBody, request: Request) -> dict:
    await rate_limit(request, "create_job", limit=30, window_s=60)
    if not is_allowed_video_url(body.url):
        raise HTTPException(422, "URL must be an https:// YouTube or Instagram link.")
    return await _create_and_enqueue(
        body.url, body.download_type, body.quality, body.extract_transcript, body.summarize
    )


@app.post("/api/jobs/batch", status_code=201)
async def create_jobs_batch(body: CreateJobsBatchBody, request: Request) -> dict:
    """Create many jobs at once — e.g. the videos picked from a playlist. They're
    enqueued together and processed by however many ingest workers are running
    (see WORKER_CONCURRENCY), so this is what makes them run in parallel rather
    than one at a time."""
    urls = list(dict.fromkeys(u.strip() for u in body.urls if u.strip()))
    if not urls:
        raise HTTPException(422, "No URLs provided.")
    if len(urls) > MAX_BATCH_JOBS:
        raise HTTPException(422, f"Too many videos at once — max {MAX_BATCH_JOBS} per batch.")

    await rate_limit(request, "create_job", limit=30, window_s=60, weight=len(urls))

    bad = [u for u in urls if not is_allowed_video_url(u)]
    if bad:
        raise HTTPException(422, f"{len(bad)} URL(s) are not allowed YouTube/Instagram links.")

    jobs = [
        await _create_and_enqueue(u, body.download_type, body.quality, body.extract_transcript, body.summarize)
        for u in urls
    ]
    return {"jobs": jobs}


@app.get("/api/jobs")
async def list_jobs(limit: int = 50, offset: int = 0) -> dict:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    return {"jobs": store.list(limit=limit, offset=offset), "total": store.count()}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    row = store.get(job_id)
    if not row:
        raise HTTPException(404, "Job not found.")
    row["transcript"] = store.get_transcript(job_id)
    row["summary"] = store.get_summary(job_id)
    row["downloads"] = store.get_downloads(job_id)
    return row


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str) -> dict:
    row = store.get(job_id)
    if not row:
        raise HTTPException(404, "Job not found.")
    await redis.set(f"vs:job:{job_id}:cancel", "1", ex=86400)
    # Clean up files
    job_dir = Path(cfg.data_dir) / "jobs" / job_id
    import shutil
    shutil.rmtree(job_dir, ignore_errors=True)
    # Remove the record (and transcripts/summaries/downloads) from the store
    store.delete(job_id)
    return {"deleted": True}


# ── Downloads ────────────────────────────────────────────────

@app.get("/api/jobs/{job_id}/download/{dtype}")
async def download_file(job_id: str, dtype: str, inline: bool = False):
    """Serve the media file: merged, video_only, audio_only.

    Defaults to a forced download (`Content-Disposition: attachment`); pass
    `?inline=1` to get a response a <video>/<audio> tag can play in place —
    that also requires a real media type, not a generic octet-stream, which
    is why we sniff it from the file extension either way.
    """
    row = store.get(job_id)
    if not row:
        raise HTTPException(404, "Job not found.")
    if row["status"] != "ready":
        raise HTTPException(409, "Job not complete yet.")

    downloads = store.get_downloads(job_id)
    dl = next((d for d in downloads if d["type"] == dtype), None)
    if not dl:
        raise HTTPException(404, f"Download type '{dtype}' not found.")

    path = Path(dl["path"])
    if not path.is_file():
        raise HTTPException(404, "File not found on disk.")

    media_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    filename = f"{job_id[:8]}_{dtype}{path.suffix}"
    response = FileResponse(path, media_type=media_type, filename=filename)
    if inline:
        response.headers["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


# ── Summarization ──────────────────────────────────────────

@app.post("/api/jobs/{job_id}/summarize")
async def generate_summary(job_id: str, body: SummarizeBody, request: Request):
    await rate_limit(request, "summarize", limit=15, window_s=60)

    row = store.get(job_id)
    if not row:
        raise HTTPException(404, "Job not found.")

    transcript = store.get_transcript(job_id)
    if not transcript:
        raise HTTPException(409, "No transcript available. Run with extract_transcript=true first.")

    existing = store.get_summary(job_id)
    if existing and not body.force:
        return existing

    result = await summarizer().summarize_async(
        transcript["text"],
        transcript["segments"],
        row.get("title", ""),
        transcript.get("duration", 0),
    )
    store.save_summary(job_id, result["eli5"], result["detailed"], result["key_points"])
    await bus.publish_async(redis, job_id, "artifact.ready", data={"name": "summary"})

    return store.get_summary(job_id)


# ── SSE ────────────────────────────────────────────────────

@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str) -> StreamingResponse:
    row = await asyncio.to_thread(store.get, job_id)
    if not row:
        raise HTTPException(404, "Job not found.")

    async def stream() -> AsyncIterator[bytes]:
        pubsub = redis.pubsub()
        await pubsub.subscribe(bus.channel_for(job_id))
        try:
            # Send snapshot
            snapshot = {"type": "snapshot", "job_id": job_id, "job": row, "ts": ""}
            yield f"data: {json.dumps(snapshot)}\n\n".encode()

            while True:
                if await asyncio.to_thread(store.get, job_id) is None:
                    break
                try:
                    msg = await asyncio.wait_for(
                        pubsub.get_message(ignore_subscribe_messages=True), timeout=15.0
                    )
                except asyncio.TimeoutError:
                    yield b": ping\n\n"
                    continue
                if msg is None:
                    continue
                try:
                    event = json.loads(msg["data"])
                except Exception:
                    continue
                yield f"data: {json.dumps(event)}\n\n".encode()
                if event.get("type") in ("job.ready", "job.failed"):
                    break
        finally:
            await pubsub.close()

    return StreamingResponse(
        stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=cfg.port)