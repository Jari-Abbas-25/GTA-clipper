"""Multi-Platform Video & Chat Ingestion Package."""

from __future__ import annotations

from .base import BaseSource, ChatResult, ChatStatus, Platform, VideoMetadata
from .detector import detect_platform, extract_twitch_id, extract_youtube_id
from .local import LocalSource
from .twitch import TwitchSource
from .youtube import YouTubeSource


def get_source(url_or_path: str) -> tuple[BaseSource, Platform, str | None]:
    """Factory to retrieve appropriate source adapter, platform, and video ID."""
    platform, vid_id = detect_platform(url_or_path)
    if platform == Platform.TWITCH:
        return TwitchSource(), platform, vid_id
    elif platform == Platform.YOUTUBE:
        return YouTubeSource(), platform, vid_id
    else:
        return LocalSource(), platform, vid_id


__all__ = [
    "BaseSource",
    "ChatResult",
    "ChatStatus",
    "Platform",
    "VideoMetadata",
    "detect_platform",
    "extract_twitch_id",
    "extract_youtube_id",
    "get_source",
    "LocalSource",
    "TwitchSource",
    "YouTubeSource",
]
