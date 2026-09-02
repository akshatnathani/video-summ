FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    nodejs \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    redis \
    pydantic \
    yt-dlp \
    yt-dlp-ejs \
    google-genai \
    && pip install --no-cache-dir faster-whisper

COPY app/shared /app/shared
COPY app/ingest /app/ingest

ENV PYTHONPATH=/app

EXPOSE 8001
CMD ["uvicorn", "ingest.main:app", "--host", "0.0.0.0", "--port", "8001"]