"""YouTube Video & Archived Livestream Chat Source Implementation."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import yt_dlp

from .base import BaseSource, ChatResult, ChatStatus, Platform, VideoMetadata
from .detector import extract_youtube_id


class YouTubeSource(BaseSource):
    """Source adapter for YouTube videos, shorts, and archived livestreams."""

    def probe(self, url_or_path: str) -> VideoMetadata:
        """Extract metadata for YouTube video using yt-dlp."""
        clean_url = url_or_path.strip()
        yt_id = extract_youtube_id(clean_url)

        if not clean_url.startswith("http"):
            clean_url = f"https://www.youtube.com/watch?v={yt_id or clean_url}"

        opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "skip_download": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(clean_url, download=False)
            duration_val = info.get("duration")
            return VideoMetadata(
                id=str(info.get("id") or yt_id or "youtube_video"),
                title=info.get("title") or "YouTube Video",
                duration=float(duration_val) if duration_val else None,
                uploader=info.get("uploader") or info.get("channel") or "Creator",
                thumbnail=info.get("thumbnail"),
                platform=Platform.YOUTUBE,
                webpage_url=info.get("webpage_url") or clean_url,
                is_local=False,
                is_live=bool(info.get("is_live")),
            )

    def download_video(
        self,
        url_or_path: str,
        dest_path: Path,
        on_progress: Callable[[float], None] | None = None,
    ) -> Path:
        """Download YouTube video with yt-dlp, merging video and audio streams."""
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        clean_url = url_or_path.strip()
        if not clean_url.startswith("http"):
            yt_id = extract_youtube_id(clean_url) or clean_url
            clean_url = f"https://www.youtube.com/watch?v={yt_id}"

        def hook(d: dict):
            if d.get("status") == "downloading" and on_progress:
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = d.get("downloaded_bytes") or 0
                if total > 0:
                    on_progress(round((downloaded / total) * 100.0, 1))

        opts = {
            # Prefer MP4 video + M4A audio or best single stream, merge to MP4 container
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best",
            "outtmpl": str(dest_path),
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [hook],
            "merge_output_format": "mp4",
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([clean_url])

        return dest_path

    def download_chat(
        self,
        video_id: str,
        dest_path: Path,
        duration: float | None = None,
        on_progress: Callable[[float, int], None] | None = None,
    ) -> ChatResult:
        """Attempt to extract archived YouTube live chat replay if available.
        
        Note: Ordinary uploaded YouTube videos do not have livestream chat replay.
        Archived livestreams may have replay if enabled by the creator.
        """
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        temp_dir = dest_path.parent / "temp_yt_chat"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_prefix = temp_dir / f"{video_id}_chat"

        video_url = f"https://www.youtube.com/watch?v={video_id}"
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "writesubtitles": True,
            "subtitleslangs": ["live_chat"],
            "outtmpl": str(temp_prefix),
        }

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([video_url])
        except Exception as err:
            # Clean up temp
            shutil.rmtree(temp_dir, ignore_errors=True)
            return ChatResult(
                status=ChatStatus.UNAVAILABLE,
                message_count=0,
                file_path=None,
                detail=f"Live chat replay unavailable for this YouTube video: {err}",
            )

        # Locate generated .live_chat.json
        live_chat_file = None
        for f in temp_dir.glob("*.live_chat.json"):
            live_chat_file = f
            break

        if not live_chat_file or not live_chat_file.is_file():
            shutil.rmtree(temp_dir, ignore_errors=True)
            return ChatResult(
                status=ChatStatus.UNAVAILABLE,
                message_count=0,
                file_path=None,
                detail="No archived livestream chat available for this YouTube video. Highlight detection will proceed using audio and speech signals.",
            )

        # Parse .live_chat.json (jsonlines format)
        messages: list[list] = []
        authors_map: dict[str, int] = {}

        try:
            with open(live_chat_file, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except Exception:
                        continue

                    replay_action = entry.get("replayChatItemAction") or {}
                    actions = replay_action.get("actions") or []
                    offset_msec = replay_action.get("videoOffsetTimeMsec")

                    for act in actions:
                        item = (act.get("addChatItemAction") or {}).get("item") or {}
                        renderer = (
                            item.get("liveChatTextMessageRenderer")
                            or item.get("liveChatPaidMessageRenderer")
                            or item.get("liveChatPaidStickerRenderer")
                            or item.get("liveChatMembershipItemRenderer")
                        )
                        if not renderer:
                            continue

                        # Extract timestamp
                        msg_offset_msec = renderer.get("videoOffsetTimeMsec") or offset_msec
                        if msg_offset_msec is not None:
                            try:
                                offset_s = float(msg_offset_msec) / 1000.0
                            except (ValueError, TypeError):
                                offset_s = 0.0
                        else:
                            offset_s = 0.0

                        # Extract text
                        runs = (renderer.get("message") or {}).get("runs") or []
                        text = "".join(r.get("text", "") for r in runs if isinstance(r, dict)).strip()
                        if not text:
                            # Check headerSubtext or similar for paid/membership
                            text = (renderer.get("headerSubtext") or {}).get("simpleText") or ""

                        if not text:
                            continue

                        # Extract author
                        author = (renderer.get("authorName") or {}).get("simpleText") or "User"
                        idx = authors_map.setdefault(author, len(authors_map))
                        messages.append([round(offset_s, 2), text[:250], idx])

            messages.sort(key=lambda m: m[0])

            if messages:
                chat_data = {
                    "version": 1,
                    "platform": "youtube",
                    "video_id": video_id,
                    "status": "ok",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "count": len(messages),
                    "authors": len(authors_map),
                    "messages": messages,
                }
                with open(dest_path, "w", encoding="utf-8") as f:
                    json.dump(chat_data, f, ensure_ascii=False)

                return ChatResult(
                    status=ChatStatus.DOWNLOADED,
                    message_count=len(messages),
                    file_path=dest_path,
                    detail=f"Extracted {len(messages)} archived YouTube live chat messages.",
                )
            else:
                return ChatResult(
                    status=ChatStatus.UNAVAILABLE,
                    message_count=0,
                    file_path=None,
                    detail="Live chat file was empty or contained no text messages.",
                )

        except Exception as e:
            return ChatResult(
                status=ChatStatus.FAILED,
                message_count=0,
                file_path=None,
                detail=f"Error parsing YouTube chat replay: {e}",
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
