"""FFmpeg 9:16 Vertical Video Renderer.

Renders 1080x1920 MP4 clips for YouTube Shorts, TikTok, and Instagram Reels.
Supports:
1. Split-screen layout (Facecam top 40% + Gameplay bottom 60%)
2. Fit layout (16:9 gameplay centered with blurred background fill)
3. Full crop layout (9:16 cover crop with pan & zoom)
4. Picture-in-Picture layout (Full gameplay + floating facecam box)
5. Burned-in ASS subtitles (with active word highlights)
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from .config import EXPORT_H, EXPORT_W, FFMPEG_PATH, SPLIT_FACE_H, SPLIT_GAME_H


@dataclass
class RenderOptions:
    layout: Literal["split", "fit", "crop", "pip"] = "split"
    # Facecam normalized coords 0..1
    facecam_x: float = 0.72
    facecam_y: float = 0.06
    facecam_w: float = 0.24
    facecam_h: float = 0.28
    # Framing & zoom
    gameplay_pan_x: float = 0.5  # 0 = left, 0.5 = center, 1.0 = right
    zoom_factor: float = 1.0      # 1.0x to 2.5x
    # Subtitles
    enable_subtitles: bool = True
    ass_path: Path | None = None
    # Encoding
    crf: int = 20
    preset: str = "veryfast"


def get_video_dimensions(video_path: Path) -> tuple[int, int]:
    """Get video width and height using ffprobe."""
    from .config import FFPROBE_PATH
    cmd = [
        FFPROBE_PATH, "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=s=x:p=0",
        str(video_path)
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        w_str, h_str = res.stdout.strip().split("x")
        return int(w_str), int(h_str)
    except Exception:
        return 1920, 1080


def build_filter_graph(
    opts: RenderOptions,
    src_w: int,
    src_h: int
) -> str:
    """Construct FFmpeg filter_complex graph for selected layout."""
    filters = []

    # ASS subtitle filter escaping for FFmpeg
    ass_filter = ""
    if opts.enable_subtitles and opts.ass_path and opts.ass_path.is_file():
        # FFmpeg on Windows requires forward slashes and escaped colons in filter paths
        escaped_ass = str(opts.ass_path.resolve()).replace("\\", "/").replace(":", "\\:")
        ass_filter = f",ass=filename='{escaped_ass}'"

    if opts.layout == "split":
        # 1. Facecam top panel (1080x768)
        cx = max(0, int(opts.facecam_x * src_w))
        cy = max(0, int(opts.facecam_y * src_h))
        cw = max(32, min(src_w - cx, int(opts.facecam_w * src_w)))
        ch = max(32, min(src_h - cy, int(opts.facecam_h * src_h)))

        cam_filter = (
            f"[0:v]crop={cw}:{ch}:{cx}:{cy},"
            f"scale={EXPORT_W}:{SPLIT_FACE_H}:force_original_aspect_ratio=increase,"
            f"crop={EXPORT_W}:{SPLIT_FACE_H}[cam];"
        )
        filters.append(cam_filter)

        # 2. Gameplay bottom panel (1080x1152)
        # Apply horizontal pan to gameplay if desired
        game_w = int(src_w / opts.zoom_factor)
        game_h = int(src_h / opts.zoom_factor)
        gx = max(0, min(src_w - game_w, int(opts.gameplay_pan_x * (src_w - game_w))))
        gy = max(0, (src_h - game_h) // 2)

        game_filter = (
            f"[0:v]crop={game_w}:{game_h}:{gx}:{gy},"
            f"scale={EXPORT_W}:{SPLIT_GAME_H}:force_original_aspect_ratio=increase,"
            f"crop={EXPORT_W}:{SPLIT_GAME_H}[game];"
        )
        filters.append(game_filter)

        # 3. Stack vertically + burn subtitles
        filters.append(f"[cam][game]vstack=inputs=2[v_stacked];")
        filters.append(f"[v_stacked]null{ass_filter}[v_out]")

    elif opts.layout == "fit":
        # Centered 16:9 with blurred background
        fg_h = int(EXPORT_W * (src_h / src_w))  # ~608px
        filters.append(
            f"[0:v]scale={EXPORT_W}:{EXPORT_H}:force_original_aspect_ratio=increase,"
            f"crop={EXPORT_W}:{EXPORT_H},boxblur=25:12[bg];"
        )
        filters.append(f"[0:v]scale={EXPORT_W}:{fg_h}[fg];")
        filters.append(f"[bg][fg]overlay=(W-w)/2:(H-h)/2[v_fit];")
        filters.append(f"[v_fit]null{ass_filter}[v_out]")

    elif opts.layout == "crop":
        # 9:16 full-screen cover crop
        target_aspect = EXPORT_W / EXPORT_H  # 9/16 = 0.5625
        crop_h = int(src_h / opts.zoom_factor)
        crop_w = int(crop_h * target_aspect)
        if crop_w > src_w:
            crop_w = src_w
            crop_h = int(crop_w / target_aspect)

        cx = max(0, min(src_w - crop_w, int(opts.gameplay_pan_x * (src_w - crop_w))))
        cy = max(0, (src_h - crop_h) // 2)

        filters.append(
            f"[0:v]crop={crop_w}:{crop_h}:{cx}:{cy},"
            f"scale={EXPORT_W}:{EXPORT_H}[v_crop];"
        )
        filters.append(f"[v_crop]null{ass_filter}[v_out]")

    elif opts.layout == "pip":
        # Picture-in-picture: Gameplay base + floating webcam box
        pip_w = int(EXPORT_W * opts.facecam_w * 1.5)
        pip_h = int(EXPORT_H * opts.facecam_h * 1.0)
        pip_x = int(EXPORT_W * opts.facecam_x)
        pip_y = int(EXPORT_H * opts.facecam_y)

        cx = max(0, int(opts.facecam_x * src_w))
        cy = max(0, int(opts.facecam_y * src_h))
        cw = max(32, min(src_w - cx, int(opts.facecam_w * src_w)))
        ch = max(32, min(src_h - cy, int(opts.facecam_h * src_h)))

        # Base 9:16 full crop or fit
        filters.append(
            f"[0:v]scale={EXPORT_W}:{EXPORT_H}:force_original_aspect_ratio=increase,"
            f"crop={EXPORT_W}:{EXPORT_H}[base];"
        )
        filters.append(
            f"[0:v]crop={cw}:{ch}:{cx}:{cy},"
            f"scale={pip_w}:{pip_h}:force_original_aspect_ratio=increase,"
            f"crop={pip_w}:{pip_h}[pip_cam];"
        )
        filters.append(f"[base][pip_cam]overlay={pip_x}:{pip_y}[v_pip];")
        filters.append(f"[v_pip]null{ass_filter}[v_out]")

    return "".join(filters)


def render_clip(
    source_video: Path,
    output_path: Path,
    start_s: float,
    end_s: float,
    opts: RenderOptions,
    on_progress: Callable[[float], None] | None = None
) -> Path:
    """Render 1080x1920 MP4 clip applying layouts, trims, and burned subtitles."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output_path.with_suffix(".part.mp4")

    src_w, src_h = get_video_dimensions(source_video)
    duration = end_s - start_s
    filter_graph = build_filter_graph(opts, src_w, src_h)

    cmd = [
        FFMPEG_PATH, "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{start_s:.3f}",
        "-to", f"{end_s:.3f}",
        "-i", str(source_video),
        "-filter_complex", filter_graph,
        "-map", "[v_out]",
        "-map", "0:a:0?",
        "-c:v", "libx264",
        "-preset", opts.preset,
        "-crf", str(opts.crf),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        str(temp_output)
    ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        if temp_output.is_file():
            temp_output.unlink()
        raise RuntimeError(f"FFmpeg rendering failed: {res.stderr}")

    if temp_output.is_file():
        if output_path.is_file():
            output_path.unlink()
        temp_output.rename(output_path)

    if on_progress:
        on_progress(100.0)

    return output_path
