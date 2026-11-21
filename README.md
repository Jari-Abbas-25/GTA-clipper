# 🎮 GTA Clipper — Free Local Gaming Highlight Clipper

A **100% free, zero-cost, locally running** desktop application that finds genuinely interesting gaming moments from **Twitch VODs** and **YouTube videos**, then exports vertical 9:16 MP4 clips for YouTube Shorts, TikTok, and Instagram Reels.

> **Primary focus:** GTA 6 gameplay on Twitch and YouTube. Works with any gaming content.

---

## ✨ Features

### Multi-Platform Support
- **Twitch VODs** — downloads video + full timestamped chat replay (Twitch GraphQL)
- **YouTube** — downloads video + live chat (archived livestreams with replay enabled)
- **Local files** — drag and drop any MP4/MKV file (optional `.chat.json` sidecar)

### Multi-Signal Highlight Detection
- 📊 **Chat velocity spikes** — rolling baseline analysis, 18× surge detection
- 🎧 **Audio dynamics** — sudden loudness jumps (+12 dB to +28 dB above baseline)
- 😂 **Audio event tagging** — laughter, shouting, cheering via CED-mini ONNX
- 🗣️ **Speech recognition** — faster-whisper INT8 on candidate windows only (saves 90% CPU)
- 🤖 **Local AI ranking** — Ollama (llama3.2:3b / qwen2.5:3b) with heuristic fallback

### 9:16 Canvas Editor
- 4 layout modes: **Split-Screen**, **Full Crop**, **Blurred Fit**, **Picture-in-Picture**
- Drag & resize the **facecam bounding box** directly on the canvas
- TikTok-style **word-by-word subtitle preview**
- **Timeline scrubber** with ±1s nudge trimming
- All edits **auto-saved per clip** — reopen without losing progress

### Export
- 1080×1920 MP4 (libx264 + AAC, burned-in subtitles)
- Native **Windows Save As dialog** to save anywhere
- One-click **storage cleanup** — delete source VOD after exporting, keep clips

### AI Provider Options
- **Ollama** (fully local, free) — recommended
- **DeepSeek API** (free tier available)
- **OpenRouter** (pay-per-use, many models)
- **Heuristics** (always works, no setup required)

---

## 🚀 Quick Start

### 1 — Prerequisites

| Tool | Version | Install |
|---|---|---|
| Python | 3.11+ (3.13 tested) | [python.org](https://python.org) |
| FFmpeg | Any modern build | [ffmpeg.org](https://ffmpeg.org) → add to PATH |

Verify FFmpeg is on PATH:
```bash
ffmpeg -version
```

### 2 — Install Python dependencies

```bash
pip install fastapi uvicorn[standard] pydantic requests yt-dlp \
            faster-whisper numpy scipy sherpa-onnx opencv-python-headless
```

> `opencv-python-headless` is optional. Without it, facecam auto-detection is disabled but all other features work.

### 3 — (Optional) Install Ollama for local AI

Download from [ollama.com](https://ollama.com), then:
```bash
ollama pull llama3.2:3b
```

The app works without Ollama — it falls back to heuristics automatically.

### 4 — Launch

```bash
python run.py
```

Opens `http://127.0.0.1:8000` in your browser. Press `Ctrl+C` to stop.

---

## 🎬 Usage Workflow

### Step 1 — Paste a URL

Paste any supported URL into the input field:

```
# Twitch VOD
https://www.twitch.tv/videos/2283066778

# YouTube livestream archive
https://www.youtube.com/watch?v=dQw4w9WgXcQ
https://youtu.be/dQw4w9WgXcQ

# Local file
C:\Users\User\Videos\gameplay.mp4
```

A **preview card** (title, channel, duration, thumbnail) appears instantly via pre-download probe.

### Step 2 — Start Processing

Click **Start Processing**. The app:
1. Downloads the video and chat
2. Extracts audio (16kHz mono WAV)
3. Runs the multi-signal highlight engine
4. Ranks candidates by hype score (0–100)
5. Optionally evaluates with the AI provider

This takes **2–10 minutes** for a typical 2-hour stream.

### Step 3 — Review Highlights

The **Highlights** view shows ranked candidates:
- Hype score, timestamp, duration, category
- AI-generated title and explanation
- Hype map waveform

### Step 4 — Edit in 9:16 Canvas

Click **Edit 9:16** on any candidate:
- Pick a **layout** (split / crop / fit / pip)
- Drag the **facecam box** to frame the webcam
- Click **Transcribe This Clip** for auto-captions
- Adjust **zoom** and **pan** for gameplay focus
- Fine-tune **trim** with ±1s nudge buttons

### Step 5 — Export

Click **Export 1080×1920 MP4** to render.

When done, click **Save As…** to open a Windows file dialog and copy the clip anywhere.

### Step 6 — Cleanup

Open **Storage Manager** to delete the heavy source VOD and WAV while keeping all rendered clips.

---

## 🧪 Testing

```bash
python tests/test_pipeline.py    # End-to-end pipeline (audio, chat, engine, renderer)
python tests/test_api.py         # FastAPI REST endpoints
```

Both suites run in isolated `tests/scratch/` and do not touch `projects/`.

---

## ⚙️ AI Configuration

Click the **⚙️ AI Settings** button on the dashboard.

| Provider | Free? | Setup |
|---|---|---|
| Ollama | ✅ Fully free | Install Ollama, pull a model |
| Heuristics | ✅ Fully free | None — always available |
| DeepSeek | ⚠️ Free tier | Add API key in settings |
| OpenRouter | ⚠️ Pay-per-use | Add API key in settings |

API keys are stored locally in `.ai_config.json` (git-ignored, never transmitted except to the chosen API endpoint).

---

## 📁 Directory Structure

```
gta clipper/
├── app/
│   ├── backend/
│   │   ├── sources/              # Platform detection, download (Twitch, YouTube, Local)
│   │   ├── server.py             # FastAPI endpoints
│   │   ├── audio_signals.py      # Loudness + audio event detection
│   │   ├── chat_signals.py       # Chat velocity + emote analysis
│   │   ├── highlight_engine.py   # Multi-signal fusion + peak picking
│   │   ├── transcriber.py        # faster-whisper INT8 + ASS subtitles
│   │   ├── ai_evaluator.py       # Ollama / DeepSeek / OpenRouter / heuristics
│   │   ├── renderer.py           # FFmpeg 1080×1920 MP4 export
│   │   ├── storage.py            # Project management
│   │   ├── facecam_detector.py   # Webcam overlay detection (OpenCV)
│   │   └── config.py             # Paths, constants, hardware config
│   └── frontend/
│       ├── index.html            # Main application shell
│       ├── app.js                # Frontend state + API bindings
│       ├── canvas_editor.js      # 9:16 HTML5 Canvas editor
│       └── styles.css            # Dark-mode gaming UI
├── docs/
│   └── CURRENT_WORKFLOW.md       # Detailed workflow and architecture reference
├── models/
│   └── ced-mini/                 # CED-mini audio event ONNX model
├── projects/                     # User project workspaces [git-ignored]
├── exports/                      # Finished MP4 clips [git-ignored]
├── cache/                        # Download cache [git-ignored]
├── temp/                         # Processing temporaries [git-ignored]
├── tests/
│   ├── fixtures/sample_project/  # Demo data (synthetic, never in projects/)
│   ├── test_pipeline.py
│   └── test_api.py
├── run.py                        # Launch script
├── PROJECT_CONTEXT.md            # Developer continuity log
└── README.md                     # This file
```

---

## 📄 Licenses & Attributions

| Component | License | Use |
|---|---|---|
| This application | MIT | Free to use and modify |
| sharkyclips (utkualsir) | MIT | Architecture inspiration, layout math |
| faster-whisper | MIT | INT8 speech recognition |
| ctranslate2 | MIT | INT8 inference backend |
| sherpa-onnx | Apache-2.0 | CED-mini audio event tagging |
| FFmpeg | LGPL/GPL | Video processing and encoding |
| yt-dlp | Unlicense | VOD downloading |
| CED-mini model | CC-BY-4.0 | Audio classification |

---

## 🔧 Troubleshooting

**App doesn't open in browser?**
Manually navigate to `http://127.0.0.1:8000`

**FFmpeg not found?**
Add FFmpeg to your system PATH. Verify with `ffmpeg -version`.

**Whisper model download slow?**
First run downloads the `tiny` model (~75 MB). Subsequent runs are instant.

**YouTube chat unavailable?**
YouTube chat is only available on archived livestreams with chat replay enabled. Regular uploads don't have chat.

**Ollama not connecting?**
Ensure Ollama is running (`ollama serve`). The app falls back to heuristics automatically.

**Probe fails on private/deleted video?**
The app shows a descriptive error. Only public, available videos can be downloaded.

**OpenCV not installed (facecam detection disabled)?**
Run `pip install opencv-python-headless` and restart the server.

---

## 📋 Full Documentation

See [`docs/CURRENT_WORKFLOW.md`](docs/CURRENT_WORKFLOW.md) for the complete workflow reference including:
- Detailed architecture diagram
- Signal weights and thresholds
- Complete REST API reference
- Storage layout
- All known limitations
