"""Comprehensive End-to-End Test Suite for GTA Clipper.

Tests:
1. Multi-platform URL detection (Twitch, YouTube standard, Shorts, Livestream, Local)
2. Synthetic VOD generation with dynamic audio and video (isolated in tests/scratch/)
3. Synthetic chat log generation with emote spikes and copy-paste waves
4. Audio signal extraction (RMS dB, loudness jumps above baseline)
5. Chat signal calculation (rolling baseline, spike ratios, reaction detection)
6. Multi-signal highlight detection & AI candidate evaluation
7. faster-whisper INT8 speech transcription and ASS subtitle file creation
8. FFmpeg 9:16 vertical 1080x1920 video rendering for all 4 layouts:
   - Split-screen (facecam top + gameplay bottom)
   - 9:16 Crop
   - Fit (blurred background fill)
   - Picture-in-Picture
9. Storage tracking and cleanup verification without polluting production directories
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
from app.backend.config import FFMPEG_PATH
from app.backend.highlight_engine import run_highlight_detection
from app.backend.renderer import RenderOptions, get_video_dimensions, render_clip
from app.backend.sources import Platform, detect_platform, extract_twitch_id, extract_youtube_id
from app.backend.storage import Project
from app.backend.transcriber import generate_ass_subtitles, transcribe_window

TEST_SCRATCH_DIR = BASE_DIR / "tests" / "scratch"
TEST_PROJECTS_DIR = TEST_SCRATCH_DIR / "projects"
TEST_EXPORTS_DIR = TEST_SCRATCH_DIR / "exports"


def test_platform_detection():
    print("\n[1/9] Testing Multi-Platform URL Detection...")
    cases = [
        ("https://www.twitch.tv/videos/123456789", Platform.TWITCH, "123456789"),
        ("https://twitch.tv/ninja/v/987654321", Platform.TWITCH, "987654321"),
        ("123456789", Platform.TWITCH, "123456789"),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", Platform.YOUTUBE, "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ", Platform.YOUTUBE, "dQw4w9WgXcQ"),
        ("https://www.youtube.com/live/dQw4w9WgXcQ", Platform.YOUTUBE, "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", Platform.YOUTUBE, "dQw4w9WgXcQ"),
    ]

    for url, expected_plat, expected_id in cases:
        plat, vid_id = detect_platform(url)
        assert plat == expected_plat, f"Expected {expected_plat} for {url}, got {plat}"
        assert vid_id == expected_id, f"Expected {expected_id} for {url}, got {vid_id}"
        print(f" -> URL recognized: [{plat.value.upper()}] id={vid_id} from {url}")

    print(" -> All multi-platform URL checks passed!")


def create_test_media(project: Project, duration_s: int = 36):
    print(f"\n[2/9] Generating {duration_s}s test synthetic video with audio dynamics...")

    audio_filter = (
        "sine=frequency=300:duration=12,volume=0.04[q1];"
        "sine=frequency=1200:duration=6,volume=1.0[spike1];"
        "sine=frequency=350:duration=6,volume=0.04[q2];"
        "sine=frequency=1400:duration=6,volume=1.0[spike2];"
        "sine=frequency=250:duration=6,volume=0.04[q3];"
        "[q1][spike1][q2][spike2][q3]concat=n=5:v=0:a=1[aout]"
    )

    cmd = [
        FFMPEG_PATH, "-y",
        "-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=30",
        "-filter_complex", audio_filter,
        "-map", "0:v", "-map", "[aout]",
        "-t", str(duration_s),
        "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac", "-b:a", "128k",
        str(project.source_video),
    ]

    subprocess.run(cmd, check=True, capture_output=True)
    assert project.source_video.is_file(), "Source video was not created"
    print(f" -> Source video created: {project.source_video.name} ({project.source_video.stat().st_size} bytes)")

    print("\n[3/9] Generating synthetic chat replay with emote spikes...")
    messages = []
    for sec in range(0, duration_s):
        messages.append([float(sec), "game is looking crazy", 1])
        if sec % 3 == 0:
            messages.append([float(sec), "what car is that?", 2])

    reaction_users = [3, 4, 5, 6, 7, 8, 9, 10]
    for u in reaction_users:
        messages.append([18.2, "KEKW", u])
        messages.append([18.5, "WTF KEKW", u])
        messages.append([19.0, "NO WAY KEKW", u])

    for u in reaction_users[:5]:
        messages.append([30.0, "INSANE PLAY OMG", u])
        messages.append([30.2, "LETS GOOO", u])

    messages.sort(key=lambda m: m[0])

    chat_payload = {
        "version": 1,
        "video_id": "test_vod",
        "status": "ok",
        "count": len(messages),
        "authors": 12,
        "messages": messages,
    }
    with open(project.chat_path, "w", encoding="utf-8") as f:
        json.dump(chat_payload, f, indent=2)
    print(f" -> Chat log created with {len(messages)} timestamped messages")


def test_signals_and_detection(project: Project):
    print("\n[4/9] Testing audio extraction and loudness signal analysis...")
    extract_audio_wav(project.source_video, project.audio_path)
    assert project.audio_path.is_file(), "Audio WAV file missing"

    rms_db, dur = compute_rms_db(project.audio_path)
    print(f" -> Extracted WAV duration: {dur:.2f}s, computed {len(rms_db)} RMS frames")

    loudness_curve, audio_reasons = compute_loudness_signal(rms_db, dur)
    print(f" -> Loudness curve max: {loudness_curve.max():.2f}, detected {len(audio_reasons)} loudness spikes")

    print("\n[5/9] Testing chat signal analysis...")
    chat_curve, chat_reasons = compute_chat_signals(project.chat_path, dur)
    print(f" -> Chat hype curve max: {chat_curve.max():.2f}, detected {len(chat_reasons)} chat reason events")

    print("\n[6/9] Testing multi-signal fusion & AI candidate evaluation...")
    detection_res = run_highlight_detection(
        wav_path=project.audio_path,
        chat_path=project.chat_path,
        top_n=5,
    )

    print(f" -> Multi-signal engine finished: detected {len(detection_res.candidates)} highlight candidate(s)")
    assert len(detection_res.candidates) > 0, "No candidates found"

    for cand in detection_res.candidates:
        print(f"    * Rank #{cand.rank} ({cand.id}): Hype {cand.hype_score}/100 [{cand.start:.1f}s - {cand.end:.1f}s] - Title: '{cand.suggested_title}'")

    return detection_res.candidates[0]


def test_transcription(project: Project, candidate):
    print(f"\n[7/9] Testing candidate-window transcription on clip {candidate.id}...")
    segments = transcribe_window(
        wav_path=project.audio_path,
        start_s=candidate.start,
        end_s=candidate.end,
        model_size="tiny",
    )
    print(f" -> Transcribed {len(segments)} segment(s) on candidate window")

    ass_path = project.cache_dir / f"{candidate.id}_test.ass"
    generate_ass_subtitles(
        segments=segments,
        output_path=ass_path,
        style="bold",
        font_size=68,
    )
    assert ass_path.is_file(), "ASS subtitle file missing"
    print(f" -> Generated ASS subtitles at {ass_path.name} ({ass_path.stat().st_size} bytes)")
    return ass_path


def test_vertical_rendering(project: Project, candidate, ass_path: Path):
    print("\n[8/9] Testing FFmpeg 9:16 vertical 1080x1920 MP4 rendering...")

    for layout in ("split", "fit", "crop", "pip"):
        out_path = project.export_dir / f"{candidate.id}_{layout}.mp4"
        opts = RenderOptions(
            layout=layout,  # type: ignore
            facecam_x=0.70,
            facecam_y=0.08,
            facecam_w=0.25,
            facecam_h=0.28,
            gameplay_pan_x=0.5,
            zoom_factor=1.0,
            enable_subtitles=True,
            ass_path=ass_path,
        )

        render_clip(
            source_video=project.source_video,
            output_path=out_path,
            start_s=candidate.start,
            end_s=min(candidate.start + 5.0, candidate.end),
            opts=opts,
        )

        assert out_path.is_file(), f"Rendered output missing for layout {layout}"
        w, h = get_video_dimensions(out_path)
        print(f" -> Layout '{layout}': Successfully rendered {w}x{h} MP4 ({out_path.stat().st_size} bytes)")
        assert w == 1080 and h == 1920, f"Expected 1080x1920, got {w}x{h}"


def test_storage_and_cleanup(project: Project):
    print("\n[9/9] Testing storage tracking and cache cleanup...")
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
    print(" (Isolated in tests/scratch/ — leaves projects/ completely clean)")
    print("=" * 70)

    # Ensure isolated test scratch folders
    if TEST_SCRATCH_DIR.exists():
        shutil.rmtree(TEST_SCRATCH_DIR, ignore_errors=True)
    TEST_PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    TEST_EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

    test_pid = "test_pipeline_run"
    proj = Project(test_pid, base_dir=TEST_PROJECTS_DIR, export_base_dir=TEST_EXPORTS_DIR)

    try:
        test_platform_detection()
        create_test_media(proj, duration_s=36)
        top_cand = test_signals_and_detection(proj)
        ass_path = test_transcription(proj, top_cand)
        test_vertical_rendering(proj, top_cand, ass_path)
        test_storage_and_cleanup(proj)

        print("\n" + "=" * 70)
        print(" ✅ ALL GTA CLIPPER PIPELINE TESTS PASSED SUCCESSFULLY!")
        print("=" * 70)
    finally:
        # Clean up test scratch
        shutil.rmtree(TEST_SCRATCH_DIR, ignore_errors=True)
        print("🧹 Cleaned up tests/scratch/ directory.")


if __name__ == "__main__":
    main()
