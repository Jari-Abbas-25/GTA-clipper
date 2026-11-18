"""Twitch VOD & Chat Downloader.

Downloads Twitch VODs and full timestamped chat replay using:
- Twitch's public GraphQL API (no login/token needed, zero cost)
- yt-dlp for video stream download
- Local file importer for pre-downloaded videos and chat logs
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import requests
import yt_dlp

TWITCH_GQL = "https://gql.twitch.tv/gql"
TWITCH_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
TWITCH_COMMENTS_HASH = "b70a3591ff0f4e0313d126c6a1502d79a1c02baebb288227c582044aa76adf6a"

KNOWN_BOTS = {
    "nightbot", "streamelements", "streamlabs", "moobot", "fossabot",
    "botrix", "wizebot", "sery_bot", "soundalerts", "pokemoncommunitygame",
    "kofistreambot", "tangiabot", "commanderroot", "botrixoficial", "streamstickers"
}


def extract_twitch_id(url_or_id: str) -> str | None:
    """Extract numeric Twitch VOD ID from URL or bare ID."""
    clean = url_or_id.strip()
    if clean.isdigit():
        return clean
    match = re.search(r"(?:twitch\.tv\/videos\/|twitch\.tv\/[^\/]+\/v\/)(\d+)", clean)
    if match:
        return match.group(1)
    return None


def probe_video_info(url_or_path: str) -> dict:
    """Extract metadata for a URL or local file with yt-dlp."""
    if Path(url_or_path).is_file():
        p = Path(url_or_path)
        return {
            "id": p.stem,
            "title": p.stem,
            "duration": None,
            "uploader": "Local File",
            "is_local": True,
            "local_path": str(p.resolve())
        }

    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url_or_path, download=False)
        return {
            "id": str(info.get("id")),
            "title": info.get("title", "Untitled VOD"),
            "duration": info.get("duration"),
            "uploader": info.get("uploader", "Streamer"),
            "thumbnail": info.get("thumbnail"),
            "webpage_url": info.get("webpage_url", url_or_path),
            "is_local": False
        }


def download_twitch_chat(
    video_id: str,
    output_path: Path,
    duration: float | None = None,
    on_progress: Callable[[float, int], None] | None = None
) -> dict:
    """Fetch Twitch VOD chat comments via Twitch public GraphQL API.
    
    Pages through comments by contentOffsetSeconds.
    Stores messages formatted as: [[timestamp_s, message_text, author_idx], ...]
    """
    session = requests.Session()
    session.headers.update({
        "Client-Id": TWITCH_CLIENT_ID,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })

    authors_map: dict[str, int] = {}
    messages: list[list] = []
    seen_ids: set[str] = set()

    cursor: str | None = None
    offset: float = 0.0
    has_next_page = True
    page_count = 0

    while has_next_page:
        page_count += 1
        variables: dict = {"videoID": video_id}
        if cursor:
            variables["cursor"] = cursor
        else:
            variables["contentOffsetSeconds"] = int(offset)

        body = [{
            "operationName": "VideoCommentsByOffsetOrCursor",
            "variables": variables,
            "extensions": {"persistedQuery": {"version": 1, "sha256Hash": TWITCH_COMMENTS_HASH}}
        }]

        success = False
        for attempt in range(4):
            try:
                res = session.post(TWITCH_GQL, json=body, timeout=20)
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
                        if last_offset > offset:
                            offset = last_offset
                        else:
                            offset += 1.0

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
    chat_data = {
        "version": 1,
        "video_id": video_id,
        "status": "ok" if messages else "empty",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "count": len(messages),
        "authors": len(authors_map),
        "messages": messages
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(chat_data, f, ensure_ascii=False)

    return chat_data


def download_video(
    url_or_path: str,
    dest_path: Path,
    on_progress: Callable[[float], None] | None = None
) -> Path:
    """Download video with yt-dlp or copy/link local file."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    if Path(url_or_path).is_file():
        src = Path(url_or_path).resolve()
        if src != dest_path.resolve():
            # Copy or hardlink
            try:
                if hasattr(os, "link"):
                    os.link(src, dest_path)
                else:
                    shutil.copy2(src, dest_path)
            except Exception:
                shutil.copy2(src, dest_path)
        return dest_path

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
        "merge_output_format": "mp4"
    }

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url_or_path])

    return dest_path
