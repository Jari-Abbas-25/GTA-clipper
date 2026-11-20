"""FastAPI Backend Server for GTA Clipper.

Provides REST and streaming endpoints for:
- Twitch VOD & Chat downloading
- Multi-signal highlight detection & Hype Map
- Video streaming with HTTP Range requests
- Candidate-window faster-whisper transcription
- Real-time 9:16 Canvas editor state persistence
- FFmpeg 1080x1920 vertical MP4 export
- Storage management & cleanup
"""

from __future__ import annotations

import json
import os
import shutil
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

from .ai_evaluator import is_ollama_available
from .audio_signals import extract_audio_wav
from .config import CPU_CORES, EXPORTS_DIR, FRONTEND_DIR, IS_WINDOWS, PROJECTS_DIR
from .facecam_detector import detect_facecam, extract_frame_image
from .highlight_engine import run_highlight_detection
from .renderer import RenderOptions, render_clip
from .storage import Project, create_project, list_all_projects
from .transcriber import (
    FASTER_WHISPER_AVAILABLE,
    SubtitleSegment,
    WordTiming,
    generate_ass_subtitles,
    transcribe_window,
)
from .twitch_downloader import (
    download_twitch_chat,
    download_video,
    extract_twitch_id,
    probe_video_info,
)

app = FastAPI(title="GTA Clipper API", version="1.0.0")

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


class CreateProjectRequest(BaseModel):
    url_or_path: str
    title: str | None = None


class SaveClipSettingRequest(BaseModel):
    layout: str = "split"
    facecam_x: float = 0.72
    facecam_y: float = 0.06
    facecam_w: float = 0.24
    facecam_h: float = 0.28
    gameplay_pan_x: float = 0.5
    zoom_factor: float = 1.0
    start_s: float | None = None
    end_s: float | None = None
    enable_subtitles: bool = True
    subtitle_style: str = "bold"
    font_size: int = 68
    highlight_color: str = "&H006AB5D9"
    clip_title: str | None = None


class RenderClipRequest(BaseModel):
    setting: SaveClipSettingRequest | None = None


class CleanupRequest(BaseModel):
    delete_source: bool = False
    delete_cache: bool = True


@app.get("/api/status")
def get_system_status():
    ollama_ok, ollama_model = is_ollama_available()
    return {
        "status": "online",
        "platform": "windows" if IS_WINDOWS else "other",
        "cpu_cores": CPU_CORES,
        "ffmpeg_available": bool(shutil.which("ffmpeg")),
        "whisper_available": FASTER_WHISPER_AVAILABLE,
        "ollama_available": ollama_ok,
        "ollama_model": ollama_model,
        "projects_dir": str(PROJECTS_DIR.resolve()),
        "exports_dir": str(EXPORTS_DIR.resolve()),
    }


@app.get("/api/projects")
def get_projects():
    return list_all_projects()


@app.post("/api/projects/create")
def create_new_project(req: CreateProjectRequest, background_tasks: BackgroundTasks):
    url_or_path = req.url_or_path.strip()
    if not url_or_path:
        raise HTTPException(status_code=400, detail="URL or file path is required")

    # Support sample demo shortcut
    if "sample" in url_or_path.lower():
        sample_path = PROJECTS_DIR / "GTA_6_Heist___Cop_Chase_Highlights" / "source.mp4"
        if sample_path.is_file():
            url_or_path = str(sample_path.resolve())

    try:
        info = probe_video_info(url_or_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to probe video: {e}")

    title = req.title or info.get("title") or "Gaming VOD"
    proj = create_project(title, url_or_path)

    # Initialize job progress
    _job_progress[proj.id] = {
        "step": "queued",
        "percent": 0.0,
        "message": "Queued for download...",
    }

    def _download_task(p_id: str, source: str, duration: float | None):
        project = Project(p_id)
        meta = project.load_meta()
        try:
            # 1. Download video
            _job_progress[p_id] = {
                "step": "download_video",
                "percent": 5.0,
                "message": "Downloading video...",
            }

            def _v_prog(pct):
                _job_progress[p_id] = {
                    "step": "download_video",
                    "percent": round(pct * 0.7, 1),
                    "message": f"Downloading video: {pct:.1f}%",
                }

            download_video(source, project.source_video, on_progress=_v_prog)

            # 2. Download Twitch chat if applicable
            twitch_id = extract_twitch_id(source)
            if twitch_id:
                _job_progress[p_id] = {
                    "step": "download_chat",
                    "percent": 75.0,
                    "message": "Downloading Twitch chat replay...",
                }

                def _c_prog(pct, count):
                    _job_progress[p_id] = {
                        "step": "download_chat",
                        "percent": round(75.0 + pct * 0.2, 1),
                        "message": f"Downloading Twitch chat ({count} msgs)...",
                    }

                download_twitch_chat(
                    twitch_id, project.chat_path, duration=duration, on_progress=_c_prog
                )

            meta["status"] = "downloaded"
            meta["duration"] = duration or 0.0
            project.save_meta(meta)
            _job_progress[p_id] = {
                "step": "ready_for_analysis",
                "percent": 100.0,
                "message": "Download complete! Ready for analysis.",
            }
        except Exception as err:
            meta["status"] = "error"
            meta["error"] = str(err)
            project.save_meta(meta)
            _job_progress[p_id] = {
                "step": "error",
                "percent": 0.0,
                "message": f"Error: {err}",
            }

    background_tasks.add_task(_download_task, proj.id, url_or_path, info.get("duration"))
    return {"project_id": proj.id, "title": title}


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
def analyze_project(project_id: str, background_tasks: BackgroundTasks):
    proj = Project(project_id)
    if not proj.source_video.is_file():
        raise HTTPException(
            status_code=400, detail="Source video not found. Ensure download is finished."
        )

    meta = proj.load_meta()
    meta["status"] = "analyzing"
    proj.save_meta(meta)

    _job_progress[project_id] = {
        "step": "extract_audio",
        "percent": 10.0,
        "message": "Extracting audio for analysis...",
    }

    def _analysis_task(p_id: str):
        project = Project(p_id)
        m = project.load_meta()
        try:
            # 1. Extract audio WAV
            extract_audio_wav(project.source_video, project.audio_path)
            _job_progress[p_id] = {
                "step": "detecting_signals",
                "percent": 35.0,
                "message": "Analyzing audio dynamics and chat spikes...",
            }

            # 2. Run multi-signal detection
            result = run_highlight_detection(
                wav_path=project.audio_path,
                chat_path=project.chat_path if project.chat_path.is_file() else None,
                top_n=15,
            )

            # 3. Detect facecam
            _job_progress[p_id] = {
                "step": "detecting_facecam",
                "percent": 85.0,
                "message": "Detecting streamer webcam region...",
            }
            fc_region = detect_facecam(project.source_video, result.duration)
            if fc_region:
                m["facecam_region"] = asdict(fc_region)

            # 4. Save highlights
            highlights_dict = {
                "duration": result.duration,
                "signals_present": result.signals_present,
                "reasons_summary": result.reasons_summary,
                "hype_curve": result.hype_curve,
                "candidates": [asdict(c) for c in result.candidates],
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

    background_tasks.add_task(_analysis_task, project_id)
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

    # Use custom start/end if saved by user
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

    # Save transcription to clip setting
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
        # Default settings based on candidate and project facecam
        meta = proj.load_meta()
        highlights = proj.load_highlights() or {}
        cand = next((c for c in highlights.get("candidates", []) if c["id"] == clip_id), None)
        fc = meta.get("facecam_region") or {"x": 0.72, "y": 0.06, "w": 0.24, "h": 0.28}

        setting = {
            "layout": "split" if fc else "crop",
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
    return setting


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

    # Sanitize title for filename
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
            # Transcribe now if not done yet
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
                    for w in sd.get("words", [])
                    if isinstance(w, dict)
                ]
                reconstructed_segs.append(
                    SubtitleSegment(
                        start=float(sd.get("start", 0.0)),
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
    valid_layouts: tuple[Literal["split", "fit", "crop", "pip"], ...] = (
        "split",
        "fit",
        "crop",
        "pip",
    )
    chosen_layout: Any = raw_layout if raw_layout in valid_layouts else "split"

    opts = RenderOptions(
        layout=chosen_layout,
        facecam_x=float(setting.get("facecam_x", 0.72)),
        facecam_y=float(setting.get("facecam_y", 0.06)),
        facecam_w=float(setting.get("facecam_w", 0.24)),
        facecam_h=float(setting.get("facecam_h", 0.28)),
        gameplay_pan_x=float(setting.get("gameplay_pan_x", 0.5)),
        zoom_factor=float(setting.get("zoom_factor", 1.0)),
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

    return {
        "status": "rendered",
        "output_path": str(output_path.resolve()),
        "filename": output_filename,
        "size_mb": round(output_path.stat().st_size / (1024 * 1024), 2),
    }


@app.post("/api/projects/{project_id}/cleanup")
def cleanup_project_storage(project_id: str, req: CleanupRequest | None = None):
    if req is None:
        req = CleanupRequest()
    proj = Project(project_id)
    res = proj.cleanup(delete_source=req.delete_source, delete_cache=req.delete_cache)
    return res


@app.get("/api/exports/{project_id}/{filename}")
def download_export_clip(project_id: str, filename: str):
    proj = Project(project_id)
    path = proj.export_dir / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Exported file not found")
    return FileResponse(path, media_type="video/mp4", filename=filename)


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
