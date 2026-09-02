"""Allowlist check for video URLs, to keep yt-dlp from being used as an SSRF vector."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

ALLOWED_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be",
    "instagram.com", "www.instagram.com",
}


def is_allowed_video_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    return host in ALLOWED_HOSTS


def is_playlist_url(url: str) -> bool:
    """YouTube playlist link (`?list=...` or `/playlist`). Instagram has no
    playlist concept, so this is always False for it."""
    if not is_allowed_video_url(url):
        return False
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if "instagram" in host:
        return False
    if bool(parse_qs(parsed.query).get("list")):
        return True
    return parsed.path.rstrip("/").endswith("/playlist")
