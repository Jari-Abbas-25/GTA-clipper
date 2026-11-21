"""Platform detection and Video ID extraction."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .base import Platform

# Regex patterns for platforms
TWITCH_PATTERNS = [
    re.compile(r"(?:twitch\.tv\/videos\/|twitch\.tv\/[^\/]+\/v\/)(\d+)"),
]

YOUTUBE_PATTERNS = [
    re.compile(r"(?:youtube\.com\/watch\?.*v=)([a-zA-Z0-9_-]{11})"),
    re.compile(r"(?:youtu\.be\/)([a-zA-Z0-9_-]{11})"),
    re.compile(r"(?:youtube\.com\/live\/)([a-zA-Z0-9_-]{11})"),
    re.compile(r"(?:youtube\.com\/shorts\/)([a-zA-Z0-9_-]{11})"),
    re.compile(r"(?:youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})"),
    re.compile(r"(?:youtube\.com\/v\/)([a-zA-Z0-9_-]{11})"),
]


def extract_twitch_id(url_or_id: str) -> str | None:
    """Extract numeric Twitch VOD ID from URL or bare ID."""
    clean = url_or_id.strip()
    if clean.isdigit() and len(clean) >= 6:
        return clean
    for pattern in TWITCH_PATTERNS:
        match = pattern.search(clean)
        if match:
            return match.group(1)
    return None


def extract_youtube_id(url_or_id: str) -> str | None:
    """Extract 11-char YouTube Video ID from URL or query parameters."""
    clean = url_or_id.strip()
    for pattern in YOUTUBE_PATTERNS:
        match = pattern.search(clean)
        if match:
            return match.group(1)

    # Check query parameter ?v=
    try:
        parsed = urlparse(clean)
        if "youtube" in parsed.netloc or "youtu.be" in parsed.netloc:
            qs = parse_qs(parsed.query)
            if "v" in qs and qs["v"]:
                val = qs["v"][0]
                if len(val) == 11:
                    return val
    except Exception:
        pass

    return None


def detect_platform(url_or_path: str) -> tuple[Platform, str | None]:
    """Detect whether source is Twitch, YouTube, or a local file.
    
    Returns:
        tuple[Platform, Optional[str]]: The detected platform and the extracted ID or path stem.
    """
    clean = url_or_path.strip()

    # 1. Local file path check
    try:
        p = Path(clean)
        if p.is_file():
            return Platform.LOCAL, p.stem
    except Exception:
        pass

    # 2. Twitch check
    tw_id = extract_twitch_id(clean)
    if tw_id:
        return Platform.TWITCH, tw_id
    if "twitch.tv" in clean.lower():
        return Platform.TWITCH, None

    # 3. YouTube check
    yt_id = extract_youtube_id(clean)
    if yt_id:
        return Platform.YOUTUBE, yt_id
    if "youtube.com" in clean.lower() or "youtu.be" in clean.lower():
        return Platform.YOUTUBE, None

    # Default fallback to local path if file exists or generic local
    return Platform.LOCAL, Path(clean).stem if clean else None
