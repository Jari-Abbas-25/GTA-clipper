"""Backwards-compatible video & chat downloader adapter.

Delegates to app.backend.sources package for multi-platform support (Twitch, YouTube, Local).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from .sources import (
    BaseSource,
    ChatResult,
    ChatStatus,
    Platform,
    TwitchSource,
    VideoMetadata,
    detect_platform,
    extract_twitch_id,
    extract_youtube_id,
    get_source,
)


def probe_video_info(url_or_path: str) -> dict:
    """Probe video metadata across Twitch, YouTube, or Local files."""
    source, platform, vid_id = get_source(url_or_path)
    meta: VideoMetadata = source.probe(url_or_path)
    return {
        "id": meta.id,
        "title": meta.title,
        "duration": meta.duration,
        "uploader": meta.uploader,
        "thumbnail": meta.thumbnail,
        "webpage_url": meta.webpage_url,
        "is_local": meta.is_local,
        "is_live": meta.is_live,
        "platform": meta.platform.value,
    }


def download_video(
    url_or_path: str,
    dest_path: Path,
    on_progress: Callable[[float], None] | None = None,
) -> Path:
    """Download video from Twitch, YouTube, or Local file."""
    source, _, _ = get_source(url_or_path)
    return source.download_video(url_or_path, dest_path, on_progress=on_progress)


def download_twitch_chat(
    video_id: str,
    output_path: Path,
    duration: float | None = None,
    on_progress: Callable[[float, int], None] | None = None,
) -> ChatResult:
    """Download Twitch chat replay."""
    source = TwitchSource()
    return source.download_chat(video_id, output_path, duration=duration, on_progress=on_progress)
