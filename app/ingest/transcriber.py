"""Local ASR using faster-whisper (CTranslate2)."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

_model_cache: dict[str, Any] = {}
_model_lock = threading.Lock()
# A single CTranslate2 model instance isn't safe for concurrent inference from
# multiple threads. With several ingest workers now running in parallel (e.g.
# processing a batch of playlist videos at once), transcription must be
# serialized even though downloads/captions/summarization run concurrently.
_transcribe_lock = threading.Lock()


def get_transcriber(model_name: str, compute_type: str = "int8"):
    """Get or create a faster-whisper model (thread-safe, cached)."""
    global _model_cache
    cache_key = f"{model_name}:{compute_type}"
    if cache_key in _model_cache:
        return _model_cache[cache_key]

    with _model_lock:
        if cache_key in _model_cache:
            return _model_cache[cache_key]

        from faster_whisper import WhisperModel

        model = WhisperModel(
            model_name,
            device="cpu",
            compute_type=compute_type,
            cpu_threads=4,
            num_workers=1,
        )
        _model_cache[cache_key] = model
        return model


def transcribe(
    audio_path: str | Path,
    model_name: str = "base",
    compute_type: str = "int8",
    language: str | None = None,
) -> dict:
    """Transcribe audio file to timestamped segments."""
    model = get_transcriber(model_name, compute_type)

    # `segments` is a lazy generator — the actual CTranslate2 inference happens
    # while iterating it, so the lock has to wrap that loop too, not just the
    # call that creates the generator.
    with _transcribe_lock:
        segments, info = model.transcribe(
            str(audio_path),
            language=language,
            beam_size=5,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
            word_timestamps=False,
        )

        seg_list = []
        for seg in segments:
            seg_list.append({
                "start": round(seg.start, 2),
                "end": round(seg.end, 2),
                "text": seg.text.strip(),
            })

    return {
        "language": info.language,
        "language_probability": round(info.language_probability, 2),
        "duration": round(info.duration, 2),
        "segments": seg_list,
        "text": " ".join(s["text"] for s in seg_list),
        "source": "faster_whisper",
    }