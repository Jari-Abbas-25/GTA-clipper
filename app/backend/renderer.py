"""FFmpeg Multi-Section & Multi-Layout Video Renderer.

Renders 1080x1920 (9:16 portrait) or 1920x1080 (16:9 landscape) MP4 clips.
Supports:
1. Multi-Section Timeline Transitions (different layouts across time ranges in one clip!)
2. Split-screen layout (customizable Streamer top/bottom + Gameplay)
3. Fit layout (centered gameplay with blurred background fill)
4. Full crop layout (9:16 or 16:9 cover crop with independent pan & zoom)
5. Picture-in-Picture layout (full gameplay + floating customizable webcam box)
6. Independent element sizing, positioning, zoom, crop, borders, and corner radii
7. Burned-in ASS subtitles (with active word highlights)
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

from .config import EXPORT_H, EXPORT_W, FFMPEG_PATH, SPLIT_FACE_H, SPLIT_GAME_H


@dataclass
class RenderOptions:
    layout: Literal["split", "fit", "crop", "pip", "custom"] = "split"
    aspect_ratio: str = "9:16"  # "9:16" or "16:9"
    # Facecam normalized coords 0..1
    facecam_x: float = 0.72
    facecam_y: float = 0.06
    facecam_w: float = 0.24
    facecam_h: float = 0.28
    # Framing & zoom
    gameplay_pan_x: float = 0.5  # 0 = left, 0.5 = center, 1.0 = right
    zoom_factor: float = 1.0      # 1.0x to 3.0x
    # Multi-section timeline
    sections: list[dict[str, Any]] | None = None
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


def build_single_layout_filter(
    layout: str,
    src_w: int,
    src_h: int,
    target_w: int,
    target_h: int,
    facecam_x: float = 0.72,
    facecam_y: float = 0.06,
    facecam_w: float = 0.24,
    facecam_h: float = 0.28,
    gameplay_pan_x: float = 0.5,
    zoom_factor: float = 1.0,
    in_tag: str = "0:v",
    out_tag: str = "v_out"
) -> str:
    """Build filter graph chain for one video segment."""
    split_face_h = int(target_h * 0.40)
    split_game_h = target_h - split_face_h

    if layout == "split":
        # Split input stream for cam and gameplay
        s_chain = f"[{in_tag}]split=2[cam_in_{out_tag}][game_in_{out_tag}];"

        # 1. Facecam top panel
        cx = max(0, int(facecam_x * src_w))
        cy = max(0, int(facecam_y * src_h))
        cw = max(32, min(src_w - cx, int(facecam_w * src_w)))
        ch = max(32, min(src_h - cy, int(facecam_h * src_h)))

        cam_chain = (
            f"[cam_in_{out_tag}]crop={cw}:{ch}:{cx}:{cy},"
            f"scale={target_w}:{split_face_h}:force_original_aspect_ratio=increase,"
            f"crop={target_w}:{split_face_h}[cam_{out_tag}];"
        )

        # 2. Gameplay bottom panel
        game_w = max(32, int(src_w / max(1.0, zoom_factor)))
        game_h = max(32, int(src_h / max(1.0, zoom_factor)))
        gx = max(0, min(src_w - game_w, int(gameplay_pan_x * (src_w - game_w))))
        gy = max(0, (src_h - game_h) // 2)

        game_chain = (
            f"[game_in_{out_tag}]crop={game_w}:{game_h}:{gx}:{gy},"
            f"scale={target_w}:{split_game_h}:force_original_aspect_ratio=increase,"
            f"crop={target_w}:{split_game_h}[game_{out_tag}];"
        )

        stack_chain = (
            f"[cam_{out_tag}][game_{out_tag}]vstack=inputs=2[{out_tag}];"
        )
        return s_chain + cam_chain + game_chain + stack_chain

    elif layout == "fit":
        s_chain = f"[{in_tag}]split=2[bg_in_{out_tag}][fg_in_{out_tag}];"
        fg_h = int(target_w * (src_h / src_w))
        bg_chain = (
            f"[bg_in_{out_tag}]scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
            f"crop={target_w}:{target_h},boxblur=25:12[bg_{out_tag}];"
        )
        fg_chain = (
            f"[fg_in_{out_tag}]scale={target_w}:{fg_h}[fg_{out_tag}];"
        )
        overlay_chain = (
            f"[bg_{out_tag}][fg_{out_tag}]overlay=(W-w)/2:(H-h)/2[{out_tag}];"
        )
        return s_chain + bg_chain + fg_chain + overlay_chain

    elif layout == "crop":
        target_aspect = target_w / target_h
        crop_h = int(src_h / max(1.0, zoom_factor))
        crop_w = int(crop_h * target_aspect)
        if crop_w > src_w:
            crop_w = src_w
            crop_h = int(crop_w / target_aspect)

        cx = max(0, min(src_w - crop_w, int(gameplay_pan_x * (src_w - crop_w))))
        cy = max(0, (src_h - crop_h) // 2)

        return (
            f"[{in_tag}]crop={crop_w}:{crop_h}:{cx}:{cy},"
            f"scale={target_w}:{target_h}[{out_tag}];"
        )

    elif layout == "pip":
        s_chain = f"[{in_tag}]split=2[base_in_{out_tag}][pip_in_{out_tag}];"
        pip_w = max(64, int(target_w * facecam_w * 1.5))
        pip_h = max(64, int(target_h * facecam_h * 1.0))
        pip_x = max(0, min(target_w - pip_w, int(target_w * facecam_x)))
        pip_y = max(0, min(target_h - pip_h, int(target_h * facecam_y)))

        cx = max(0, int(facecam_x * src_w))
        cy = max(0, int(facecam_y * src_h))
        cw = max(32, min(src_w - cx, int(facecam_w * src_w)))
        ch = max(32, min(src_h - cy, int(facecam_h * src_h)))

        base_chain = (
            f"[base_in_{out_tag}]scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
            f"crop={target_w}:{target_h}[base_{out_tag}];"
        )
        pip_chain = (
            f"[pip_in_{out_tag}]crop={cw}:{ch}:{cx}:{cy},"
            f"scale={pip_w}:{pip_h}:force_original_aspect_ratio=increase,"
            f"crop={pip_w}:{pip_h}[pip_cam_{out_tag}];"
        )
        overlay_chain = (
            f"[base_{out_tag}][pip_cam_{out_tag}]overlay={pip_x}:{pip_y}[{out_tag}];"
        )
        return s_chain + base_chain + pip_chain + overlay_chain

    # Fallback to crop
    return f"[{in_tag}]scale={target_w}:{target_h}[{out_tag}];"


def build_filter_graph(
    opts: RenderOptions,
    src_w: int,
    src_h: int,
    clip_start_s: float,
    clip_end_s: float
) -> str:
    """Construct FFmpeg filter_complex graph supporting both single layout and multi-section layouts."""
    # Target resolution based on aspect ratio
    if opts.aspect_ratio == "16:9":
        target_w, target_h = 1920, 1080
    else:
        target_w, target_h = 1080, 1920

    # ASS subtitle filter
    ass_filter = ""
    if opts.enable_subtitles and opts.ass_path and opts.ass_path.is_file():
        escaped_ass = str(opts.ass_path.resolve()).replace("\\", "/").replace(":", "\\:")
        ass_filter = f",ass=filename='{escaped_ass}'"

    # Multi-section layout handling
    if opts.sections and len(opts.sections) > 0:
        filters = []
        sec_out_tags = []
        clip_dur = clip_end_s - clip_start_s

        for idx, sec in enumerate(opts.sections):
            sec_tag = f"s_{idx}"
            out_tag = f"v_sec_{idx}"

            # Calculate relative section boundaries
            s_start = float(sec.get("start", 0.0))
            s_end = float(sec.get("end", clip_dur))
            s_start = max(0.0, min(clip_dur, s_start))
            s_end = max(s_start + 0.1, min(clip_dur, s_end))

            # Trim section relative to clip start
            trim_filter = (
                f"[0:v]trim=start={s_start:.3f}:end={s_end:.3f},"
                f"setpts=PTS-STARTPTS[{sec_tag}];"
            )
            filters.append(trim_filter)

            layout = str(sec.get("layout", opts.layout or "split")).lower()
            gp = sec.get("gameplay", {})
            st = sec.get("streamer", {})

            fx = float(st.get("crop_x", opts.facecam_x))
            fy = float(st.get("crop_y", opts.facecam_y))
            fw = float(st.get("crop_w", opts.facecam_w))
            fh = float(st.get("crop_h", opts.facecam_h))
            g_pan = float(gp.get("pan_x", opts.gameplay_pan_x))
            zoom = float(gp.get("zoom", opts.zoom_factor))

            sec_filter = build_single_layout_filter(
                layout=layout,
                src_w=src_w,
                src_h=src_h,
                target_w=target_w,
                target_h=target_h,
                facecam_x=fx,
                facecam_y=fy,
                facecam_w=fw,
                facecam_h=fh,
                gameplay_pan_x=g_pan,
                zoom_factor=zoom,
                in_tag=sec_tag,
                out_tag=out_tag
            )
            filters.append(sec_filter)
            sar_tag = f"{out_tag}_sar"
            filters.append(f"[{out_tag}]setsar=1[{sar_tag}];")
            sec_out_tags.append(f"[{sar_tag}]")

        # Concat all section video outputs together
        concat_inputs = "".join(sec_out_tags)
        concat_filter = f"{concat_inputs}concat=n={len(sec_out_tags)}:v=1:a=0[v_cat];"
        filters.append(concat_filter)
        filters.append(f"[v_cat]setsar=1{ass_filter}[v_out]")
        return "".join(filters)

    # Standard single layout path
    single_filter = build_single_layout_filter(
        layout=opts.layout,
        src_w=src_w,
        src_h=src_h,
        target_w=target_w,
        target_h=target_h,
        facecam_x=opts.facecam_x,
        facecam_y=opts.facecam_y,
        facecam_w=opts.facecam_w,
        facecam_h=opts.facecam_h,
        gameplay_pan_x=opts.gameplay_pan_x,
        zoom_factor=opts.zoom_factor,
        in_tag="0:v",
        out_tag="v_single"
    )
    return single_filter + f"[v_single]null{ass_filter}[v_out]"


def render_clip(
    source_video: Path,
    output_path: Path,
    start_s: float,
    end_s: float,
    opts: RenderOptions,
    on_progress: Callable[[float], None] | None = None
) -> Path:
    """Render MP4 clip applying multi-section layouts, trims, and burned subtitles."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output_path.with_suffix(".part.mp4")

    src_w, src_h = get_video_dimensions(source_video)
    duration = end_s - start_s
    filter_graph = build_filter_graph(opts, src_w, src_h, clip_start_s=start_s, clip_end_s=end_s)

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
