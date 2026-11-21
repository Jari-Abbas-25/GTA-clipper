"""Project & Storage Management Engine.

Organizes project assets into isolated directories:
- projects/<project_id>/source.mp4       (Source VOD)
- projects/<project_id>/audio.wav        (Extracted 16kHz mono audio)
- projects/<project_id>/chat.json        (Twitch chat log)
- projects/<project_id>/meta.json        (Project metadata)
- projects/<project_id>/highlights.json  (Detected candidates & hype curve)
- projects/<project_id>/clip_settings/   (User editing preferences per clip)
- exports/<project_id>/                  (Final 1080x1920 MP4 clips)
- models/                                (Local quantized models)
- temp/                                  (Scratch processing buffers)

Provides one-click storage cleanup without touching exported clips.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import EXPORTS_DIR, MODELS_DIR, PROJECTS_DIR, TEMP_DIR


@dataclass
class ProjectMeta:
    id: str
    title: str
    source_url_or_path: str
    duration: float
    created_at: str
    status: str  # "created", "downloading", "analyzing", "ready", "error"
    platform: str = "twitch"  # "twitch", "youtube", "local"
    video_id: str | None = None
    is_local: bool = False
    chat_status: str = "unavailable"  # "downloaded", "unavailable", "failed"
    chat_message_count: int = 0
    ai_provider: str = "heuristics"
    facecam_region: dict | None = None


class Project:
    def __init__(
        self,
        project_id: str,
        base_dir: Path | None = None,
        export_base_dir: Path | None = None,
    ):
        self.id = project_id
        self.base_dir = base_dir or PROJECTS_DIR
        self.dir = self.base_dir / project_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir = self.dir / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.settings_dir = self.dir / "clip_settings"
        self.settings_dir.mkdir(parents=True, exist_ok=True)

        self.source_video = self.dir / "source.mp4"
        self.audio_path = self.dir / "audio.wav"
        self.chat_path = self.dir / "chat.json"
        self.meta_path = self.dir / "meta.json"
        self.highlights_path = self.dir / "highlights.json"
        self.export_dir = (export_base_dir / project_id) if export_base_dir else (EXPORTS_DIR / project_id)
        self.export_dir.mkdir(parents=True, exist_ok=True)

    def load_meta(self) -> dict:
        if self.meta_path.is_file():
            try:
                with open(self.meta_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "id": self.id,
            "title": self.id,
            "source_url_or_path": "",
            "duration": 0.0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "created",
            "is_local": False
        }

    def save_meta(self, meta: dict) -> None:
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

    def load_highlights(self) -> dict | None:
        if self.highlights_path.is_file():
            try:
                with open(self.highlights_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return None

    def save_highlights(self, data: dict) -> None:
        with open(self.highlights_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def load_clip_setting(self, clip_id: str) -> dict | None:
        p = self.settings_dir / f"{clip_id}.json"
        if p.is_file():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return None

    def save_clip_setting(self, clip_id: str, setting: dict) -> None:
        p = self.settings_dir / f"{clip_id}.json"
        with open(p, "w", encoding="utf-8") as f:
            json.dump(setting, f, indent=2, ensure_ascii=False)

    def list_exports(self) -> list[dict]:
        exports = []
        if self.export_dir.is_dir():
            for p in self.export_dir.glob("*.mp4"):
                st = p.stat()
                exports.append({
                    "name": p.name,
                    "path": str(p.resolve()),
                    "size_mb": round(st.st_size / (1024 * 1024), 2),
                    "modified": datetime.fromtimestamp(st.st_mtime).isoformat()
                })
        exports.sort(key=lambda x: x["modified"], reverse=True)
        return exports

    def disk_usage(self) -> dict:
        """Calculate disk space usage in MB."""
        def dir_size(d: Path) -> float:
            if not d.is_dir():
                return 0.0
            total = 0
            for root, _, files in os.walk(d):
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        total += os.path.getsize(fp)
                    except OSError:
                        pass
            return round(total / (1024 * 1024), 2)

        source_mb = round(self.source_video.stat().st_size / (1024 * 1024), 2) if self.source_video.is_file() else 0.0
        audio_mb = round(self.audio_path.stat().st_size / (1024 * 1024), 2) if self.audio_path.is_file() else 0.0
        cache_mb = dir_size(self.cache_dir)
        exports_mb = dir_size(self.export_dir)

        return {
            "source_video_mb": source_mb,
            "audio_wav_mb": audio_mb,
            "cache_mb": cache_mb,
            "exports_mb": exports_mb,
            "total_mb": round(source_mb + audio_mb + cache_mb + exports_mb, 2)
        }

    def cleanup(self, delete_source: bool = False, delete_cache: bool = True) -> dict:
        """Free disk space while safely preserving exported clips and metadata."""
        freed_bytes = 0

        if delete_cache:
            if self.audio_path.is_file():
                freed_bytes += self.audio_path.stat().st_size
                self.audio_path.unlink()
            if self.cache_dir.is_dir():
                for f in self.cache_dir.glob("*"):
                    try:
                        freed_bytes += f.stat().st_size
                        f.unlink()
                    except OSError:
                        pass

        if delete_source and self.source_video.is_file():
            freed_bytes += self.source_video.stat().st_size
            self.source_video.unlink()

        return {
            "freed_mb": round(freed_bytes / (1024 * 1024), 2),
            "source_deleted": delete_source,
            "cache_deleted": delete_cache
        }


def sanitize_project_id(title_or_id: str) -> str:
    slug = re.sub(r"[^\w\-_]", "_", title_or_id.strip()).strip("_")
    return slug[:50] or f"project_{int(datetime.now().timestamp())}"


def create_project(
    title: str,
    url_or_path: str,
    platform: str = "twitch",
    video_id: str | None = None,
) -> Project:
    pid = sanitize_project_id(title)
    # Ensure uniqueness
    candidate_id = pid
    counter = 1
    while (PROJECTS_DIR / candidate_id / "meta.json").is_file():
        candidate_id = f"{pid}_{counter}"
        counter += 1

    proj = Project(candidate_id)
    meta = {
        "id": candidate_id,
        "title": title,
        "source_url_or_path": url_or_path,
        "platform": platform,
        "video_id": video_id,
        "duration": 0.0,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "created",
        "is_local": Path(url_or_path).is_file(),
        "chat_status": "pending",
        "chat_message_count": 0,
        "ai_provider": "heuristics",
    }
    proj.save_meta(meta)
    return proj


def create_demo_project() -> Project:
    """Explicitly create a demo project by copying from tests/fixtures/sample_project.
    
    ONLY invoked when user explicitly clicks 'Try Offline Demo'. Never runs automatically.
    """
    from .config import FIXTURES_DIR
    fixture_dir = FIXTURES_DIR / "sample_project"
    if not fixture_dir.is_dir():
        raise RuntimeError("Demo fixtures not found in tests/fixtures/sample_project")

    title = "GTA 6 Heist & Cop Chase Highlights (Demo)"
    proj = create_project(title, "demo://sample_gta6_heist", platform="local", video_id="demo_vod")

    # Copy files from fixture
    for item in fixture_dir.iterdir():
        dest = proj.dir / item.name
        if item.is_file():
            shutil.copy2(item, dest)
        elif item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True)

    meta = proj.load_meta()
    meta["title"] = title
    meta["status"] = "ready"
    meta["is_demo"] = True
    proj.save_meta(meta)
    return proj


def list_all_projects() -> list[dict]:
    projects = []
    if not PROJECTS_DIR.is_dir():
        return []
    for d in PROJECTS_DIR.iterdir():
        if d.is_dir() and (d / "meta.json").is_file():
            try:
                with open(d / "meta.json", "r", encoding="utf-8") as f:
                    meta = json.load(f)
                    proj = Project(d.name)
                    meta["disk_usage"] = proj.disk_usage()
                    meta["export_count"] = len(proj.list_exports())
                    projects.append(meta)
            except Exception:
                pass
    projects.sort(key=lambda p: p.get("created_at", ""), reverse=True)
    return projects
