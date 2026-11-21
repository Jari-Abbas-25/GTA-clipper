# GTA Clipper — Project Context & Continuity Log

> **For any new session:** Read this file first. It describes the current state of the entire project.

---

## Project Objective

Build a free, locally running, zero-cost desktop highlight clipping application for gaming Twitch VODs and YouTube videos (primary focus: GTA 6 gameplay). Target workflow:

**Paste URL → Download VOD & Chat → Multi-Signal Highlight Detection → Review Candidates → Edit in 9:16 Canvas → Export Vertical 1080×1920 MP4**

---

## Zero-Cost & Local-First Guarantee

- No paid APIs, no subscriptions, no cloud AI dependencies.
- Zero API keys required to operate (optional for DeepSeek/OpenRouter).
- Fully runnable on standard hardware (Intel Core i5, 8GB RAM, Windows PC).
- CPU-first INT8 quantized models with optional hardware acceleration.

---

## Technology Stack & Dependencies

| Component | Package | Version Tested |
|---|---|---|
| Runtime | Python (Windows x64) | 3.13.3 |
| Backend | FastAPI + Uvicorn | latest |
| Video/Audio | ffmpeg | 9.0.2 (full build) |
| Downloader | yt-dlp | 2026.08.19 |
| Transcription | faster-whisper + ctranslate2 | 1.2.1 / 4.9.0 |
| Audio tagging | sherpa-onnx (CED-mini ONNX) | 2.0.1 |
| Numerics | numpy, scipy | 2.3.2 / 1.16.3 |
| Vision | opencv-python-headless | 5.0.0.93 (optional) |
| HTTP | requests | latest |
| Validation | pydantic | v2 |
| Chat (Twitch) | Twitch public GraphQL API | No auth required |
| Chat (YouTube) | yt-dlp live_chat track | — |
| AI (local) | Ollama (llama3.2:3b / qwen2.5:3b) | Optional |
| AI (API) | DeepSeek / OpenRouter | Optional, key required |

---

## Current Project Structure

```
e:\jari\Python\gta clipper\
├── app/
│   ├── backend/
│   │   ├── sources/              # NEW: Multi-platform source package
│   │   │   ├── __init__.py       # Package factory, get_source() dispatcher
│   │   │   ├── base.py           # BaseSource ABC, Platform, ChatStatus dataclasses
│   │   │   ├── detector.py       # detect_platform(), extract_twitch_id(), extract_youtube_id()
│   │   │   ├── twitch.py         # TwitchSource (yt-dlp video + GraphQL chat)
│   │   │   ├── youtube.py        # YouTubeSource (yt-dlp video + live_chat)
│   │   │   └── local.py          # LocalSource (copy/hardlink + .chat.json sidecar)
│   │   ├── config.py             # Paths, constants, hardware config
│   │   ├── twitch_downloader.py  # Thin adapter (delegates to sources/) — backwards compat
│   │   ├── audio_signals.py      # RMS dBFS loudness jumps + CED-mini audio event tagging
│   │   ├── chat_signals.py       # Twitch/YouTube chat velocity, rolling baseline, emote waves
│   │   ├── transcriber.py        # faster-whisper INT8 candidate transcription + ASS subtitles
│   │   ├── ai_evaluator.py       # REWRITTEN: Ollama/DeepSeek/OpenRouter/heuristics providers
│   │   ├── highlight_engine.py   # Multi-signal fusion, hype curve, peak picking
│   │   ├── facecam_detector.py   # Webcam overlay bounding box detection (OpenCV)
│   │   ├── renderer.py           # FFmpeg 1080×1920 9:16 vertical MP4 export
│   │   ├── storage.py            # UPDATED: platform/video_id/chat_status/ai_provider fields
│   │   └── server.py             # REWRITTEN: multi-platform, AI config, Save As endpoints
│   └── frontend/
│       ├── index.html            # REWRITTEN: AI Settings modal, platform badge, preview card
│       ├── styles.css            # UPDATED: platform badge, preview card, empty state styles
│       ├── canvas_editor.js      # 9:16 HTML5 Canvas editor (unchanged)
│       └── app.js                # REWRITTEN: no auto-load, platform detection, AI settings UI
├── docs/
│   └── CURRENT_WORKFLOW.md       # Complete workflow reference (created this session)
├── exports/                      # Finished MP4 clips [git-ignored, currently empty]
├── models/
│   └── ced-mini/
│       ├── model.int8.onnx
│       └── class_labels_indices.csv
├── projects/                     # User project workspaces [git-ignored, currently empty]
├── cache/                        # Download cache [git-ignored]
├── temp/                         # Processing temporaries [git-ignored]
├── tests/
│   ├── fixtures/
│   │   └── sample_project/       # Demo project data (synthetic test fixtures)
│   │       ├── audio.wav
│   │       ├── chat.json
│   │       ├── highlights.json
│   │       ├── meta.json
│   │       ├── source.mp4
│   │       ├── cache/c01_test.ass
│   │       └── clip_settings/c01.json
│   ├── test_pipeline.py          # REWRITTEN: isolated to tests/scratch/, never touches projects/
│   └── test_api.py               # REWRITTEN: comprehensive API tests with cleanup
├── _research/                    # Cloned reference repos (pireel, sharkyclips)
├── .ai_config.json               # AI provider config [git-ignored, created at first use]
├── .gitignore
├── PROJECT_CONTEXT.md            # This file
├── README.md                     # UPDATED: multi-platform, AI providers, YouTube support
├── run.py
└── pyrightconfig.json
```

---

## Completed Functionality

### First-Launch AI Configuration (NEW)
- Onboarding modal triggers automatically on first launch before URL input.
- **Option A (Local AI)**: Auto-detects local Ollama server, lists installed models with disk sizes and approximate RAM requirements (e.g. `llama3.2:3b` ~2.0GB / ~2.8GB RAM, `qwen2.5:3b` ~1.9GB / ~2.6GB RAM). Includes zero-cost heuristic fallback when Ollama is unavailable.
- **Option B (Cloud AI)**: Supports DeepSeek (`deepseek-chat`) and OpenRouter models with masked key storage and connectivity testing (`POST /api/ai/test`).
- Config saved with `configured: True` to `.ai_config.json` (git-ignored). Can be reopened anytime via the AI Settings button.

### Multi-Platform Support
- **Twitch VODs**: yt-dlp video download + Twitch public GraphQL chat
- **YouTube**: yt-dlp video download + yt-dlp live_chat track (archived livestreams)
- **Local files**: copy/hardlink + optional `.chat.json` sidecar
- URL detection: 6 YouTube patterns, 2 Twitch patterns, local file check
- Pre-download probe (`/api/probe`): title, duration, thumbnail via `yt-dlp --dump-json`
- Platform badge in UI (purple Twitch / red YouTube / grey Local)

### Real AI Highlight Detection & Tuning (NEW)
- Analysis Options Drawer in Dashboard allows configuring:
  - **Target highlight count**: Default 5 (targeting 4–6+ strong clips)
  - **Sensitivity**: Low, Medium, High (adjusts spike threshold and baseline multipliers)
  - **Focus Mode**: All, Action (loudness & intensity), Funny (laughter/KEKW spikes), Story (dialogue & pacing)
  - **Min/Max Duration**: Default 15s to 60s
- Candidates card list with checkboxes, confidence score, peak hype, duration, and one-click editor opening.
- Automatic generation of multi-section editing arrangements on detection.

### Structured AI Multi-Section Timeline Editing (NEW)
- Clips automatically receive structured narrative section breakdowns:
  - Intro / Build-up (Full gameplay crop)
  - Climax / Peak (Split-screen streamer reaction)
  - Climax Zoom (Action focus 1.35x zoom)
  - Outro / Aftermath (Blurred fit)
- Re-generate anytime with "⚡ AI Edit Suggestions" (`POST /api/projects/{id}/clips/{cid}/ai-edit-suggestions`).

### Upgraded Canvas & Multi-Section Manual Video Editor (NEW)
- **Aspect Ratio Switcher**: One-click toggling between `9:16 Portrait` (1080×1920) and `16:9 Landscape` (1920×1080) with dynamic canvas resizing.
- **Multi-Section Timeline**: Time ruler with visual ticks, color-coded section blocks, playhead scrubber, "Split Section" at playhead, "Delete Section", and boundary trimming.
- **Independent Element Controls**:
  - **Gameplay**: Zoom 1.0x–3.0x, Pan X, Pan Y, Position Y, Border width & color, Corner radius, Reset.
  - **Streamer**: Enable/Disable, Zoom 1.0x–2.5x, Crop framing (X, Y, W, H), interactive canvas drag & corner handle resizing, Border width & color, Corner radius, Z-index.
  - **Layout per section**: Split, Crop, Fit, PIP applied dynamically as the playhead advances.

### Export Destination & Native File Management (NEW)
- Render directly to user-chosen paths outside the project directory.
- Native Windows "Browse Destination" dialog (`POST /api/system/browse-save-path`).
- "Open Containing Folder" button (`POST /api/system/open-folder`) highlights the rendered video in Windows Explorer.
- Frame-accurate FFmpeg multi-section concatenation with `setsar=1` aspect ratio normalization and burned-in subtitles.

### Startup Behavior
- Dashboard starts empty; no auto-loading of projects
- Shows existing genuine user projects or empty state
- Processing starts ONLY after user pastes URL + clicks Start Processing
- Demo is accessible via explicit "Load Sample Clip" button (calls `/api/projects/create-demo`)

### Repository Cleanup (DONE)
- Test fixtures moved from `projects/` → `tests/fixtures/sample_project/`
- `projects/` and `exports/` are clean (empty)
- `.gitignore` covers: `exports/`, `cache/`, `temp/`, `tests/scratch/`, `.ai_config.json`, `.env.local`

### Storage.py Updates (DONE)
- `ProjectMeta` extended with: `platform`, `video_id`, `chat_status`, `ai_provider`
- `create_demo_project()` added for explicit demo loading
- `Project.__init__` accepts optional `base_dir` and `export_base_dir` for test isolation

### Audio Pipeline (UNCHANGED — working)
- 16kHz mono WAV extraction via FFmpeg
- 0.5s RMS dBFS rolling baseline (120s median)
- Loudness jump detection: +12/+20/+28 dB thresholds
- CED-mini ONNX: laughter, shouting, cheering, crowd_applause tags
- Spectral dynamics fallback (NumPy/SciPy) when CED-mini unavailable

### Chat Signal Analysis (UNCHANGED — working)
- Rolling 10s window vs 120s median baseline
- 18.0× velocity spike detected in test
- Emote regex: KEKW, WTF, POG, LUL, etc. + Unicode emojis
- Bot filtering, spam collapse, 5s broadcast delay compensation

### Highlight Engine (UNCHANGED — working)
- Multi-signal fusion with agreement bonus
- Gaussian smoothing, peak picking, NMS
- Pre-roll 6s / post-roll 4s boundary calculation
- Relative 0–100 hype scoring

### Transcription (UNCHANGED — working)
- faster-whisper tiny INT8 on candidate windows only
- 4 ASS subtitle styles: bold_gold, karaoke, clean_box, minimal

### Canvas Editor (UNCHANGED — working)
- 60fps HTML5 Canvas, 360×640 preview → 1080×1920 export
- 4 layouts: split, fit, crop, pip
- Facecam drag/resize, gameplay pan/zoom, subtitle preview, timeline scrubber
- Settings auto-saved to `clip_settings/<cid>.json`

### FFmpeg Export (UNCHANGED — working)
- libx264 + AAC, 1080×1920, yuv420p
- Burned-in ASS subtitles
- All 4 layout filter chains verified

---

## Test Results

### test_pipeline.py (all 9/9 passed ✅)
- 7 URL detection cases passed (Twitch VODs, channels, YouTube standard, Shorts, Livestreams)
- 36s synthetic 1080p video generated with dynamic audio spikes
- 82 synthetic chat messages with emote surges
- Multi-signal detection: Rank #1 (c01 Hype 99/100), Rank #2 (c02 Hype 81/100)
- faster-whisper INT8 candidate transcription + ASS subtitle generation
- FFmpeg 9:16 vertical 1080×1920 MP4 rendering verified across all 4 layouts:
  - Split: 1080×1920 (136 KB)
  - Fit: 1080×1920 (533 KB)
  - Crop: 1080×1920 (166 KB)
  - PIP: 1080×1920 (169 KB)
- Storage cleanup: cache freed, all exports preserved, `tests/scratch/` cleanly deleted

### test_api.py (all passed ✅)
- `/api/status` → 200 OK (CPU cores, tools, active AI provider)
- `/api/probe` → Twitch 200, YouTube 200
- AI config get/update with `configured: True`
- `/api/ai/ollama/models` returns model names, details, and RAM/disk specs
- Heuristics connection test → `success: True`
- DeepSeek missing key validation → `success: False` (correctly rejected)
- Demo project creation → 200 OK, 2 highlight candidates
- `/api/projects/{id}/clips/{cid}/ai-edit-suggestions` → generates structured sections
- Multi-section timeline settings save → 200 OK
- Multi-section MP4 render directly to custom destination path → 200 OK, valid MP4
- `/api/exports/{pid}/{cid}/save-to-path` verified
- `/api/system/open-folder` verified with Explorer integration
- Complete cleanup of test demo projects

---

## Known Bugs & Limitations

| # | Issue | Severity | Notes |
|---|---|---|---|
| 1 | `cv2` optional — frame endpoint fails without it | Low | `pip install opencv-python-headless` |
| 2 | YouTube chat only on archived livestreams | Medium | Handled gracefully with status message |
| 3 | yt-dlp live_chat.json format may change | Medium | Pin yt-dlp version |
| 4 | API keys in `.ai_config.json` plaintext | Low | File git-ignored; local only |
| 5 | Tkinter Save As ~1-2s startup lag | Low | Subprocess approach for thread safety |
| 6 | faster-whisper downloads tiny model on first use | Low | One-time ~75MB download |
| 7 | GPU not auto-detected for faster-whisper | Low | Set `compute_type="float16"` manually |

---

## Git History

| Commit | Description |
|---|---|
| `6095be2` | Initial commit — full backend + frontend |
| `e7a669a` | Server.py error fixes and hardening |
| (pending) | Multi-platform, AI config, clean startup, sources package, Save As, docs |

> **IMPORTANT**: The session that produced the sources package, ai_evaluator rewrite, server rewrite, frontend rewrites, and all documentation has not yet been committed. Run the git commit below.

### Pending commit command

```bash
git add -A
git commit -m "feat: multi-platform (Twitch+YouTube), AI provider config, clean startup, sources package, Save As dialog, docs"
```

---

## Research Findings

### sharkyclips (MIT)
- Modular Python backend with multi-signal hype detection
- Good 9:16 layout math (`split`, `fit`, `crop`)
- Architecture adapted for our CPU-first system
- Caveat: `doctor.py` assumed CUDA 12 on any NVIDIA GPU — we default CPU-first

### pireel (AGPL-3.0)
- Large pnpm monorepo (React 19, Tailwind 4, WebCodecs)
- Designed around cloud AI endpoints
- AGPL-3.0 license friction
- **Decision**: Not integrated — custom Canvas editor built instead

---

## Instructions for a New Session

1. Navigate to `e:\jari\Python\gta clipper`
2. Read `PROJECT_CONTEXT.md` (this file)
3. Launch: `python run.py`
4. Access: `http://127.0.0.1:8000`
5. Test: `python tests/test_pipeline.py` and `python tests/test_api.py`

### Next Optional Development Tasks

1. **Automatic face-tracking pan** — Use OpenCV to track face position across gameplay frames and auto-set the pan value.
2. **Batch export queue** — Multi-clip export queue UI with progress bars.
3. **Hype map visualization** — Chart.js waveform in dashboard showing full VOD engagement curve.
4. **Clip sharing** — Generate a shareable `.zip` of a clip + subtitles + settings.
5. **GPU transcription** — Auto-detect CUDA and switch faster-whisper to `float16`.
6. **Twitch API v2 auth** — Optional OAuth for private/subscriber-only VODs.
