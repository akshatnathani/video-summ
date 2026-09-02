"""Configuration for gateway service."""

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
    ingest_url: str
    google_api_key: str
    llm_model: str
    cors_origins: list[str]
    port: int = 8000

    def job_dir(self, job_id: str) -> Path:
        return self.jobs_dir / job_id


def load() -> Config:
    data_dir = Path(os.environ.get("DATA_DIR", "/data"))
    cors = os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    return Config(
        redis_url=os.environ.get("REDIS_URL", "redis://redis:6379/0"),
        db_path=data_dir / "vs.db",
        data_dir=data_dir,
        jobs_dir=data_dir / "jobs",
        ingest_url=os.environ.get("INGEST_URL", "http://ingest:8001"),
        google_api_key=os.environ.get("GOOGLE_API_KEY", ""),
        llm_model=os.environ.get("LLM_MODEL", "gemini-2.5-flash"),
        cors_origins=[o.strip() for o in cors.split(",")],
    )


cfg = load()