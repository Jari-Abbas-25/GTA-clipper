"""Comprehensive End-to-End Test Suite for GTA Clipper.

Tests:
1. Synthetic VOD generation with dynamic audio and video
2. Synthetic Twitch chat log generation with emote spikes and copy-paste waves
3. Audio signal extraction (RMS dB, loudness jumps above baseline)
4. Chat signal calculation (rolling baseline, spike ratios, reaction detection)
5. Multi-signal highlight detection & ranking engine
6. faster-whisper INT8 speech transcription and ASS subtitle file creation
7. FFmpeg 9:16 vertical 1080x1920 video rendering for all 4 layouts:
   - Split-screen (facecam top + gameplay bottom)
   - 9:16 Crop
   - Fit (blurred background fill)
   - Picture-in-Picture
8. Storage tracking and cleanup verification
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.backend.audio_signals import compute_loudness_signal, compute_rms_db, extract_audio_wav
from app.backend.chat_signals import compute_chat_signals
from app.backend.config import EXPORTS_DIR, FFMPEG_PATH, PROJECTS_DIR
from app.backend.facecam_detector import detect_facecam
from app.backend.highlight_engine import run_highlight_detection
from app.backend.renderer import RenderOptions, get_video_dimensions, render_clip
from app.backend.storage import Project, create_project
from app.backend.transcriber import generate_ass_subtitles, transcribe_window


def create_test_media(project: Project, duration_s: int = 40):
    """Generate a test 1920x1080 video with varying audio dynamics."""
    print(f"\n[1/8] Generating {duration_s}s test synthetic video with audio dynamics...")

    # We generate audio with quiet speech baseline and sudden high-energy loudness bursts around t=15s and t=28s
    # Using FFmpeg lavfi filters
    audio_filter = (
        "sine=frequency=300:duration=12,volume=0.04[q1];"
        "sine=frequency=1200:duration=6,volume=1.0[spike1];"
        "sine=frequency=350:duration=8,volume=0.04[q2];"
        "sine=frequency=1400:duration=7,volume=1.0[spike2];"
        "sine=frequency=250:duration=7,volume=0.04[q3];"
        "[q1][spike1][q2][spike2][q3]concat=n=5:v=0:a=1[aout]"
    )

    cmd = [
        FFMPEG_PATH, "-y",
        "-f", "lavfi", "-i", f"testsrc=size=1920x1080:rate=30",
        "-filter_complex", audio_filter,
        "-map", "0:v", "-map", "[aout]",
        "-t", str(duration_s),
        "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac", "-b:a", "128k",
        str(project.source_video)
    ]

    subprocess.run(cmd, check=True, capture_output=True)
    assert project.source_video.is_file(), "Source video was not created"
    print(f" -> Source video created: {project.source_video.name} ({project.source_video.stat().st_size} bytes)")

    # 2. Generate synthetic Twitch chat log with message spike and reaction waves
    print("\n[2/8] Generating synthetic Twitch chat replay with emote spikes...")
    messages = []
    # Baseline chatter
    for sec in range(0, duration_s):
        messages.append([float(sec), "game is looking crazy", 1])
        if sec % 3 == 0:
            messages.append([float(sec), "what car is that?", 2])

    # Massive reaction burst at t=18s (stream broadcast delay matches audio peak at t=15s)
    # 3+ different users spamming KEKW and WTF
    reaction_users = [3, 4, 5, 6, 7, 8, 9, 10]
    for u in reaction_users:
        messages.append([18.2, "KEKW", u])
        messages.append([18.5, "WTF KEKW", u])
        messages.append([19.0, "NO WAY KEKW", u])

    for u in reaction_users[:5]:
        messages.append([31.0, "INSANE PLAY OMG", u])
        messages.append([31.2, "LETS GOOO", u])

    messages.sort(key=lambda m: m[0])

    chat_payload = {
        "version": 1,
        "video_id": "test_vod",
        "status": "ok",
        "count": len(messages),
        "authors": 12,
        "messages": messages
    }
    with open(project.chat_path, "w", encoding="utf-8") as f:
        json.dump(chat_payload, f, indent=2)
    print(f" -> Chat log created with {len(messages)} timestamped messages")


def test_signals_and_detection(project: Project):
    print("\n[3/8] Testing audio extraction and loudness signal analysis...")
    extract_audio_wav(project.source_video, project.audio_path)
    assert project.audio_path.is_file(), "Audio WAV file missing"

    rms_db, dur = compute_rms_db(project.audio_path)
    print(f" -> Extracted WAV duration: {dur:.2f}s, computed {len(rms_db)} RMS frames")

    loudness_curve, audio_reasons = compute_loudness_signal(rms_db, dur)
    print(f" -> Loudness curve max: {loudness_curve.max():.2f}, detected {len(audio_reasons)} loudness spikes")

    print("\n[4/8] Testing Twitch chat analysis...")
    chat_curve, chat_reasons = compute_chat_signals(project.chat_path, dur)
    print(f" -> Chat hype curve max: {chat_curve.max():.2f}, detected {len(chat_reasons)} chat reason events")
    assert chat_curve.max() > 0.3, "Chat curve failed to detect reaction spike"

    print("\n[5/8] Testing multi-signal highlight detection engine...")
    res = run_highlight_detection(project.audio_path, project.chat_path, top_n=5)
    print(f" -> Detection complete: Found {len(res.candidates)} highlight candidates!")
    assert len(res.candidates) > 0, "No candidates found"

    for c in res.candidates:
        print(f"    * Rank #{c.rank} [{c.id}]: {c.start:.1f}s - {c.end:.1f}s (dur: {c.duration:.1f}s) | Hype: {c.hype_score}/100 | Title: '{c.suggested_title}' | Category: {c.category}")
        for r in c.reasons:
            print(f"       -> Reason: {r['code']} ({r['value']})")

    # Save to project
    highlights_dict = {
        "duration": res.duration,
        "signals_present": res.signals_present,
        "reasons_summary": res.reasons_summary,
        "hype_curve": res.hype_curve,
        "candidates": [c.__dict__ for c in res.candidates]
    }
    project.save_highlights(highlights_dict)
    return res.candidates[0]


def test_transcription(project: Project, candidate):
    print("\n[6/8] Testing faster-whisper candidate transcription & ASS subtitle generation...")
    segments = transcribe_window(
        wav_path=project.audio_path,
        start_s=candidate.start,
        end_s=candidate.end,
        model_size="tiny"
    )
    print(f" -> Whisper transcribed candidate: {len(segments)} segments")

    # Generate ASS subtitle file
    ass_path = project.cache_dir / f"{candidate.id}_test.ass"
    generate_ass_subtitles(
        segments=segments,
        output_path=ass_path,
        style="bold",
        font_size=64
    )
    assert ass_path.is_file(), "ASS subtitle file missing"
    print(f" -> Generated ASS subtitles: {ass_path.name} ({ass_path.stat().st_size} bytes)")
    return ass_path


def test_vertical_rendering(project: Project, candidate, ass_path: Path):
    print("\n[7/8] Testing FFmpeg 1080x1920 vertical export across all 4 layouts...")
    layouts = ["split", "fit", "crop", "pip"]

    for layout in layouts:
        out_path = project.export_dir / f"{candidate.id}_{layout}.mp4"
        opts = RenderOptions(
            layout=layout,
            facecam_x=0.72,
            facecam_y=0.06,
            facecam_w=0.24,
            facecam_h=0.28,
            gameplay_pan_x=0.5,
            zoom_factor=1.0,
            enable_subtitles=True,
            ass_path=ass_path,
            preset="ultrafast"
        )

        render_clip(
            source_video=project.source_video,
            output_path=out_path,
            start_s=candidate.start,
            end_s=min(candidate.start + 6.0, candidate.end),  # 6s test render for speed
            opts=opts
        )

        assert out_path.is_file(), f"Rendered output missing for layout {layout}"
        w, h = get_video_dimensions(out_path)
        print(f" -> Layout '{layout}': Successfully rendered {w}x{h} MP4 ({out_path.stat().st_size} bytes)")
        assert w == 1080 and h == 1920, f"Expected 1080x1920, got {w}x{h}"


def test_storage_and_cleanup(project: Project):
    print("\n[8/8] Testing storage metrics and cleanup...")
    usage = project.disk_usage()
    print(f" -> Disk usage: Source {usage['source_video_mb']} MB | Cache {usage['cache_mb']} MB | Exports {usage['exports_mb']} MB | Total {usage['total_mb']} MB")

    clean_res = project.cleanup(delete_source=False, delete_cache=True)
    print(f" -> Cache cleanup freed: {clean_res['freed_mb']} MB")
    assert not project.audio_path.is_file(), "Audio WAV should have been cleaned"
    assert len(project.list_exports()) > 0, "Exports must be preserved!"
    print(f" -> Verified: {len(project.list_exports())} exported clips safely preserved!")


def main():
    print("=" * 70)
    print(" 🧪 RUNNING GTA CLIPPER COMPREHENSIVE PIPELINE TEST")
    print("=" * 70)

    test_pid = "test_gta6_vod"
    # Clean previous test project if exists
    test_dir = PROJECTS_DIR / test_pid
    if test_dir.is_dir():
        shutil.rmtree(test_dir, ignore_errors=True)

    proj = Project(test_pid)
    try:
        create_test_media(proj, duration_s=36)
        top_cand = test_signals_and_detection(proj)
        ass_path = test_transcription(proj, top_cand)
        test_vertical_rendering(proj, top_cand, ass_path)
        test_storage_and_cleanup(proj)
        print("\n" + "=" * 70)
        print(" ✅ ALL GTA CLIPPER TESTS PASSED SUCCESSFULLY!")
        print("=" * 70)
    finally:
        # Keep exports for verification or clean
        pass


if __name__ == "__main__":
    main()
