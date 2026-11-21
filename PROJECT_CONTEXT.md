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

### Platform Support (Multi-Platform — NEW)
- **Twitch VODs**: yt-dlp video download + Twitch public GraphQL chat
- **YouTube**: yt-dlp video download + yt-dlp live_chat track (archived livestreams)
- **Local files**: copy/hardlink + optional `.chat.json` sidecar
- URL detection: 6 YouTube patterns, 2 Twitch patterns, local file check
- Pre-download probe (`/api/probe`): title, duration, thumbnail via `yt-dlp --dump-json`
- Platform badge in UI (purple Twitch / red YouTube / grey Local)

### Startup Behavior (FIXED)
- Dashboard starts empty; no auto-loading of projects
- Shows existing genuine user projects or empty state
- Processing starts ONLY after user pastes URL + clicks Start Processing
- Demo is accessible via explicit "Load Sample Clip" button (calls `/api/projects/create-demo`)

### AI Provider System (REWRITTEN)
- **Ollama**: auto-discovers models at `http://localhost:11434`; `GET /api/ai/ollama/models`
- **DeepSeek**: `deepseek-chat` via `https://api.deepseek.com/v1`
- **OpenRouter**: any model via `https://openrouter.ai/api/v1`
- **Heuristics**: gaming keyword + chat/audio signal fallback (always available)
- Config stored in `.ai_config.json` (git-ignored)
- Keys masked in UI (e.g. `sk-****...abcd`)
- `POST /api/ai/test` verifies connectivity before saving
- Graceful fallback to heuristics if any provider fails

### Save As Dialog (NEW)
- `POST /api/exports/{pid}/{cid}/save-dialog` → Tkinter subprocess → native Windows file dialog
- `POST /api/exports/{pid}/{cid}/save-to-path` → copies rendered file to chosen path
- UI shows export success bar with Save As button

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

### test_pipeline.py (all passed ✅)
- 7 URL detection cases passed
- 36s synthetic 1080p video generated (1.49 MB)
- 82 synthetic chat messages, 10 loudness spikes, 6 chat events
- 2 candidates: c01 Hype 99/100, c02 Hype 81/100
- 4 layout renders: split (137KB), fit (534KB), crop (166KB), pip (168KB) — all 1080×1920
- Storage cleanup: freed 1.1 MB, all exports preserved
- `tests/scratch/` cleaned after run

### test_api.py (all passed ✅)
- `/api/status` → 200 OK, ai_mode/ai_provider included
- `/api/probe` → Twitch 200, YouTube 200
- AI config get/update → 200 OK
- Heuristics test → `success: True`
- DeepSeek missing key → `success: False` (correctly handled)
- Demo project creation → 200, title correct, 2 candidates
- Clip render → `c01_Chat_Lost_It_KEKW.mp4` (0.36 MB)
- Save-to-path → 200 OK, file written
- Cleanup → projects/ and exports/ left empty

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
