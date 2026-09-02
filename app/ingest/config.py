"""Configuration for ingest service."""

from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass


@dataclass
class Config:
    redis_url: str
    db_path: Path
    data_dir: Path
    jobs_dir: Path
    whisper_model: str
    whisper_compute_type: str
    keep_media: bool
    cookies_file: str
    extractor_args: str
    enable_js_runtimes: bool
    google_api_key: str
    llm_model: str
    worker_concurrency: int = 2
    port: int = 8001

    def job_dir(self, job_id: str) -> Path:
        return self.jobs_dir / job_id


def load() -> Config:
    data_dir = Path(os.environ.get("DATA_DIR", "/data"))
    return Config(
        redis_url=os.environ.get("REDIS_URL", "redis://redis:6379/0"),
        db_path=data_dir / "vs.db",
        data_dir=data_dir,
        jobs_dir=data_dir / "jobs",
        whisper_model=os.environ.get("WHISPER_MODEL", "base"),
        whisper_compute_type=os.environ.get("WHISPER_COMPUTE_TYPE", "int8"),
        keep_media=os.environ.get("KEEP_MEDIA", "1") == "1",
        cookies_file=os.environ.get("COOKIES_FILE", ""),
        extractor_args=os.environ.get("EXTRACTOR_ARGS", ""),
        enable_js_runtimes=os.environ.get("ENABLE_JS_RUNTIMES", "0") == "1",
        google_api_key=os.environ.get("GOOGLE_API_KEY", ""),
        llm_model=os.environ.get("LLM_MODEL", "gemini-2.5-flash"),
        worker_concurrency=max(1, int(os.environ.get("WORKER_CONCURRENCY", "2") or "2")),
    )


cfg = load()