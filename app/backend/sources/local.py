"""Local Video File Source Implementation."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Callable

from .base import BaseSource, ChatResult, ChatStatus, Platform, VideoMetadata


class LocalSource(BaseSource):
    """Source adapter for local video files."""

    def probe(self, url_or_path: str) -> VideoMetadata:
        p = Path(url_or_path).resolve()
        duration = None

        # Probe duration via ffprobe if possible
        try:
            import subprocess
            from ..config import FFPROBE_PATH
            cmd = [
                FFPROBE_PATH, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(p)
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            duration = float(res.stdout.strip())
        except Exception:
            pass

        return VideoMetadata(
            id=p.stem,
            title=p.stem,
            duration=duration,
            uploader="Local File",
            thumbnail=None,
            platform=Platform.LOCAL,
            webpage_url=str(p),
            is_local=True,
            is_live=False,
        )

    def download_video(
        self,
        url_or_path: str,
        dest_path: Path,
        on_progress: Callable[[float], None] | None = None,
    ) -> Path:
        src = Path(url_or_path).resolve()
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        if src != dest_path.resolve():
            try:
                if hasattr(os, "link"):
                    os.link(src, dest_path)
                else:
                    shutil.copy2(src, dest_path)
            except Exception:
                shutil.copy2(src, dest_path)
        if on_progress:
            on_progress(100.0)
        return dest_path

    def download_chat(
        self,
        video_id: str,
        dest_path: Path,
        duration: float | None = None,
        on_progress: Callable[[float, int], None] | None = None,
    ) -> ChatResult:
        """Check if an adjacent .chat.json exists alongside the local video file."""
        src_chat = dest_path.parent / f"{video_id}.chat.json"
        if not src_chat.is_file():
            src_chat = dest_path.parent / "chat.json"

        if src_chat.is_file() and src_chat != dest_path:
            try:
                shutil.copy2(src_chat, dest_path)
                with open(dest_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return ChatResult(
                    status=ChatStatus.DOWNLOADED,
                    message_count=data.get("count", len(data.get("messages", []))),
                    file_path=dest_path,
                    detail="Loaded local chat log.",
                )
            except Exception as e:
                return ChatResult(status=ChatStatus.FAILED, detail=str(e))

        return ChatResult(
            status=ChatStatus.UNAVAILABLE,
            detail="No local chat file provided. Analyzing with audio signals and speech recognition.",
        )
