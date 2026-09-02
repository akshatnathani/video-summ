"""Main ingest service: download → transcript → summarize."""

from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from shared import bus
from shared.db import JobStore
from shared.obs import get_logger, setup
from shared.urlcheck import is_allowed_video_url, is_playlist_url

from .config import cfg
from .downloader import MediaDownloader, detect_platform
from .captions import fetch_from_tracks
from .transcriber import transcribe
from shared.summarizer import Summarizer

log = get_logger(__name__)

MAX_PLAYLIST_ENTRIES = 200


class CreateJobBody(BaseModel):
    url: str
    download_type: str = "merged"   # merged | video_only | audio_only
    quality: str = "best"           # best | 1080p | 720p | 480p
    extract_transcript: bool = True
    summarize: bool = True


class PreviewBody(BaseModel):
    url: str


def worker_loop() -> None:
    redis = bus.new_client(cfg.redis_url)
    store = JobStore(cfg.db_path)
    summarizer = Summarizer(cfg.google_api_key, cfg.llm_model) if cfg.google_api_key else None

    while True:
        item = bus.dequeue_blocking(redis, bus.QUEUE_INGEST, timeout_s=5)
        if item is None:
            continue

        job_id = item.get("job_id")
        url = item.get("url")
        download_type = item.get("download_type", "merged")
        quality = item.get("quality", "best")
        extract_transcript = item.get("extract_transcript", True)
        do_summarize = item.get("summarize", True)
        notebook_id = item.get("notebook_id")

        if not job_id or not url:
            continue

        try:
            process_job(
                store, redis, summarizer, job_id, url,
                download_type, quality, extract_transcript, do_summarize, notebook_id
            )
        except Exception as e:
            log.exception("ingest failed", extra={"kv": {"job_id": job_id, "url": url}})
            try:
                store.update(job_id, status="failed", error=str(e)[:500])
                bus.publish(redis, job_id, "job.failed", message=str(e)[:300])
            except Exception:
                log.exception("could not record ingest failure")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Multiple workers pull from the same Redis queue (BLPOP hands each item to
    # exactly one popper), so this is what actually lets several jobs — e.g. a
    # batch of videos picked from a playlist — download/transcribe/summarize at
    # once instead of one at a time. Whisper inference is still serialized
    # (see transcriber.py) since a single CTranslate2 model isn't safe for
    # concurrent calls from multiple threads.
    n = max(1, cfg.worker_concurrency)
    for i in range(n):
        threading.Thread(target=worker_loop, name=f"ingest-worker-{i}", daemon=True).start()
    log.info(f"started {n} ingest worker(s)")
    yield


app = FastAPI(title="Video Summarizer Ingest", version="1.0.0", lifespan=lifespan)
setup("ingest", app)

store = JobStore(cfg.db_path)
redis = bus.new_client(cfg.redis_url)


@app.get("/health")
async def health() -> dict:
    return {"status": "healthy", "service": "ingest"}


@app.post("/preview")
async def preview(body: PreviewBody) -> dict:
    """Metadata-only lookup — no download, so it's fast enough to run as the user types a URL."""
    if not is_allowed_video_url(body.url):
        raise HTTPException(422, "URL must be an https:// YouTube or Instagram link.")

    downloader = MediaDownloader("/tmp/vs-preview", cfg.cookies_file, cfg.extractor_args, cfg.enable_js_runtimes)
    try:
        info = await asyncio.to_thread(downloader.get_info, body.url)
    except Exception as e:
        raise HTTPException(422, f"Could not look up this video: {str(e)[:200]}")

    return {
        "platform": info.get("platform"),
        "title": info.get("title"),
        "uploader": info.get("uploader"),
        "duration": info.get("duration"),
        "view_count": info.get("view_count"),
        "upload_date": info.get("upload_date"),
        "thumbnail": info.get("thumbnail"),
        "captions_available": bool(info.get("captions_available")),
    }


@app.post("/playlist/preview")
async def playlist_preview(body: PreviewBody) -> dict:
    """List a playlist's videos (flat — no per-video page hits) so the UI can
    offer a pick list before anything downloads."""
    if not is_allowed_video_url(body.url):
        raise HTTPException(422, "URL must be an https:// YouTube link.")
    if not is_playlist_url(body.url):
        raise HTTPException(422, "That doesn't look like a playlist URL.")

    downloader = MediaDownloader("/tmp/vs-preview", cfg.cookies_file, cfg.extractor_args, cfg.enable_js_runtimes)
    try:
        info = await asyncio.to_thread(downloader.get_playlist_info, body.url, MAX_PLAYLIST_ENTRIES)
    except Exception as e:
        raise HTTPException(422, f"Could not read this playlist: {str(e)[:200]}")

    if not info["entries"]:
        raise HTTPException(422, "This playlist has no videos (or they're all private/unavailable).")
    return info


def emit(job_id: str, event_type: str, **kw) -> None:
    bus.publish(redis, job_id, event_type, **kw)


def set_stage(job_id: str, stage: str, progress: float, message: str) -> None:
    store.update(job_id, status="running", stage=stage, progress=progress)
    emit(job_id, "stage.started", stage=stage, progress=progress, message=message)


def cancelled(job_id: str) -> bool:
    try:
        return redis.get(f"vs:job:{job_id}:cancel") == "1" or store.get(job_id) is None
    except Exception:
        return False


def process_job(
    store: JobStore,
    redis: Any,
    summarizer: Optional[Summarizer],
    job_id: str,
    url: str,
    download_type: str,
    quality: str,
    extract_transcript: bool,
    do_summarize: bool,
    notebook_id: Optional[str] = None,
) -> None:
    job_dir = Path(cfg.job_dir(job_id))
    job_dir.mkdir(parents=True, exist_ok=True)

    if cancelled(job_id):
        return

    if not is_allowed_video_url(url):
        store.update(job_id, status="failed", error="URL is not an allowed YouTube/Instagram link.")
        emit(job_id, "job.failed", message="URL is not an allowed YouTube/Instagram link.")
        return

    # Stage 1: Get info
    set_stage(job_id, "info", 0.05, "Fetching video info...")

    downloader = MediaDownloader(
        job_dir / "media", cfg.cookies_file, cfg.extractor_args, cfg.enable_js_runtimes
    )
    source = downloader.get_info(url)

    store.update(job_id, platform=source["platform"], title=source["title"], duration=source["duration"], uploader=source["uploader"])
    emit(job_id, "log", message=f'Found: "{source["title"][:80]}" by {source["uploader"]}')

    # Stage 2: Download
    set_stage(job_id, "downloading", 0.1, f"Downloading {download_type} ({quality})...")

    media_path: Optional[Path] = None
    try:
        media_path = downloader.download(url, download_type, quality)
        store.update_extra(job_id, media_path=str(media_path))
        size = media_path.stat().st_size if media_path.exists() else 0
        store.save_download(job_id, download_type, str(media_path), size)
        emit(job_id, "log", message=f"Downloaded {size/1024/1024:.1f} MB")
    except Exception as e:
        emit(job_id, "log", message=f"Download failed: {e}")
        # Continue anyway for transcript/summary if possible

    transcript = None
    if extract_transcript:
        # Stage 3a: Try platform captions
        if source.get("captions_available"):
            set_stage(job_id, "transcript", 0.4, "Fetching platform captions...")
            transcript = fetch_from_tracks(
                source["captions_available"],
                source.get("language"),
                float(source.get("duration") or 0),
            )
            if transcript:
                emit(job_id, "log", message=f'Using {transcript["language"]} platform captions (instant)')

        # Stage 3b: Fallback to Whisper
        if transcript is None:
            set_stage(job_id, "transcript", 0.5, "No captions — running faster-whisper...")
            try:
                # merged/audio_only downloads already have an audio track on disk —
                # faster-whisper decodes audio out of any container via ffmpeg, so
                # there's no need to fetch a second, whisper-only audio stream.
                # video_only has no audio track, so that one still needs a fetch.
                reusable = (
                    media_path is not None
                    and download_type in ("merged", "audio_only")
                    and media_path.exists()
                )
                if reusable:
                    audio_path = media_path
                    emit(job_id, "log", message="Reusing downloaded media for transcription.")
                else:
                    audio_path = downloader.download_audio_for_whisper(url)
                transcript = transcribe(
                    audio_path,
                    cfg.whisper_model,
                    cfg.whisper_compute_type,
                    source.get("language"),
                )
                emit(job_id, "log", message=f'Transcribed via faster-whisper ({transcript["language"]})')
                if not cfg.keep_media and audio_path != media_path:
                    try:
                        audio_path.unlink()
                    except Exception:
                        pass
            except Exception as e:
                emit(job_id, "log", message=f"Transcription failed: {e}")

        if transcript:
            store.save_transcript(
                job_id,
                transcript["language"],
                transcript["source"],
                transcript["text"],
                transcript["segments"],
            )
            emit(job_id, "artifact.ready", data={"name": "transcript"})

    # Stage 4: Summarize
    if do_summarize and transcript and summarizer:
        set_stage(job_id, "summarize", 0.8, "Generating ELI5 + detailed summary...")
        try:
            summary = summarizer.summarize(
                transcript["text"],
                transcript["segments"],
                source.get("title", ""),
                transcript.get("duration", 0),
            )
            store.save_summary(
                job_id,
                summary["eli5"],
                summary["detailed"],
                summary["key_points"],
            )
            emit(job_id, "artifact.ready", data={"name": "summary"})
        except Exception as e:
            emit(job_id, "log", message=f"Summarization failed: {e}")

    # Complete
    store.update(job_id, status="ready", stage="ready", progress=1.0)
    emit(job_id, "job.ready", progress=1.0, message="Job complete")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=cfg.port)