# GTA Clipper — Project Context & Continuity

## Project Objective
Build a free, locally running, zero-cost desktop highlight clipping application specifically designed for gaming Twitch VODs (with primary focus on GTA gameplay). The target workflow:
**Paste Twitch VOD URL -> Download VOD & Chat -> Multi-Signal Highlight Detection (Audio, Chat, VAD, Speech) -> Review & Select Highlights -> Integrated 9:16 Canvas Editor (Crop, Split-Screen Facecam, Captions, Trimming) -> Export Vertical 1080x1920 MP4 Clips.**

## Zero-Cost & Local-First Guarantee
- No paid APIs, no subscriptions, no cloud AI dependencies.
- Zero API keys required.
- Fully runnable on standard hardware (Intel Core i5, 8GB RAM, Windows PC).
- CPU-first INT8 quantized models with optional hardware acceleration.

## Technology Stack & Dependencies
- **Runtime**: Python 3.13.3 (Windows x64)
- **Backend Framework**: FastAPI + Uvicorn
- **Video & Audio Processing**:
  - `ffmpeg` (installed: 9.0.2 full build with libass, x264, x265)
  - `yt-dlp` (installed: 2026.08.19)
  - `faster-whisper` (installed: 1.2.1 with `ctranslate2` 4.9.0 CPU INT8)
  - `sherpa-onnx` (installed: 2.0.1 for CPU audio event tagging: laughter, shouting, cheering via CED-mini ONNX)
  - `numpy` (2.3.2), `scipy` (1.16.3), `opencv-python-headless` (5.0.0.93)
- **Chat Extraction**: Direct Twitch Public GraphQL API (`https://gql.twitch.tv/gql`, operation `VideoCommentsByOffsetOrCursor`, public web client ID `kimne78kx3ncx6brgo4mv6wki5h1ko`)
- **Frontend / UI**: HTML5 Canvas 9:16 editor + modern reactive web dashboard. Real-time split-screen rendering, facecam crop bounding box manipulation, caption styles, waveform/hype map, and clip boundary trimmer.
- **Local AI Evaluator**: Local Ollama endpoint (`http://localhost:11434`), gracefully bypassed with rule-based gaming heuristics if Ollama is not installed/running.

## Research Findings on Candidate Repositories
1. **Pireel (`pireel/pireel`)**:
   - **License**: AGPL-3.0-only (strong copyleft).
   - **Architecture**: Large pnpm monorepo with React 19, tailwind 4, mediabunny WebCodecs, designed around external cloud AI endpoints (`StudioProviders`) and NLE XML/FCPXML timeline exports rather than local gaming split-screen FFmpeg rendering.
   - **Conclusion**: Impractical to embed directly without massive overhead, license friction (AGPL-3.0), and missing dedicated gaming layouts (split facecam top + gameplay bottom).
2. **SharkyClips (`utkualsir/sharkyclips`)**:
   - **License**: MIT License (permissive).
   - **Architecture**: Modular Python backend with multi-signal hype detection (chat rolling baseline, loudness jump above baseline, laughter/shouting via CED-mini ONNX, faster-whisper speech context).
   - **Video Rendering & Layouts**: Excellent 9:16 layout math (`split` facecam top + gameplay bottom, `fit` with blurred background, `crop` center cover), libass subtitle burn-in with karaoke/bold styles.
   - **Caveat Discovered**: SharkyClips' `doctor.py` assumed modern CUDA 12 on any detected NVIDIA card, freezing on older legacy GPUs (like NVS 4200M). Our custom system explicitly defaults to CPU-first INT8 and handles hardware gracefully.

## Current Project Structure
```
e:\jari\Python\gta clipper\
├── app/
│   ├── backend/
│   │   ├── config.py             # System paths, constants & hardware config
│   │   ├── twitch_downloader.py  # Twitch VOD & public GraphQL chat fetcher
│   │   ├── audio_signals.py      # RMS dB loudness jumps & audio event detection
│   │   ├── chat_signals.py       # Twitch chat velocity, rolling baseline & emote waves
│   │   ├── transcriber.py        # faster-whisper INT8 candidate transcription & ASS subtitles
│   │   ├── ai_evaluator.py       # Local Ollama integration & heuristic fallback
│   │   ├── highlight_engine.py   # Multi-signal fusion, hype curve, peak picking
│   │   ├── facecam_detector.py   # Webcam overlay bounding box detection
│   │   ├── renderer.py           # FFmpeg 1080x1920 9:16 vertical MP4 export
│   │   ├── storage.py            # Project state, disk usage & cleanup
│   │   └── server.py             # FastAPI REST & streaming server
│   └── frontend/
│       ├── index.html            # Main desktop application interface
│       ├── styles.css            # Dark-mode gaming UI styling
│       ├── canvas_editor.js      # 9:16 HTML5 Canvas editor & facecam manipulator
│       └── app.js                # Frontend state controller & API binder
├── exports/                      # Finished 1080x1920 MP4 clips
├── models/                       # Quantized ONNX & Whisper models (CED-mini)
├── projects/                     # Project workspaces (source VOD, chat, cache, settings)
├── tests/
│   ├── test_pipeline.py          # End-to-end pipeline test
│   └── test_api.py               # REST API test
├── run.py                        # Single-command application launcher
├── PROJECT_CONTEXT.md            # Mandatory project context & continuity log
└── README.md                     # Documentation & user guide
```

## Completed Functionality
- **VOD & Chat Ingestion**:
  - `twitch_downloader.py`: Downloads Twitch VOD streams via `yt-dlp` and Twitch chat comments via public GraphQL API with pagination, retry, and bot filtering.
  - Supports local video file importation for instant offline clipping.
- **Multi-Signal Highlight Detection**:
  - `audio_signals.py`: 16kHz mono WAV extraction, streaming 0.5s RMS dBFS calculation, adaptive rolling baseline filter, sudden loudness jump detection (+12 dB to +28 dB), and audio event tagging (laughter, shouting, cheering via CED-mini ONNX model or spectral dynamics).
  - `chat_signals.py`: Rolling median baseline (120s), chat velocity spikes (e.g. 18.0x surge), reaction regex matching (`KEKW`, `WTF`, `POG`, emojis), copy-paste spam wave detection across unique users, and broadcast delay compensation (5s).
  - `highlight_engine.py`: Dynamic signal fusion, agreement bonus boost, Gaussian curve smoothing, peak picking with min gap, natural boundary calculation (pre-roll setup + post-roll reaction), non-maximum suppression, and relative 0..100 hype scoring.
- **Speech Context & Captions**:
  - `transcriber.py`: `faster-whisper` INT8 quantized CPU transcription restricted to candidate windows (saving 90%+ CPU time), word-level timing extraction, and professional `.ass` subtitle generator with Bold Gold Highlight, Karaoke, Clean Box, and Minimal styles.
- **Local AI Evaluator**:
  - `ai_evaluator.py`: Optional Ollama evaluation (`llama3.2:3b`, `qwen2.5:3b`) with seamless heuristic fallback providing viral scoring, category classification, and click-worthy titles.
- **Embedded 9:16 Canvas Editor**:
  - `canvas_editor.js` & `index.html`: Real-time 60fps HTML5 Canvas preview with 4 layouts (`split`, `crop`, `fit`, `pip`), on-screen draggable/resizable facecam bounding box, horizontal gameplay pan focus, zoom factor (1.0x - 2.5x), live word-highlight subtitle overlay, and timeline scrubber with trim nudges (-1s/+1s).
  - Persistence: Clip settings automatically saved per clip and reloaded on demand.
- **Vertical MP4 Rendering**:
  - `renderer.py`: Local FFmpeg 1080x1920 MP4 export with CPU `libx264` + `aac` encoding and burned-in ASS subtitles.
- **Storage Management**:
  - `storage.py`: Disk usage breakdown and one-click cleanup option to remove source VODs and temporary cache while safely preserving rendered clips and metadata.

## Actual Testing Performed & Results
1. **Automated End-to-End Pipeline Test (`tests/test_pipeline.py`)**:
   - [x] Generated 42s synthetic 1080p video with distinct audio volume dynamics (+28 dB spikes).
   - [x] Generated synthetic Twitch chat log with 82 timestamped messages including reaction bursts.
   - [x] Verified audio extraction and RMS dB loudness jump detection (detected 11 loudness spikes).
   - [x] Verified Twitch chat spike analysis (0.96 hype score, 18.0x velocity spike, KEKW detected).
   - [x] Verified highlight detection: successfully ranked candidates (Rank #1: Hype 99/100 'Chat Lost It! KEKW', Rank #2: Hype 79/100 'Intense Play!').
   - [x] Verified faster-whisper candidate transcription and ASS subtitle file creation (`c01_test.ass`).
   - [x] Verified FFmpeg 1080x1920 vertical export across all 4 layouts:
     - `c01_split.mp4` (592,540 bytes, 1080x1920)
     - `c01_fit.mp4` (2,029,958 bytes, 1080x1920)
     - `c01_crop.mp4` (412,219 bytes, 1080x1920)
     - `c01_pip.mp4` (444,310 bytes, 1080x1920)
   - [x] Verified storage disk usage tracking and cache cleanup (freed 1.1 MB, verified all 4 exports safely preserved).
   - Result: **ALL TESTS PASSED WITH ZERO ERRORS**.
2. **FastAPI Route Test (`tests/test_api.py`)**:
   - [x] Tested `/api/status`: returned online status, CPU core count (4 threads), FFmpeg available, Whisper available.
   - [x] Tested `/api/projects`: listed existing project with candidate count.
   - [x] Tested `/api/projects/{id}/clips/{id}/settings`: successfully updated and saved clip settings.
   - [x] Tested `/api/projects/{id}/clips/{id}/render`: successfully rendered `c01_GTA_6_Crazy_Moment.mp4` via the API endpoint.
   - Result: **ALL FASTAPI ROUTES PASSED WITH STATUS CODE 200**.

## Current Working State
Fully functional, fully local, tested application with complete backend, frontend, models, and demo project.

## Known Limitations & Considerations
- **Ollama**: If Ollama is not installed or running, the application seamlessly defaults to rule-based gaming heuristic titles and categories (no crash, zero degradation of core highlight detection).
- **GPU Acceleration**: The system is tuned for CPU-first execution (Intel Core i5) using INT8 quantization. On PCs with modern NVIDIA GPUs (GTX 1660 / RTX 2060+), PyTorch / CUDA acceleration can optionally be installed for faster transcription.

## Git Status
- Repository initialized at `e:\jari\Python\gta clipper`.
- Initial commit: `6095be2` (or subsequent commit).
- Tracked files include `app/`, `tests/`, `run.py`, `PROJECT_CONTEXT.md`, `README.md`, `.gitignore`.

## Exact Next Development Task
- Optional: Add automatic face-tracking pan across dynamic gameplay scenes.
- Optional: Add one-click multi-clip batch export queue in the UI.

## Instructions for a New Antigravity Session to Continue
1. Open the workspace at `e:\jari\Python\gta clipper`.
2. Read this `PROJECT_CONTEXT.md` file first.
3. Start the application by running:
   ```bash
   python run.py
   ```
4. Access the web interface at `http://127.0.0.1:8000`.
5. Run tests anytime via `python tests/test_pipeline.py` and `python tests/test_api.py`.
