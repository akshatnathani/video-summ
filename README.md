# Video Summarizer — Standalone App

Download best-quality video/audio, extract transcripts (captions → whisper fallback), and get ELI5 summaries.

## Features

- **Best quality downloads**: Video+audio, video-only, audio-only
- **Playlists**: paste a YouTube playlist link, pick which videos you want from a
  thumbnail list, and download/transcribe/summarize them together
- **Parallel processing**: multiple ingest workers pull jobs off the same queue
  (`WORKER_CONCURRENCY`), so a batch from a playlist runs concurrently instead
  of one video at a time
- **Smart transcripts**: YouTube captions first (instant), faster-whisper fallback (local, fast)
- **ELI5 summaries**: LLM-powered "explain like I'm 5" + detailed summaries
- **Fast & optimized**: Parallel downloads, caption prioritization, int8 whisper
- **Clean UI**: Paper-and-ink design (like Verve) with light/dark themes — a journal-style
  library of jobs, a live pipeline rail, and translatable transcript/summary views

## Quick Start

```bash
# 1. Configure
cp .env.example .env
# Add GOOGLE_API_KEY (get from https://aistudio.google.com/apikey)

# 2. Run
docker compose up --build

# 3. Open http://localhost:5173
```

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Frontend   │────▶│   Gateway   │────▶│  Ingest     │
│  (React)    │     │  (FastAPI)  │     │  (FastAPI)  │
└─────────────┘     └──────┬──────┘     └──────┬──────┘
                           │                   │
                    ┌──────▼──────┐     ┌──────▼──────┐
                    │   Redis     │     │  Whisper    │
                    │  (queue)    │     │  (local)    │
                    └─────────────┘     └─────────────┘
```

## API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/preview` | Look up title/duration/thumbnail for a URL — no download |
| `POST` | `/api/playlist/preview` | List a playlist's videos — no download |
| `POST` | `/api/jobs` | Create one job (URL + download options) |
| `POST` | `/api/jobs/batch` | Create jobs for several URLs at once (up to 25), e.g. a playlist selection |
| `GET` | `/api/jobs/{id}` | Job status + results |
| `GET` | `/api/jobs/{id}/events` | SSE live updates |
| `GET` | `/api/jobs/{id}/download/{type}` | Download file (video/audio/merged) |
| `POST` | `/api/jobs/{id}/summarize` | Generate ELI5 + detailed summary |

## Download Options

```json
{
  "url": "https://youtube.com/watch?v=...",
  "download_type": "merged",    // "merged" | "video_only" | "audio_only"
  "quality": "best",            // "best" | "1080p" | "720p" | "480p"
  "extract_transcript": true,
  "summarize": true
}
```