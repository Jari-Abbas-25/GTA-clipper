"""Base abstractions and types for video & chat sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable


class Platform(str, Enum):
    TWITCH = "twitch"
    YOUTUBE = "youtube"
    LOCAL = "local"


class ChatStatus(str, Enum):
    DOWNLOADED = "downloaded"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


@dataclass
class VideoMetadata:
    id: str
    title: str
    duration: float | None
    uploader: str
    thumbnail: str | None
    platform: Platform
    webpage_url: str
    is_local: bool = False
    is_live: bool = False


@dataclass
class ChatResult:
    status: ChatStatus
    message_count: int = 0
    file_path: Path | None = None
    detail: str = ""


class BaseSource(ABC):
    """Abstract base source for video and chat ingestion."""

    @abstractmethod
    def probe(self, url_or_path: str) -> VideoMetadata:
        """Probe video metadata."""
        pass

    @abstractmethod
    def download_video(
        self,
        url_or_path: str,
        dest_path: Path,
        on_progress: Callable[[float], None] | None = None,
    ) -> Path:
        """Download video to destination path."""
        pass

    @abstractmethod
    def download_chat(
        self,
        video_id: str,
        dest_path: Path,
        duration: float | None = None,
        on_progress: Callable[[float, int], None] | None = None,
    ) -> ChatResult:
        """Download timestamped chat replay if available."""
        pass
