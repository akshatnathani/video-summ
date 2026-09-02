"""Structured logging setup."""

from __future__ import annotations

import contextvars
import logging
import sys
from contextlib import contextmanager
from typing import Any, Optional

_job_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("job_id", default=None)
_notebook_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("notebook_id", default=None)


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        job_id = _job_id_var.get()
        notebook_id = _notebook_id_var.get()
        if job_id:
            record.job_id = job_id
        if notebook_id:
            record.notebook_id = notebook_id
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        import json
        base = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "service": getattr(record, "service", "unknown"),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if hasattr(record, "job_id"):
            base["job_id"] = record.job_id
        if hasattr(record, "notebook_id"):
            base["notebook_id"] = record.notebook_id
        if hasattr(record, "kv"):
            base.update(record.kv)
        return json.dumps(base, ensure_ascii=False)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def setup(service: str, app: Any = None) -> None:
    level = logging.INFO
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    handler = logging.StreamHandler(sys.stdout)
    if sys.stdout.isatty():
        handler.setFormatter(fmt)
    else:
        handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [handler]
    root.addFilter(ContextFilter())

    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("httpx").setLevel(logging.WARNING)


@contextmanager
def bind(job_id: str = None, notebook_id: str = None):
    tokens = []
    if job_id:
        tokens.append(_job_id_var.set(job_id))
    if notebook_id:
        tokens.append(_notebook_id_var.set(notebook_id))
    try:
        yield
    finally:
        for tok in tokens:
            if job_id:
                _job_id_var.reset(tok)
            if notebook_id:
                _notebook_id_var.reset(tok)