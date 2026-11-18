# GTA Clipper — Project Context & Continuity

## Project Objective
Build a free, locally running, zero-cost desktop highlight clipping application specifically designed for gaming Twitch VODs (with primary focus on GTA gameplay). The workflow:
**Paste Twitch VOD URL -> Download VOD & Chat -> Multi-Signal Highlight Detection (Audio, Chat, VAD, Speech) -> Review & Select Highlights -> Integrated 9:16 Canvas Editor (Crop, Split-Screen Facecam, Captions, Trimming) -> Export Vertical 1080x1920 MP4 Clips.**

## Zero-Cost & Local-First Guarantee
- No paid APIs, no subscriptions, no cloud AI dependencies.
- Zero API keys required.
- Fully runnable on standard hardware (Intel Core i5, 8GB RAM, Windows PC).
- CPU-first INT8 quantized models with optional hardware acceleration.

## Technology Stack & Dependencies
- **Runtime**: Python 3.13.3 (Windows x64)
- **Backend Framework**: FastAPI + Uvicorn + WebSockets / SSE
- **Video & Audio Processing**:
  - `ffmpeg` (installed: 9.0.2 full build with libass, x264, x265)
  - `yt-dlp` (installed: 2026.08.19)
  - `faster-whisper` (installed: 1.2.1 with `ctranslate2` 4.9.0 CPU INT8)
  - `sherpa-onnx` (installed: 2.0.1 for CPU audio event tagging: laughter, shouting, cheering)
  - `numpy` (2.3.2), `scipy` (1.16.3), `opencv-python-headless` (5.0.0.93)
- **Chat Extraction**: Direct Twitch Public GraphQL API (`https://gql.twitch.tv/gql`, operation `VideoCommentsByOffsetOrCursor`, public web client ID `kimne78kx3ncx6brgo4mv6wki5h1ko`)
- **Frontend / UI**: Clean, high-performance HTML5 Canvas 9:16 editor + modern reactive web dashboard. Real-time split-screen rendering, facecam crop bounding box manipulation, caption styles, waveform/hype map, and clip boundary trimmer.
- **Local AI Evaluator (Optional)**: Ollama endpoint (`http://localhost:11434`), gracefully bypassed if Ollama is not installed/running.

## Research Findings on Candidate Repositories
1. **Pireel (`pireel/pireel`)**:
   - **License**: AGPL-3.0-only (strong copyleft).
   - **Architecture**: Large pnpm monorepo with React 19, tailwind 4, mediabunny WebCodecs, designed around external cloud AI endpoints (`StudioProviders`) and NLE XML/FCPXML timeline exports rather than local gaming split-screen FFmpeg rendering.
   - **Conclusion**: Impractical to embed directly without massive overhead, license friction (AGPL-3.0), and missing dedicated gaming layouts (split facecam top + gameplay bottom).
2. **SharkyClips (`utkualsir/sharkyclips`)**:
   - **License**: MIT License (permissive).
   - **Architecture**: Modular Python backend with multi-signal hype detection (chat rolling baseline, loudness jump above baseline, laughter/shouting via CED-mini ONNX, faster-whisper speech context).
   - **Video Rendering & Layouts**: Excellent 9:16 layout math (`split` facecam top + gameplay bottom, `fit` with blurred background, `crop` center cover), libass subtitle burn-in with karaoke/bold styles.
   - **Caveat Discovered**: SharkyClips' `doctor.py` assumed modern CUDA 12 on any detected NVIDIA card, freezing on older legacy GPUs (like NVS 4200M). Our custom system must explicitly default to CPU-first INT8 and handle hardware gracefully.

## Current Project Structure
```
e:\jari\Python\gta clipper\
├── _research\              # Cloned candidate repositories for analysis (sharkyclips, pireel)
├── app\
│   ├── backend\            # FastAPI backend, highlight engine, audio/chat signals, export
│   └── frontend\           # Web-based 9:16 canvas editor and review interface
├── exports\                # Rendered 1080x1920 vertical MP4 clips
├── projects\               # Project workspaces (VODs, chat, audio, signals, candidates)
├── PROJECT_CONTEXT.md      # Mandatory project context and continuity log
└── run.py                  # Single-command launcher for the entire application
```

## Completed Functionality
- Initial environment audit: Verified Python 3.13.3, ffmpeg 9.0.2, git 2.48.1, yt-dlp, Node.js v24.19.0.
- Cloned and analyzed `sharkyclips` and `pireel` repositories and their licenses.
- Successfully installed and verified `faster-whisper` (1.2.1) + `ctranslate2` (4.9.0) with Python 3.13 support.
- Successfully installed and verified `sherpa-onnx` (2.0.1) CPU wheels for audio event detection.
- Identified target hardware: Intel Core i5-2520M, 8GB RAM, Windows 10, CPU-first design.

## Actual Testing Performed
- [x] Environment check: Python, FFmpeg, yt-dlp, git, node
- [x] faster-whisper import and ctranslate2 initialization test
- [x] Hardware detection execution: confirmed CPU Intel Core i5, legacy GPU fallback
- [ ] Multi-signal highlight detection test on sample audio/chat
- [ ] Real-time 9:16 canvas preview test
- [ ] FFmpeg 9:16 vertical clip export test (split-screen facecam + gameplay + subtitles)

## Current Working State
In progress: Implementing the modular backend and frontend engine tailored for gaming/GTA highlights.

## Technical Decisions & Reasons
1. **CPU-First INT8 Execution**: The primary development machine has an Intel Core i5 CPU without modern CUDA support. Using INT8 quantized Whisper and ONNX CPU models guarantees universal portability across any Windows PC.
2. **Candidate-First Speech Transcription**: Instead of transcribing a 4-hour VOD upfront (which would take hours on CPU), speech transcription is performed only on candidate highlight windows (or on-demand for selected clips). This reduces transcription time by over 90%.
3. **Twitch Public GraphQL for Chat**: Download Twitch VOD chat directly via Twitch's public GraphQL endpoint without requiring user login or Twitch API keys.
4. **Interactive 9:16 Canvas Editor**: Provide interactive crop, facecam position, zoom, and live subtitle styling directly in the browser using HTML5 Canvas, perfectly synced to the FFmpeg export filter pipeline.

## Exact Next Development Task
1. Build the core processing engine in `app/backend/`:
   - `twitch_downloader.py`: VOD and chat downloaders.
   - `audio_signals.py`: Loudness jump and laughter/excitement detection.
   - `chat_signals.py`: Chat spike and reaction wave detection.
   - `transcriber.py`: faster-whisper candidate transcription.
   - `highlight_engine.py`: Multi-signal fusion, hype curve, peak picking, candidate generation.
   - `ffmpeg_renderer.py`: 1080x1920 vertical video rendering with split, crop, fit, and subtitles.
2. Build the unified web UI in `app/frontend/` with the 9:16 editor canvas.
3. Wire up FastAPI routes and test end-to-end.

## Instructions for a New Session to Continue
1. Read this `PROJECT_CONTEXT.md` file first.
2. Run `python run.py` to start the application.
3. Check `app/backend/` and `app/frontend/` for implementation files.
4. All project workspace data is saved in `projects/`, and exported clips are saved in `exports/`.
