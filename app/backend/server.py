"""FastAPI Backend Server for GTA Clipper.

Provides REST and streaming endpoints for:
- Multi-Platform Video & Chat downloading (Twitch, YouTube, Local)
- Multi-signal highlight detection & Hype Map
- Video streaming with HTTP Range requests
- Candidate-window faster-whisper transcription
- Real-time 9:16 Canvas editor state persistence
- FFmpeg 1080x1920 vertical MP4 export
- Native Windows Save As dialog & direct file saving
- First-launch AI Provider configuration & connectivity testing (Ollama, DeepSeek, OpenRouter, Heuristics)
- Storage management & cleanup
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

# Ensure parent directories and package context are available whether run directly or imported
_current_file = Path(__file__).resolve()
_backend_dir = _current_file.parent
_project_root = _backend_dir.parent.parent

for _p in (str(_project_root), str(_backend_dir)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

if __package__ in (None, ""):
    import importlib
    importlib.import_module("app.backend")
    __package__ = "app.backend"

# External framework imports with inline type ignores for editor portability
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request, Response  # type: ignore # pyrefly: ignore
from fastapi.middleware.cors import CORSMiddleware  # type: ignore # pyrefly: ignore
from fastapi.responses import FileResponse, StreamingResponse  # type: ignore # pyrefly: ignore
from fastapi.staticfiles import StaticFiles  # type: ignore # pyrefly: ignore
from pydantic import BaseModel  # type: ignore # pyrefly: ignore

try:
    import cv2  # type: ignore # pyrefly: ignore
except ImportError:
    cv2 = None  # type: ignore

from .ai_evaluator import (
    OLLAMA_MODEL_SPECS,
    generate_ai_edit_suggestions,
    get_ollama_status,
    is_ollama_available,
    load_ai_config,
    save_ai_config,
    test_ai_connection,
)
from .audio_signals import extract_audio_wav
from .config import CPU_CORES, EXPORTS_DIR, FRONTEND_DIR, IS_WINDOWS, PROJECTS_DIR
from .facecam_detector import detect_facecam, extract_frame_image
from .highlight_engine import run_highlight_detection
from .renderer import RenderOptions, render_clip
from .sources import (
    BaseSource,
    ChatResult,
    ChatStatus,
    Platform,
    VideoMetadata,
    detect_platform,
    get_source,
)
from .storage import Project, create_demo_project, create_project, list_all_projects
from .transcriber import (
    FASTER_WHISPER_AVAILABLE,
    SubtitleSegment,
    WordTiming,
    generate_ass_subtitles,
    transcribe_window,
)

app = FastAPI(title="GTA Clipper API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Background job states
_job_progress: dict[str, dict[str, Any]] = {}


def _model_to_dict(req: BaseModel) -> dict[str, Any]:
    """Compatible dict extraction supporting both Pydantic v1 and v2 without deprecation warnings."""
    if hasattr(req, "model_dump"):
        data = req.model_dump(exclude_unset=True)
    else:
        data = req.dict(exclude_unset=True)  # type: ignore[deprecated]
    return {k: v for k, v in data.items() if v is not None}


# ============================================================================
# Request Models
# ============================================================================

class ProbeRequest(BaseModel):
    url_or_path: str


class CreateProjectRequest(BaseModel):
    url_or_path: str
    title: str | None = None


class AnalyzeProjectRequest(BaseModel):
    target_count: int = 5
    min_duration: float = 15.0
    max_duration: float = 60.0
    sensitivity: str = "medium"  # "low", "medium", "high"
    focus_mode: str = "all"      # "all", "action", "funny", "story"


class SaveClipSettingRequest(BaseModel):
    layout: str = "split"
    aspect_ratio: str = "9:16"   # "9:16" or "16:9"
    facecam_x: float = 0.72
    facecam_y: float = 0.06
    facecam_w: float = 0.24
    facecam_h: float = 0.28
    gameplay_pan_x: float = 0.5
    zoom_factor: float = 1.0
    sections: list[dict[str, Any]] | None = None
    start_s: float | None = None
    end_s: float | None = None
    enable_subtitles: bool = True
    subtitle_style: str = "bold"
    font_size: int = 68
    highlight_color: str = "&H006AB5D9"
    clip_title: str | None = None


class RenderClipRequest(BaseModel):
    setting: SaveClipSettingRequest | None = None
    destination_path: str | None = None


class CleanupRequest(BaseModel):
    delete_source: bool = False
    delete_cache: bool = True


class AiConfigRequest(BaseModel):
    mode: str | None = None
    provider: str | None = None
    ollama_url: str | None = None
    ollama_model: str | None = None
    deepseek_url: str | None = None
    deepseek_model: str | None = None
    deepseek_key: str | None = None
    openrouter_url: str | None = None
    openrouter_model: str | None = None
    openrouter_key: str | None = None
    configured: bool | None = None


class AiTestRequest(BaseModel):
    provider: str
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None


class SaveToPathRequest(BaseModel):
    destination_path: str
    overwrite: bool = False


class OpenFolderRequest(BaseModel):
    path: str


# ============================================================================
# System & AI Endpoints
# ============================================================================

@app.get("/api/status")
def get_system_status():
    ollama_ok, ollama_model = is_ollama_available()
    ai_cfg = load_ai_config()
    return {
        "status": "online",
        "platform": "windows" if IS_WINDOWS else "other",
        "cpu_cores": CPU_CORES,
        "ffmpeg_available": bool(shutil.which("ffmpeg")),
        "whisper_available": FASTER_WHISPER_AVAILABLE,
        "ollama_available": ollama_ok,
        "ollama_model": ollama_model,
        "ai_mode": ai_cfg.get("mode", "local"),
        "ai_provider": ai_cfg.get("provider", "ollama"),
        "projects_dir": str(PROJECTS_DIR.resolve()),
        "exports_dir": str(EXPORTS_DIR.resolve()),
    }


@app.get("/api/ai/config")
def get_ai_configuration():
    """Retrieve active AI settings with masked keys."""
    return load_ai_config()


@app.post("/api/ai/config")
def update_ai_configuration(req: AiConfigRequest):
    """Update AI mode, provider, endpoints, or keys."""
    updates = _model_to_dict(req)
    updated = save_ai_config(updates)
    return {"status": "saved", "config": updated}


@app.get("/api/ai/ollama/models")
def list_ollama_models(url: str = Query(None)):
    """Retrieve installed models from local Ollama instance with model size and RAM requirements."""
    ok, models, recommended = get_ollama_status(url)
    detailed_models = []
    for m in models:
        spec = OLLAMA_MODEL_SPECS.get(m, {})
        if not spec:
            for k, s in OLLAMA_MODEL_SPECS.items():
                if m.startswith(k):
                    spec = s
                    break
        detailed_models.append({
            "name": m,
            "recommended": (m == recommended),
            "size": spec.get("size", "Unknown"),
            "ram": spec.get("ram", "~2.5 GB RAM"),
            "desc": spec.get("desc", ""),
        })
    return {
        "online": ok,
        "models": models,
        "model_details": detailed_models,
        "recommended": recommended,
        "specs": OLLAMA_MODEL_SPECS,
    }


@app.post("/api/ai/test")
def test_provider_connection(req: AiTestRequest):
    """Test connection with specified AI provider."""
    return test_ai_connection(
        provider=req.provider,
        api_key=req.api_key,
        base_url=req.base_url,
        model=req.model,
    )


# ============================================================================
# Video Ingestion & Project Endpoints
# ============================================================================

@app.post("/api/probe")
def probe_video_endpoint(req: ProbeRequest):
    """Inspect and validate a Twitch or YouTube URL, or local video path."""
    url = req.url_or_path.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL or file path is required")

    try:
        source, platform, vid_id = get_source(url)
        meta = source.probe(url)
        return {
            "id": meta.id,
            "title": meta.title,
            "duration": meta.duration,
            "uploader": meta.uploader,
            "thumbnail": meta.thumbnail,
            "platform": meta.platform.value,
            "webpage_url": meta.webpage_url,
            "is_local": meta.is_local,
            "is_live": meta.is_live,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to probe video: {e}")


@app.get("/api/projects")
def get_projects():
    """List genuine user projects only (empty if none exist)."""
    return list_all_projects()


@app.post("/api/projects/create")
def create_new_project(req: CreateProjectRequest, background_tasks: BackgroundTasks):
    url_or_path = req.url_or_path.strip()
    if not url_or_path:
        raise HTTPException(status_code=400, detail="URL or file path is required")

    source, platform, vid_id = get_source(url_or_path)

    try:
        info = source.probe(url_or_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to probe video: {e}")

    title = req.title or info.title or "Gaming VOD"
    proj = create_project(
        title=title,
        url_or_path=url_or_path,
        platform=platform.value,
        video_id=vid_id or info.id,
    )

    # Initialize job progress
    _job_progress[proj.id] = {
        "step": "queued",
        "percent": 0.0,
        "message": f"Queued for {platform.value.capitalize()} download...",
    }

    def _download_task(p_id: str, src_url: str, duration: float | None):
        project = Project(p_id)
        meta = project.load_meta()
        try:
            # 1. Download video
            _job_progress[p_id] = {
                "step": "download_video",
                "percent": 5.0,
                "message": f"Downloading {platform.value.capitalize()} video streams...",
            }

            def _v_prog(pct):
                _job_progress[p_id] = {
                    "step": "download_video",
                    "percent": round(pct * 0.7, 1),
                    "message": f"Downloading video: {pct:.1f}%",
                }

            source.download_video(src_url, project.source_video, on_progress=_v_prog)

            # 2. Download chat replay
            _job_progress[p_id] = {
                "step": "download_chat",
                "percent": 75.0,
                "message": f"Retrieving {platform.value.capitalize()} chat replay...",
            }

            def _c_prog(pct, count):
                _job_progress[p_id] = {
                    "step": "download_chat",
                    "percent": round(75.0 + pct * 0.2, 1),
                    "message": f"Downloading chat ({count} msgs)...",
                }

            chat_res: ChatResult = source.download_chat(
                vid_id or p_id,
                project.chat_path,
                duration=duration,
                on_progress=_c_prog,
            )

            meta["status"] = "downloaded"
            meta["duration"] = duration or meta.get("duration", 0.0)
            meta["chat_status"] = chat_res.status.value
            meta["chat_message_count"] = chat_res.message_count
            meta["chat_detail"] = chat_res.detail
            project.save_meta(meta)

            _job_progress[p_id] = {
                "step": "ready_for_analysis",
                "percent": 100.0,
                "message": f"Download complete! ({chat_res.detail}) Ready for highlight detection.",
            }
        except Exception as err:
            meta["status"] = "error"
            meta["error"] = str(err)
            project.save_meta(meta)
            _job_progress[p_id] = {
                "step": "error",
                "percent": 0.0,
                "message": f"Download failed: {err}",
            }

    background_tasks.add_task(_download_task, proj.id, url_or_path, info.duration)
    return {"project_id": proj.id, "title": title, "platform": platform.value}


@app.post("/api/projects/create-demo")
def create_demo_project_endpoint():
    """Explicitly create an offline demo project from tests/fixtures. Never runs automatically."""
    try:
        proj = create_demo_project()
        meta = proj.load_meta()
        return {"project_id": proj.id, "title": meta.get("title", "Demo Project")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create demo project: {e}")


@app.get("/api/projects/{project_id}")
def get_project_details(project_id: str):
    proj = Project(project_id)
    if not proj.meta_path.is_file():
        raise HTTPException(status_code=404, detail="Project not found")

    meta = proj.load_meta()
    highlights = proj.load_highlights()
    exports = proj.list_exports()
    disk = proj.disk_usage()
    job = _job_progress.get(
        project_id,
        {
            "step": meta.get("status", "unknown"),
            "percent": 100.0 if meta.get("status") in ["downloaded", "ready"] else 0.0,
            "message": f"Project status: {meta.get('status', 'unknown')}",
        },
    )

    return {
        "meta": meta,
        "has_source": proj.source_video.is_file(),
        "has_chat": proj.chat_path.is_file(),
        "has_highlights": highlights is not None,
        "candidate_count": len(highlights.get("candidates", [])) if highlights else 0,
        "exports": exports,
        "disk_usage": disk,
        "job": job,
    }


@app.post("/api/projects/{project_id}/analyze")
def analyze_project(
    project_id: str,
    background_tasks: BackgroundTasks,
    req: AnalyzeProjectRequest | None = None,
):
    proj = Project(project_id)
    if not proj.source_video.is_file():
        raise HTTPException(
            status_code=400, detail="Source video not found. Ensure download is finished."
        )

    options = req or AnalyzeProjectRequest()

    meta = proj.load_meta()
    meta["status"] = "analyzing"
    proj.save_meta(meta)

    _job_progress[project_id] = {
        "step": "extract_audio",
        "percent": 10.0,
        "message": "Extracting 16kHz audio for dynamics analysis...",
    }

    def _analysis_task(p_id: str, opts: AnalyzeProjectRequest):
        project = Project(p_id)
        m = project.load_meta()
        try:
            # 1. Extract audio WAV
            extract_audio_wav(project.source_video, project.audio_path)
            _job_progress[p_id] = {
                "step": "detecting_facecam",
                "percent": 25.0,
                "message": "Detecting streamer webcam framing...",
            }

            # 2. Detect facecam
            fc_region = None
            try:
                fc_region = detect_facecam(project.source_video, m.get("duration", 60.0))
                if fc_region:
                    m["facecam_region"] = asdict(fc_region)
            except Exception:
                pass

            _job_progress[p_id] = {
                "step": "detecting_signals",
                "percent": 45.0,
                "message": "Analyzing audio dynamics, chat spikes, and AI candidates...",
            }

            # 3. Run multi-signal detection
            has_valid_chat = project.chat_path.is_file() and project.chat_path.stat().st_size > 30
            result = run_highlight_detection(
                wav_path=project.audio_path,
                chat_path=project.chat_path if has_valid_chat else None,
                top_n=opts.target_count or 6,
                target_count=opts.target_count or 5,
                min_duration=opts.min_duration,
                max_duration=opts.max_duration,
                sensitivity=opts.sensitivity,
                focus_mode=opts.focus_mode,
                facecam_region=m.get("facecam_region"),
            )

            # 4. Save highlights
            highlights_dict = {
                "duration": result.duration,
                "signals_present": result.signals_present,
                "reasons_summary": result.reasons_summary,
                "hype_curve": result.hype_curve,
                "candidates": [asdict(c) for c in result.candidates],
                "analysis_options": _model_to_dict(opts),
            }
            project.save_highlights(highlights_dict)

            m["status"] = "ready"
            m["duration"] = result.duration
            project.save_meta(m)
            _job_progress[p_id] = {
                "step": "ready",
                "percent": 100.0,
                "message": f"Detection complete! Found {len(result.candidates)} highlights.",
            }
        except Exception as err:
            m["status"] = "error"
            m["error"] = str(err)
            project.save_meta(m)
            _job_progress[p_id] = {
                "step": "error",
                "percent": 0.0,
                "message": f"Analysis failed: {err}",
            }

    background_tasks.add_task(_analysis_task, project_id, options)
    return {"message": "Highlight detection started"}


@app.get("/api/projects/{project_id}/highlights")
def get_highlights(project_id: str):
    proj = Project(project_id)
    highlights = proj.load_highlights()
    if not highlights:
        raise HTTPException(status_code=404, detail="Highlights not generated yet")
    return highlights


@app.get("/api/projects/{project_id}/video")
def stream_source_video(project_id: str, request: Request):
    """Stream source video with HTTP range requests for seamless timeline seeking."""
    proj = Project(project_id)
    if not proj.source_video.is_file():
        raise HTTPException(status_code=404, detail="Source video not found")

    path = proj.source_video
    file_size = path.stat().st_size
    range_header = request.headers.get("Range")

    if not range_header:
        return FileResponse(path, media_type="video/mp4")

    # Parse byte range (e.g. "bytes=1024-2048")
    range_match = range_header.strip().lower().replace("bytes=", "").split("-")
    start = int(range_match[0]) if range_match[0] else 0
    end = int(range_match[1]) if len(range_match) > 1 and range_match[1] else file_size - 1
    end = min(end, file_size - 1)

    if start >= file_size or start > end:
        return Response(
            status_code=416,
            headers={"Content-Range": f"bytes */{file_size}"},
            media_type="text/plain",
        )

    chunk_size = end - start + 1

    def iter_file():
        with open(path, "rb") as f:
            f.seek(start)
            remaining = chunk_size
            while remaining > 0:
                read_len = min(65536, remaining)
                data = f.read(read_len)
                if not data:
                    break
                remaining -= len(data)
                yield data

    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(chunk_size),
    }
    return StreamingResponse(
        iter_file(), status_code=206, headers=headers, media_type="video/mp4"
    )


@app.get("/api/projects/{project_id}/frame")
def get_video_frame(project_id: str, time: float = Query(0.0)):
    """Extract JPEG frame snapshot for candidate preview / facecam setup."""
    proj = Project(project_id)
    if not proj.source_video.is_file():
        raise HTTPException(status_code=404, detail="Source video not found")

    frame = extract_frame_image(proj.source_video, time)
    if frame is None:
        raise HTTPException(status_code=500, detail="Could not extract video frame")

    if cv2 is None:
        raise HTTPException(status_code=500, detail="OpenCV (cv2) is not available")

    success, encoded_jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not success:
        raise HTTPException(status_code=500, detail="JPEG encoding failed")

    return Response(content=encoded_jpg.tobytes(), media_type="image/jpeg")


@app.post("/api/projects/{project_id}/clips/{clip_id}/transcribe")
def transcribe_clip(project_id: str, clip_id: str):
    """Transcribe specific clip window with faster-whisper INT8."""
    proj = Project(project_id)
    highlights = proj.load_highlights()
    if not highlights:
        raise HTTPException(status_code=400, detail="Highlights not found")

    cand = next((c for c in highlights.get("candidates", []) if c["id"] == clip_id), None)
    if not cand:
        raise HTTPException(status_code=404, detail="Clip candidate not found")

    setting = proj.load_clip_setting(clip_id) or {}
    start_s = float(setting.get("start_s", cand["start"]))
    end_s = float(setting.get("end_s", cand["end"]))

    if not proj.audio_path.is_file():
        if not proj.source_video.is_file():
            raise HTTPException(status_code=400, detail="Source video and audio not found")
        extract_audio_wav(proj.source_video, proj.audio_path)

    segments = transcribe_window(
        wav_path=proj.audio_path,
        start_s=start_s,
        end_s=end_s,
        model_size="tiny",
    )

    setting["segments"] = [asdict(s) for s in segments]
    setting["full_text"] = " ".join(s.text for s in segments)
    proj.save_clip_setting(clip_id, setting)

    return {
        "clip_id": clip_id,
        "segments": setting["segments"],
        "full_text": setting["full_text"],
    }


@app.get("/api/projects/{project_id}/clips/{clip_id}/settings")
def get_clip_setting(project_id: str, clip_id: str):
    proj = Project(project_id)
    setting = proj.load_clip_setting(clip_id)
    if not setting:
        meta = proj.load_meta()
        highlights = proj.load_highlights() or {}
        cand = next((c for c in highlights.get("candidates", []) if c["id"] == clip_id), None)
        fc = meta.get("facecam_region") or {"x": 0.72, "y": 0.06, "w": 0.24, "h": 0.28}

        setting = {
            "layout": "split" if fc else "crop",
            "aspect_ratio": "9:16",
            "facecam_x": float(fc.get("x", 0.72)),
            "facecam_y": float(fc.get("y", 0.06)),
            "facecam_w": float(fc.get("w", 0.24)),
            "facecam_h": float(fc.get("h", 0.28)),
            "gameplay_pan_x": 0.5,
            "zoom_factor": 1.0,
            "start_s": float(cand["start"]) if cand else 0.0,
            "end_s": float(cand["end"]) if cand else 30.0,
            "enable_subtitles": True,
            "subtitle_style": "bold",
            "font_size": 68,
            "highlight_color": "&H006AB5D9",
            "clip_title": cand.get("suggested_title", "Highlight") if cand else "Highlight",
        }

    # Ensure sections exist (AI edit suggestions populated)
    if "sections" not in setting or not setting["sections"]:
        meta = proj.load_meta()
        highlights = proj.load_highlights() or {}
        cand = next((c for c in highlights.get("candidates", []) if c["id"] == clip_id), None)
        fc = meta.get("facecam_region") or {"x": 0.72, "y": 0.06, "w": 0.24, "h": 0.28}
        if cand and cand.get("edit_suggestions"):
            setting["sections"] = cand["edit_suggestions"]
        elif cand:
            start_val = float(setting.get("start_s", cand["start"]))
            end_val = float(setting.get("end_s", cand["end"]))
            peak_val = float(cand.get("peak", start_val + (end_val - start_val) / 2))
            setting["sections"] = generate_ai_edit_suggestions(
                start=start_val,
                end=end_val,
                peak=peak_val,
                reasons=cand.get("reasons", []),
                # pyrefly: ignore[bad-argument-type]
                transcript_text=setting.get("full_text", ""),
                facecam_region=fc,
            )
        proj.save_clip_setting(clip_id, setting)

    return setting


@app.post("/api/projects/{project_id}/clips/{clip_id}/ai-edit-suggestions")
def get_or_generate_clip_edit_suggestions(project_id: str, clip_id: str):
    """Generate or re-generate structured AI multi-section editing arrangement."""
    proj = Project(project_id)
    highlights = proj.load_highlights() or {}
    cand = next((c for c in highlights.get("candidates", []) if c["id"] == clip_id), None)
    if not cand:
        raise HTTPException(status_code=404, detail="Candidate not found")
    meta = proj.load_meta()
    setting = proj.load_clip_setting(clip_id) or {}

    start_s = float(setting.get("start_s", cand["start"]))
    end_s = float(setting.get("end_s", cand["end"]))
    fc = meta.get("facecam_region") or {"x": 0.72, "y": 0.06, "w": 0.24, "h": 0.28}

    suggestions = generate_ai_edit_suggestions(
        start=start_s,
        end=end_s,
        peak=float(cand.get("peak", start_s + (end_s - start_s) / 2)),
        reasons=cand.get("reasons", []),
        transcript_text=setting.get("full_text", ""),
        facecam_region=fc,
    )

    setting["sections"] = suggestions
    proj.save_clip_setting(clip_id, setting)
    return {"clip_id": clip_id, "sections": suggestions}


@app.post("/api/projects/{project_id}/clips/{clip_id}/settings")
def save_clip_setting(project_id: str, clip_id: str, req: SaveClipSettingRequest):
    proj = Project(project_id)
    setting = proj.load_clip_setting(clip_id) or {}
    setting.update(_model_to_dict(req))
    proj.save_clip_setting(clip_id, setting)
    return {"status": "saved", "clip_id": clip_id}


@app.post("/api/projects/{project_id}/clips/{clip_id}/render")
def trigger_render_clip(
    project_id: str,
    clip_id: str,
    req: RenderClipRequest | None = None,
):
    if req is None:
        req = RenderClipRequest()

    proj = Project(project_id)
    if not proj.source_video.is_file():
        raise HTTPException(status_code=400, detail="Source video not found")

    highlights = proj.load_highlights() or {}
    cand = next((c for c in highlights.get("candidates", []) if c["id"] == clip_id), None)

    # Load or use passed settings
    setting = proj.load_clip_setting(clip_id) or {}
    if req.setting:
        setting.update(_model_to_dict(req.setting))

    start_s = float(setting.get("start_s", cand["start"] if cand else 0.0))
    end_s = float(setting.get("end_s", cand["end"] if cand else 30.0))
    clip_title = str(
        setting.get("clip_title")
        or (cand.get("suggested_title") if cand else clip_id)
        or clip_id
    )

    clean_title = "".join(c for c in clip_title if c.isalnum() or c in " _-").strip().replace(
        " ", "_"
    )
    output_filename = f"{clip_id}_{clean_title[:35]}.mp4"
    output_path = proj.export_dir / output_filename

    # Generate ASS subtitle file if enabled
    ass_path = None
    if setting.get("enable_subtitles", True):
        segments_data = setting.get("segments")
        if not segments_data and proj.audio_path.is_file():
            try:
                segments_obj = transcribe_window(
                    proj.audio_path, start_s, end_s, model_size="tiny"
                )
                setting["segments"] = [asdict(s) for s in segments_obj]
                proj.save_clip_setting(clip_id, setting)
                segments_data = setting["segments"]
            except Exception:
                segments_data = []

        if segments_data:
            reconstructed_segs = []
            for sd in segments_data:
                if not isinstance(sd, dict):
                    continue
                words = [
                    WordTiming(
                        start=float(w.get("start", 0.0)),
                        end=float(w.get("end", 0.0)),
                        word=str(w.get("word", "")),
                    )
                    # pyrefly: ignore[not-iterable]
                    for w in sd.get("words", [])
                    if isinstance(w, dict)
                ]
                reconstructed_segs.append(
                    SubtitleSegment(
                        # pyrefly: ignore[bad-argument-type]
                        start=float(sd.get("start", 0.0)),
                        # pyrefly: ignore[bad-argument-type]
                        end=float(sd.get("end", 0.0)),
                        text=str(sd.get("text", "")),
                        words=words,
                    )
                )

            ass_path = proj.cache_dir / f"{clip_id}_subs.ass"
            raw_style = str(setting.get("subtitle_style", "bold")).lower()
            valid_styles: tuple[Literal["bold", "karaoke", "clean", "minimal"], ...] = (
                "bold",
                "karaoke",
                "clean",
                "minimal",
            )
            chosen_style: Any = raw_style if raw_style in valid_styles else "bold"

            font_size_val = 68
            try:
                font_size_val = int(float(setting.get("font_size", 68)))
            except (ValueError, TypeError):
                pass

            generate_ass_subtitles(
                segments=reconstructed_segs,
                output_path=ass_path,
                style=chosen_style,
                font_size=font_size_val,
                highlight_color=str(setting.get("highlight_color", "&H006AB5D9")),
            )

    # Configure render options
    raw_layout = str(setting.get("layout", "split")).lower()
    valid_layouts: tuple[Literal["split", "fit", "crop", "pip", "custom"], ...] = (
        "split",
        "fit",
        "crop",
        "pip",
        "custom",
    )
    chosen_layout: Any = raw_layout if raw_layout in valid_layouts else "split"

    opts = RenderOptions(
        layout=chosen_layout,
        aspect_ratio=str(setting.get("aspect_ratio", "9:16")),
        facecam_x=float(setting.get("facecam_x", 0.72)),
        facecam_y=float(setting.get("facecam_y", 0.06)),
        facecam_w=float(setting.get("facecam_w", 0.24)),
        facecam_h=float(setting.get("facecam_h", 0.28)),
        gameplay_pan_x=float(setting.get("gameplay_pan_x", 0.5)),
        zoom_factor=float(setting.get("zoom_factor", 1.0)),
        sections=setting.get("sections"),
        enable_subtitles=bool(setting.get("enable_subtitles", True) and ass_path is not None),
        ass_path=ass_path,
    )

    try:
        render_clip(
            source_video=proj.source_video,
            output_path=output_path,
            start_s=start_s,
            end_s=end_s,
            opts=opts,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Rendering failed: {e}")

    final_path = output_path
    if req.destination_path and req.destination_path.strip():
        dest = Path(req.destination_path.strip())
        if dest.is_dir():
            dest = dest / output_filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(output_path, dest)
            final_path = dest
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to copy rendered video to destination: {e}")

    return {
        "status": "rendered",
        "output_path": str(final_path.resolve()),
        "filename": final_path.name,
        "size_mb": round(final_path.stat().st_size / (1024 * 1024), 2),
    }


# ============================================================================
# Export & Save As Endpoints
# ============================================================================

@app.post("/api/exports/{project_id}/{clip_id}/save-dialog")
def open_native_save_dialog(project_id: str, clip_id: str):
    """Open Windows native Save As dialog to save the rendered MP4 to a user-chosen location."""
    proj = Project(project_id)
    exports = proj.list_exports()

    target_file = None
    for exp in exports:
        if exp["name"].startswith(f"{clip_id}_") or exp["name"].startswith(clip_id):
            target_file = Path(exp["path"])
            break

    if not target_file or not target_file.is_file():
        raise HTTPException(
            status_code=404,
            detail="Rendered clip export not found. Please render the clip first before saving.",
        )

    meta = proj.load_meta()
    clean_title = "".join(c for c in meta.get("title", "Clip") if c.isalnum() or c in " _-").strip().replace(" ", "_")
    default_filename = f"{clean_title[:30]}_{clip_id}.mp4"

    # Execute Tkinter dialog in an isolated subprocess to guarantee thread-safety and foreground window focus
    script = f"""
import sys
import tkinter as tk
from tkinter import filedialog

root = tk.Tk()
root.withdraw()
root.attributes('-topmost', True)
dest = filedialog.asksaveasfilename(
    title='Save 9:16 Highlight Clip As',
    initialfile={repr(default_filename)},
    defaultextension='.mp4',
    filetypes=[('MP4 Video', '*.mp4'), ('All Files', '*.*')]
)
root.destroy()
if dest:
    sys.stdout.write(dest)
"""
    try:
        proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=90)
        chosen_dest = proc.stdout.strip()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to open Save As dialog: {e}")

    if not chosen_dest:
        return {"status": "cancelled", "message": "Save As was cancelled."}

    dest_path = Path(chosen_dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(target_file, dest_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to copy video to {dest_path}: {e}")

    return {
        "status": "saved",
        "path": str(dest_path.resolve()),
        "filename": dest_path.name,
        "size_mb": round(dest_path.stat().st_size / (1024 * 1024), 2),
    }


@app.post("/api/system/browse-save-path")
def browse_save_path(default_filename: str = Query("clip.mp4")):
    """Open Windows native Save As dialog to select export path before or during rendering."""
    clean_default = Path(default_filename).name or "clip.mp4"
    script = f"""
import sys
import tkinter as tk
from tkinter import filedialog

root = tk.Tk()
root.withdraw()
root.attributes('-topmost', True)
dest = filedialog.asksaveasfilename(
    title='Select Export Destination',
    initialfile={repr(clean_default)},
    defaultextension='.mp4',
    filetypes=[('MP4 Video', '*.mp4'), ('All Files', '*.*')]
)
root.destroy()
if dest:
    sys.stdout.write(dest)
"""
    try:
        proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=90)
        chosen_dest = proc.stdout.strip()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to open Save As dialog: {e}")

    if not chosen_dest:
        return {"cancelled": True, "path": "", "filename": ""}

    return {"cancelled": False, "path": chosen_dest, "filename": Path(chosen_dest).name}


@app.post("/api/system/open-folder")
def open_system_folder(req: OpenFolderRequest):
    """Open Windows Explorer with the specified file or folder selected."""
    target = Path(req.path.strip())
    if not target.exists():
        raise HTTPException(status_code=404, detail="Path does not exist on disk")

    if IS_WINDOWS:
        try:
            if target.is_file():
                subprocess.Popen(f'explorer /select,"{str(target.resolve())}"')
            else:
                subprocess.Popen(f'explorer "{str(target.resolve())}"')
            return {"status": "opened", "path": str(target.resolve())}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to open folder: {e}")

    return {"status": "not_supported", "message": "Only supported on Windows desktop"}


@app.post("/api/exports/{project_id}/{clip_id}/save-to-path")
def save_export_to_path(project_id: str, clip_id: str, req: SaveToPathRequest):
    """Save rendered clip to an explicitly provided file path."""
    proj = Project(project_id)
    exports = proj.list_exports()

    target_file = None
    for exp in exports:
        if exp["name"].startswith(f"{clip_id}_") or exp["name"].startswith(clip_id):
            target_file = Path(exp["path"])
            break

    if not target_file or not target_file.is_file():
        raise HTTPException(status_code=404, detail="Rendered clip export not found")

    dest_path = Path(req.destination_path.strip())
    if dest_path.is_dir():
        dest_path = dest_path / target_file.name

    if dest_path.is_file() and not req.overwrite:
        raise HTTPException(
            status_code=409,
            detail=f"File already exists at {dest_path}. Confirm overwrite to replace.",
        )

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(target_file, dest_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save video: {e}")

    return {
        "status": "saved",
        "path": str(dest_path.resolve()),
        "filename": dest_path.name,
        "size_mb": round(dest_path.stat().st_size / (1024 * 1024), 2),
    }


@app.post("/api/system/browse-save-path")
def browse_save_path(default_filename: str = Query("clip.mp4")):
    """Open Windows native Save As dialog to select export path before or during rendering."""
    clean_default = Path(default_filename).name or "clip.mp4"
    script = f"""
import sys
import tkinter as tk
from tkinter import filedialog

root = tk.Tk()
root.withdraw()
root.attributes('-topmost', True)
dest = filedialog.asksaveasfilename(
    title='Select Export Destination',
    initialfile={repr(clean_default)},
    defaultextension='.mp4',
    filetypes=[('MP4 Video', '*.mp4'), ('All Files', '*.*')]
)
root.destroy()
if dest:
    sys.stdout.write(dest)
"""
    try:
        proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=90)
        chosen_dest = proc.stdout.strip()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to open Save As dialog: {e}")

    if not chosen_dest:
        return {"cancelled": True, "path": "", "filename": ""}

    return {"cancelled": False, "path": chosen_dest, "filename": Path(chosen_dest).name}


@app.post("/api/system/open-folder")
def open_system_folder(req: OpenFolderRequest):
    """Open Windows Explorer with the specified file or folder selected."""
    target = Path(req.path.strip())
    if not target.exists():
        raise HTTPException(status_code=404, detail="Path does not exist on disk")

    if IS_WINDOWS:
        try:
            if target.is_file():
                subprocess.Popen(f'explorer /select,"{str(target.resolve())}"')
            else:
                subprocess.Popen(f'explorer "{str(target.resolve())}"')
            return {"status": "opened", "path": str(target.resolve())}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to open folder: {e}")

    return {"status": "not_supported", "message": "Only supported on Windows desktop"}


@app.post("/api/projects/{project_id}/cleanup")
def cleanup_project_storage(project_id: str, req: CleanupRequest | None = None):
    if req is None:
        req = CleanupRequest()
    proj = Project(project_id)
    res = proj.cleanup(delete_source=req.delete_source, delete_cache=req.delete_cache)
    return res


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str):
    """Permanently delete a project folder and all its cached data."""
    import shutil
    proj = Project(project_id)
    if not proj.dir.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        shutil.rmtree(proj.dir, ignore_errors=True)
        # Also remove empty export dir if present and empty
        if proj.export_dir.exists() and not any(proj.export_dir.iterdir()):
            proj.export_dir.rmdir()
        return {"success": True, "deleted": project_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delete failed: {e}")


@app.get("/api/exports/{project_id}/{filename}")
def download_export_clip(project_id: str, filename: str, download: bool = False):
    proj = Project(project_id)
    path = proj.export_dir / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Exported file not found")

    headers = {}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'

    return FileResponse(path, media_type="video/mp4", filename=filename, headers=headers)


# Mount static frontend
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    print("=" * 65)
    print(" 🎮 GTA CLIPPER FASTAPI BACKEND SERVER")
    print(" 🚀 Starting locally on http://127.0.0.1:8000")
    print("=" * 65)
    uvicorn.run(app, host="127.0.0.1", port=8000)
