# 🎮 GTA Clipper — Free Local Gaming Highlight Clipper

A 100% free, zero-cost, locally running desktop application designed to find genuinely interesting gaming moments from Twitch VODs (with primary focus on GTA gameplay) and export vertical 9:16 MP4 clips for YouTube Shorts, TikTok, and Instagram Reels.

## ✨ Core Highlights & Features

- **Zero-Cost Guarantee**: No paid APIs, cloud subscriptions, or API keys required. Runs entirely locally on your Windows PC.
- **CPU-First Architecture**: Powered by Intel Core i5 CPU with INT8 quantized models (`faster-whisper`, `sherpa-onnx` CED-mini), keeping memory footprint under 4GB and overall app size under 10GB.
- **Multi-Signal Highlight Engine**:
  - **Twitch Chat Velocity & Spikes**: Rolling median baseline analysis, emote wave detection (`KEKW`, `WTF`, `POG`, `OMG`, `LUL`), and unique user reaction bursts.
  - **Audio Dynamics & Sudden Loudness Jumps**: Filters out steady background music and gameplay noise to isolate true shout and celebration spikes (+12 dB to +28 dB jumps).
  - **Audio Event Tagging**: Laughter, shouting, and cheering detection via CED-mini ONNX model (with high-frequency spectral dynamics fallback).
  - **Candidate-First Speech Recognition**: `faster-whisper` INT8 transcription runs exclusively on candidate highlight windows, saving 90%+ processing time compared to full-VOD transcription.
  - **Local AI Evaluator**: Connects optionally to local Ollama (e.g. `llama3.2:3b`, `qwen2.5:3b`) for viral scoring and punchy titles, with seamless heuristic fallback when Ollama is offline.
- **Integrated 9:16 Canvas Editor**:
  - Real-time 60fps HTML5 Canvas rendering of the selected clip.
  - 4 Gaming Layout Modes:
    1. **Split-Screen**: Streamer webcam on top (~40%), Gameplay on bottom (~60%).
    2. **9:16 Full Crop**: Gameplay cover crop with adjustable pan focus and zoom (1.0x - 2.5x).
    3. **Blurred Fit**: 16:9 gameplay centered with blurred gameplay background fill.
    4. **Picture-in-Picture (PiP)**: Full gameplay with floating facecam box.
  - **Interactive Webcam Framing**: Click, drag, and resize the yellow facecam bounding box directly on the canvas!
  - **Live Subtitle Preview**: Word-by-word active highlighted subtitles (TikTok-style Gold glow, Karaoke, Clean box, Minimal).
  - **Timeline Scrubber & Trimming**: Visual scrubber, start/end time inputs, and instant -1s/+1s nudging.
  - **State Persistence**: Saves all your edits to `clip_settings/` so you can reopen projects without losing progress.
- **High-Performance Local FFmpeg Export**:
  - Local CPU rendering with `libx264` and `aac`.
  - Burns in styled subtitles using FFmpeg's `ass` filter.
  - Exports crisp 1080x1920 MP4 clips directly into `exports/`.
- **Storage Management**:
  - Clear directory separation: `source.mp4`, `audio.wav`, `chat.json`, `exports/`.
  - Built-in one-click disk cleanup tool to delete heavy source VODs and cache while safely preserving finished clips.

---

## 🚀 Quick Start Guide

### 1. Prerequisites
- **Python**: 3.11+ (Python 3.13 supported)
- **FFmpeg**: Installed and on system PATH (`ffmpeg -version`)

### 2. Run the Application
Open a terminal in this directory and execute:
```bash
python run.py
```
This starts the local FastAPI server at `http://127.0.0.1:8000` and automatically opens the user interface in your default browser.

### 3. Usage Workflow
1. **Paste Twitch VOD URL**: Enter the Twitch VOD URL (e.g., `https://www.twitch.tv/videos/123456789`) or provide a local `.mp4` file path.
2. **Automatic Download & Analysis**: GTA Clipper downloads the video stream and Twitch chat replay, extracts audio, and computes the multi-signal hype curve.
3. **Review Highlights**: Browse the Hype Map engagement wave and candidate highlights ranked by engagement score.
4. **Edit in 9:16 Canvas**: Click **Edit 9:16** on any candidate to open the interactive editor:
   - Adjust the facecam box position and size.
   - Adjust gameplay focus and zoom.
   - Click **Transcribe This Clip** to generate timestamped captions.
   - Fine-tune trim boundaries with -1s/+1s nudges.
5. **Export**: Click **Export 1080x1920 MP4** to render the finished clip into the `exports/` folder.
6. **Storage Cleanup**: Use the Storage Manager modal to remove temporary source videos when finished.

---

## 🧪 Testing

To run the automated end-to-end test suite:
```bash
python tests/test_pipeline.py
python tests/test_api.py
```

---

## 📁 Project Directory Structure

```
gta clipper/
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
├── models/                       # Quantized ONNX & Whisper models
├── projects/                     # Project workspaces (source VOD, chat, cache, settings)
├── tests/
│   ├── test_pipeline.py          # End-to-end pipeline test
│   └── test_api.py               # REST API test
├── run.py                        # Single-command application launcher
├── PROJECT_CONTEXT.md            # Mandatory project context & continuity log
└── README.md                     # Documentation & user guide
```

---

## 📄 License & Open-Source Attributions
- Application: MIT License.
- Reused components & inspiration: `sharkyclips` (MIT License).
- Transcription: `faster-whisper` (MIT License) powered by `ctranslate2`.
- Audio Tagging: `sherpa-onnx` (Apache-2.0) with CED-mini model.
- Media Processing: `FFmpeg` (LGPL/GPL).
