"""Twitch VOD & Chat Replay Source Implementation."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import requests
import yt_dlp

from .base import BaseSource, ChatResult, ChatStatus, Platform, VideoMetadata
from .detector import extract_twitch_id

TWITCH_GQL = "https://gql.twitch.tv/gql"
TWITCH_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
TWITCH_COMMENTS_HASH = "b70a3591ff0f4e0313d126c6a1502d79a1c02baebb288227c582044aa76adf6a"

KNOWN_BOTS = {
    "nightbot", "streamelements", "streamlabs", "moobot", "fossabot",
    "botrix", "wizebot", "sery_bot", "soundalerts", "pokemoncommunitygame",
    "kofistreambot", "tangiabot", "commanderroot", "botrixoficial", "streamstickers"
}


class TwitchSource(BaseSource):
    """Source adapter for Twitch VODs and GraphQL chat replay."""

    def probe(self, url_or_path: str) -> VideoMetadata:
        """Extract metadata for Twitch VOD using yt-dlp."""
        clean_url = url_or_path.strip()
        tw_id = extract_twitch_id(clean_url) or clean_url

        if not clean_url.startswith("http"):
            clean_url = f"https://www.twitch.tv/videos/{tw_id}"

        opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "skip_download": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(clean_url, download=False)
            return VideoMetadata(
                id=str(info.get("id") or tw_id),
                title=info.get("title") or "Twitch VOD",
                duration=float(info.get("duration") or 0.0) if info.get("duration") else None,
                uploader=info.get("uploader") or "Streamer",
                thumbnail=info.get("thumbnail"),
                platform=Platform.TWITCH,
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
        """Download Twitch VOD video streams with yt-dlp."""
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        clean_url = url_or_path.strip()
        if not clean_url.startswith("http"):
            tw_id = extract_twitch_id(clean_url) or clean_url
            clean_url = f"https://www.twitch.tv/videos/{tw_id}"

        def hook(d: dict):
            if d.get("status") == "downloading" and on_progress:
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = d.get("downloaded_bytes") or 0
                if total > 0:
                    on_progress(round((downloaded / total) * 100.0, 1))

        opts = {
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
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
        """Download Twitch VOD chat replay via Twitch public GraphQL API."""
        session = requests.Session()
        session.headers.update({
            "Client-Id": TWITCH_CLIENT_ID,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })

        authors_map: dict[str, int] = {}
        messages: list[list] = []
        seen_ids: set[str] = set()

        cursor: str | None = None
        offset: float = 0.0
        has_next_page = True

        while has_next_page:
            variables: dict = {"videoID": video_id}
            if cursor:
                variables["cursor"] = cursor
            else:
                variables["contentOffsetSeconds"] = int(offset)

            body = [{
                "operationName": "VideoCommentsByOffsetOrCursor",
                "variables": variables,
                "extensions": {"persistedQuery": {"version": 1, "sha256Hash": TWITCH_COMMENTS_HASH}},
            }]

            success = False
            for attempt in range(3):
                try:
                    res = session.post(TWITCH_GQL, json=body, timeout=15)
                    if res.status_code == 200:
                        payload = res.json()
                        data = payload[0].get("data", {}) if payload else {}
                        comments_data = (data.get("video") or {}).get("comments") or {}
                        edges = comments_data.get("edges") or []
                        page_info = comments_data.get("pageInfo") or {}

                        if not edges:
                            has_next_page = False
                            break

                        for edge in edges:
                            node = edge.get("node") or {}
                            cid = node.get("id")
                            if not cid or cid in seen_ids:
                                continue
                            seen_ids.add(cid)

                            author_name = ((node.get("commenter") or {}).get("displayName") or "").strip()
                            if not author_name or author_name.lower() in KNOWN_BOTS:
                                continue

                            offset_s = float(node.get("contentOffsetSeconds") or 0.0)
                            fragments = (node.get("message") or {}).get("fragments") or []
                            text = "".join(f.get("text", "") for f in fragments).strip()

                            if not text:
                                continue

                            idx = authors_map.setdefault(author_name, len(authors_map))
                            messages.append([round(offset_s, 2), text[:250], idx])

                        has_next_page = bool(page_info.get("hasNextPage") and edges)
                        cursor = edges[-1].get("cursor") if edges else None
                        if edges:
                            last_offset = float((edges[-1].get("node") or {}).get("contentOffsetSeconds") or offset)
                            offset = max(offset + 1.0, last_offset)

                        success = True
                        break
                    else:
                        time.sleep(1.0 * (attempt + 1))
                except Exception:
                    time.sleep(1.0 * (attempt + 1))

            if not success:
                break

            if on_progress:
                pct = min(100.0, (offset / duration * 100.0)) if duration and duration > 0 else 0.0
                on_progress(pct, len(messages))

            if duration and offset >= duration + 10:
                break

        messages.sort(key=lambda m: m[0])
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        if not messages:
            return ChatResult(
                status=ChatStatus.UNAVAILABLE,
                message_count=0,
                file_path=None,
                detail="No Twitch chat replay found or chat was disabled for this VOD.",
            )

        chat_data = {
            "version": 1,
            "platform": "twitch",
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
            detail=f"Downloaded {len(messages)} Twitch chat replay messages.",
        )
