"""Fetch platform-provided transcripts (YouTube captions) so ASR can be skipped."""

from __future__ import annotations

import json
import re
import urllib.request
from typing import Any, Optional

FORMAT_PRIORITY = ("json3", "vtt", "srv3", "srv2", "srv1", "srt", "sbv")
MAX_CAPTION_BYTES = 5 * 1024 * 1024
MAX_CHARS_PER_SEGMENT = 90
MERGE_GAP_S = 1.5
MIN_SENTENCE_CHARS = 40
SOUND_TAG_RE = re.compile(r"\[[^\]\[]{0,40}\]")
INLINE_TAG_RE = re.compile(r"<[^>]+>")
CUE_TIME_RE = re.compile(
    r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})[.,](\d{1,3})\s*-->\s*(?:(\d{1,2}):)?(\d{1,2}):(\d{2})[.,](\d{1,3})"
)


def base_lang(lang: str) -> str:
    return (lang or "").split("-")[0].split("_")[0].lower()


def _clean(text: str) -> str:
    text = INLINE_TAG_RE.sub(" ", text)
    text = SOUND_TAG_RE.sub(" ", text)
    text = re.sub(r">>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _pick_format(formats: list[dict]) -> Optional[dict]:
    by_ext = {f.get("ext"): f for f in formats if isinstance(f, dict)}
    for ext in FORMAT_PRIORITY:
        if ext in by_ext and by_ext[ext].get("url"):
            return by_ext[ext]
    return None


def collect_tracks(info: dict) -> list[dict]:
    """Flatten yt-dlp subtitle/automatic_captions dicts into compact track records."""
    tracks: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for kind, bucket in (
        ("manual", info.get("subtitles") or {}),
        ("auto", info.get("automatic_captions") or {}),
    ):
        for lang, formats in bucket.items():
            if not isinstance(formats, list):
                continue
            fmt = _pick_format(formats)
            if not fmt:
                continue
            key = (kind, lang)
            if key in seen:
                continue
            seen.add(key)
            tracks.append({
                "lang": lang,
                "base_lang": base_lang(lang),
                "kind": kind,
                "ext": fmt["ext"],
                "url": fmt["url"],
            })
    return tracks


def choose_track(tracks: list[dict], video_lang: str | None) -> Optional[dict]:
    """Manual beats auto; English and the original language beat the rest."""
    if not tracks:
        return None
    vl = base_lang(video_lang or "")
    manuals = [t for t in tracks if t["kind"] == "manual"]
    autos = [t for t in tracks if t["kind"] == "auto"]

    def pick(pool: list[dict]) -> Optional[dict]:
        for pred in (
            lambda t: t["base_lang"] == "en",
            lambda t: vl and t["base_lang"] == vl,
            lambda t: t["base_lang"].startswith("en"),
        ):
            hit = [t for t in pool if pred(t)]
            if hit:
                return sorted(hit, key=lambda t: t["lang"])[0]
        return sorted(pool, key=lambda t: t["lang"])[0] if pool else None

    return pick(manuals) or pick(autos)


def download_caption(track: dict) -> tuple[Any, str]:
    req = urllib.request.Request(
        track["url"], headers={"User-Agent": "Mozilla/5.0 (compatible; video-summarizer)"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read(MAX_CAPTION_BYTES + 1)
    if len(raw) > MAX_CAPTION_BYTES:
        raise ValueError("caption payload too large")
    text = raw.decode("utf-8", errors="replace")
    if track["ext"] == "json3":
        return json.loads(text), "json3"
    return text, "vtt"


def parse_json3(payload: dict) -> list[tuple[float, float, str]]:
    cues: list[tuple[float, float, str]] = []
    for ev in payload.get("events", []):
        if ev.get("aAppend"):
            continue
        segs = ev.get("segs") or []
        text = _clean("".join(s.get("utf8", "") for s in segs))
        if not text:
            continue
        start = max(0.0, (ev.get("tStartMs") or 0) / 1000.0)
        end = start + max(200.0, ev.get("dDurationMs") or 1500) / 1000.0
        cues.append((start, end, text))
    return cues


def parse_timed_text(raw: str) -> list[tuple[float, float, str]]:
    """Parse WebVTT / SRT cue blocks."""
    cues: list[tuple[float, float, str]] = []
    current: Optional[tuple[float, float]] = None
    body: list[str] = []

    def flush() -> None:
        nonlocal current, body
        if current and body:
            text = _clean(" ".join(body))
            if text:
                cues.append((current[0], current[1], text))
        current, body = None, []

    for line in raw.splitlines():
        m = CUE_TIME_RE.search(line)
        if m:
            flush()
            start = _ts(m.group(1), m.group(2), m.group(3), m.group(4))
            end = _ts(m.group(5), m.group(6), m.group(7), m.group(8))
            current = (start, max(start, end))
            continue
        if line.strip() and current is not None:
            body.append(line.strip())
        elif not line.strip():
            flush()
    flush()
    return cues


def _ts(h: str | None, m: str, s: str, ms: str) -> float:
    return (int(h or 0) * 3600) + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def _dedupe_rolling(cues: list[tuple[float, float, str]]) -> list[tuple[float, float, str]]:
    """Drop words repeated from the immediately previous cue (YouTube auto-caption rolling)."""
    out: list[tuple[float, float, str]] = []
    prev_words: list[str] = []
    for start, end, text in cues:
        words = text.split()
        if prev_words:
            max_k = min(len(words) - 1, len(prev_words))
            for k in range(max_k, 0, -1):
                if [w.lower().strip(".,!?;:") for w in words[:k]] == [
                    w.lower().strip(".,!?;:") for w in prev_words[-k:]
                ]:
                    words = words[k:]
                    break
        if not words:
            prev_words = prev_words if not out else text.split()
            continue
        out.append((start, end, " ".join(words)))
        prev_words = words
    return out


def merge_cues(cues: list[tuple[float, float, str]]) -> list[dict]:
    merged: list[dict] = []
    cur_start = cur_end = None
    chars = 0
    pending: list[tuple[float, float, str]] = []

    def flush() -> None:
        nonlocal cur_start, cur_end, chars, pending
        if cur_start is not None and cur_end is not None and pending:
            texts = [c[2] for c in pending]
            merged.append({
                "start": round(cur_start, 2),
                "end": round(cur_end, 2),
                "text": " ".join(texts),
            })
        pending.clear()
        cur_start = cur_end = None
        chars = 0

    for start, end, text in cues:
        if cur_start is None:
            cur_start, cur_end, chars = start, end, len(text)
            pending.append((start, end, text))
            continue
        gap = start - (cur_end or 0)
        sentence_done = pending[-1][2].endswith((".", "!", "?"))
        if (
            gap > MERGE_GAP_S
            or chars >= MAX_CHARS_PER_SEGMENT
            or (sentence_done and chars >= MIN_SENTENCE_CHARS)
        ):
            flush()
            cur_start, cur_end, chars = start, end, len(text)
            pending.append((start, end, text))
        else:
            cur_end = max(cur_end or end, end)
            chars += len(text) + 1
            pending.append((start, end, text))
    flush()
    return merged


def build_transcript(
    cues: list[tuple[float, float, str]], language_hint: str, fallback_duration: float
) -> Optional[dict]:
    cues = _dedupe_rolling(cues)
    segments = merge_cues(cues)
    if not segments:
        return None
    text = " ".join(s["text"] for s in segments)
    if len(text) < 40:
        return None
    duration = max(fallback_duration, segments[-1]["end"])
    return {
        "language": language_hint or "unknown",
        "duration": round(duration, 2),
        "segments": segments,
        "text": text,
        "source": "platform_captions",
    }


def fetch_from_tracks(
    tracks: list[dict], video_lang: str | None, fallback_duration: float
) -> Optional[dict]:
    """Try to build a transcript purely from platform captions. None => fall back to ASR."""
    try:
        track = choose_track(tracks or [], video_lang)
        if not track:
            return None
        payload, kind = download_caption(track)
        cues = parse_json3(payload) if kind == "json3" else parse_timed_text(payload)
        if not cues:
            return None
        return build_transcript(cues, base_lang(track["lang"]), fallback_duration)
    except Exception:
        return None