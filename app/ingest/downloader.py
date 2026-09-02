"""Video/audio downloader using yt-dlp with quality options."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import yt_dlp


def detect_platform(url: str, info: dict | None = None) -> str:
    host = (urlparse(url).hostname or "").lower()
    if "instagram" in host:
        return "instagram"
    if "youtube" in host or host == "youtu.be":
        return "youtube"
    if info:
        extractor = (info.get("extractor_key") or info.get("extractor") or "").lower()
        if "instagram" in extractor:
            return "instagram"
        if "youtube" in extractor:
            return "youtube"
    return "unknown"


def _ydl_base_opts(enable_js_runtimes: bool = False) -> dict:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 30,
        "retries": 3,
    }
    # yt-dlp's "ejs:github" remote component downloads and executes JS from
    # GitHub at runtime to solve some extractor challenges. That's a supply-chain
    # decision, not a default — only enable it if the operator opted in.
    if enable_js_runtimes:
        js_runtimes = {name: {} for name in ("deno", "node", "bun") if shutil.which(name)}
        if js_runtimes:
            opts["js_runtimes"] = js_runtimes
            opts["remote_components"] = {"ejs:github": {}}
    return opts


def _parse_extractor_args(raw: str) -> dict[str, dict[str, list[str]]]:
    result: dict[str, dict[str, list[str]]] = {}
    for part in (raw or "").split("|"):
        if ":" not in part:
            continue
        key, _, val = part.partition(":")
        args: dict[str, list[str]] = {}
        for pair in val.split(";"):
            name, _, vals = pair.partition("=")
            name = name.strip().lower().replace("-", "_")
            if not name:
                continue
            args[name] = [
                v.replace("\\,", ",").strip()
                for v in re.split(r"(?<!\\),", vals)
                if v.strip()
            ] if vals else []
        args = {k: v for k, v in args.items() if v}
        if args:
            result[key.strip().lower().replace("-", "_")] = args
    return result


QUALITY_MAP = {
    "best": "bestvideo+bestaudio/best",
    "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
    "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]",
    "480p": "bestvideo[height<=480]+bestaudio/best[height<=480]",
}

VIDEO_ONLY_MAP = {
    "best": "bestvideo",
    "1080p": "bestvideo[height<=1080]",
    "720p": "bestvideo[height<=720]",
    "480p": "bestvideo[height<=480]",
}

AUDIO_ONLY_MAP = {
    "best": "bestaudio",
}


class MediaDownloader:
    def __init__(
        self,
        download_dir: str | Path,
        cookies_file: str = "",
        extractor_args: str = "",
        enable_js_runtimes: bool = False,
    ) -> None:
        self.download_dir = Path(download_dir)
        self.cookies_file = cookies_file
        self.extractor_args = _parse_extractor_args(extractor_args)
        self.enable_js_runtimes = enable_js_runtimes

    def _opts(self, **extra: Any) -> dict:
        opts = _ydl_base_opts(self.enable_js_runtimes)
        opts["outtmpl"] = str(self.download_dir / "%(id)s.%(ext)s")
        if self.cookies_file and Path(self.cookies_file).is_file():
            opts["cookiefile"] = self.cookies_file
        if self.extractor_args:
            opts["extractor_args"] = dict(self.extractor_args)
        opts.update(extra)
        return opts

    def get_info(self, url: str) -> dict[str, Any]:
        with yt_dlp.YoutubeDL(self._opts()) as ydl:
            info = ydl.extract_info(url, download=False)
        platform = detect_platform(url, info)
        title = info.get("title") or info.get("description") or f"{platform.capitalize()} media"
        uploader = info.get("uploader") or info.get("uploader_id") or info.get("channel") or "Unknown"
        upload_date = info.get("upload_date") or None
        if upload_date and len(upload_date) == 8:
            upload_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
        description = (info.get("description") or "")[:500]

        from .captions import collect_tracks

        payload = {
            "platform": platform,
            "video_id": info.get("id"),
            "webpage_url": info.get("webpage_url") or url,
            "title": title[:200],
            "duration": float(info.get("duration") or 0),
            "uploader": uploader,
            "view_count": int(info.get("view_count") or 0),
            "upload_date": upload_date,
            "thumbnail": info.get("thumbnail"),
            "description": description,
            "language": info.get("language"),
            "categories": info.get("categories") or [],
            "tags": (info.get("tags") or [])[:20],
        }
        tracks = collect_tracks(info)
        if tracks:
            payload["captions_available"] = tracks
        return payload

    def _get_format_selector(self, download_type: str, quality: str) -> str:
        if download_type == "merged":
            return QUALITY_MAP.get(quality, QUALITY_MAP["best"])
        elif download_type == "video_only":
            return VIDEO_ONLY_MAP.get(quality, VIDEO_ONLY_MAP["best"])
        elif download_type == "audio_only":
            return AUDIO_ONLY_MAP.get(quality, AUDIO_ONLY_MAP["best"])
        return QUALITY_MAP["best"]

    def download(self, url: str, download_type: str = "merged", quality: str = "best") -> Path:
        self.download_dir.mkdir(parents=True, exist_ok=True)
        fmt = self._get_format_selector(download_type, quality)
        with yt_dlp.YoutubeDL(self._opts(format=fmt)) as ydl:
            info = ydl.extract_info(url, download=True)
        path = Path(ydl.prepare_filename(info))
        if path.is_file():
            return path
        media = sorted(self.download_dir.glob("*"), key=lambda p: p.stat().st_mtime)
        if not media:
            raise RuntimeError("Download finished but no media file was produced.")
        return media[-1]

    def download_audio_for_whisper(self, url: str) -> Path:
        """Download audio optimized for whisper (lower quality, smaller)."""
        self.download_dir.mkdir(parents=True, exist_ok=True)
        with yt_dlp.YoutubeDL(
            self._opts(format="bestaudio[ext=m4a]/bestaudio/best", quiet=True)
        ) as ydl:
            info = ydl.extract_info(url, download=True)
        path = Path(ydl.prepare_filename(info))
        if path.is_file():
            return path
        media = sorted(self.download_dir.glob("*"), key=lambda p: p.stat().st_mtime)
        if not media:
            raise RuntimeError("Audio download finished but no file was produced.")
        return media[-1]

    def get_playlist_info(self, url: str, max_entries: int = 200) -> dict[str, Any]:
        """List a playlist's videos without downloading or even opening each video
        page — yt-dlp's flat extraction is fast enough to run as the user pastes a link."""
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "skip_download": True,
            "socket_timeout": 30,
            "retries": 3,
            "playlistend": max_entries,
        }
        if self.cookies_file and Path(self.cookies_file).is_file():
            opts["cookiefile"] = self.cookies_file
        if self.extractor_args:
            opts["extractor_args"] = dict(self.extractor_args)

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        entries: list[dict[str, Any]] = []
        for e in info.get("entries") or []:
            if not e:
                continue
            video_id = e.get("id")
            raw_url = e.get("url")
            entry_url = raw_url if raw_url and raw_url.startswith("http") else (
                f"https://www.youtube.com/watch?v={video_id}" if video_id else None
            )
            if not entry_url:
                continue
            thumbnail = e.get("thumbnail")
            if not thumbnail:
                thumbs = e.get("thumbnails") or []
                thumbnail = thumbs[-1]["url"] if thumbs else None
            entries.append({
                "video_id": video_id,
                "url": entry_url,
                "title": e.get("title") or "Untitled",
                "duration": float(e["duration"]) if e.get("duration") else None,
                "thumbnail": thumbnail,
            })

        return {
            "title": info.get("title") or "Playlist",
            "uploader": info.get("uploader") or info.get("channel"),
            "entry_count": len(entries),
            "entries": entries,
        }