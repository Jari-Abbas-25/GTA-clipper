"""GTA Clipper - Configuration & System Paths."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

# Base directories
BASE_DIR = Path(__file__).resolve().parents[2]
APP_DIR = BASE_DIR / "app"
FRONTEND_DIR = APP_DIR / "frontend"
PROJECTS_DIR = BASE_DIR / "projects"
EXPORTS_DIR = BASE_DIR / "exports"
MODELS_DIR = BASE_DIR / "models"
TEMP_DIR = BASE_DIR / "temp"

# Ensure all primary runtime directories exist
for directory in (PROJECTS_DIR, EXPORTS_DIR, MODELS_DIR, TEMP_DIR):
    directory.mkdir(parents=True, exist_ok=True)

# Hardware and environment
IS_WINDOWS = sys.platform == "win32"
CPU_CORES = os.cpu_count() or 4
FFMPEG_PATH = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE_PATH = shutil.which("ffprobe") or "ffprobe"

# Default clipping options
DEFAULT_CLIP_MIN = 15.0      # Minimum clip duration (seconds)
DEFAULT_CLIP_IDEAL = 35.0    # Target clip duration (seconds)
DEFAULT_CLIP_MAX = 60.0      # Maximum clip duration (seconds for Shorts/TikTok)
DEFAULT_PRE_ROLL = 6.0       # Seconds of setup before peak
DEFAULT_POST_ROLL = 4.0      # Seconds of reaction after peak
DEFAULT_MIN_GAP = 35.0       # Minimum seconds between highlight peaks

# Canvas preview constants
PREVIEW_W = 360
PREVIEW_H = 640
EXPORT_W = 1080
EXPORT_H = 1920
SPLIT_FACE_H = 768           # 40% height for facecam in 1080x1920
SPLIT_GAME_H = 1152          # 60% height for gameplay in 1080x1920
