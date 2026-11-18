#!/usr/bin/env python3
"""GTA Clipper — Launcher Script.

Runs the local FastAPI server and launches the web desktop interface.
Usage:
    python run.py [--port 8000] [--no-browser]
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))


def check_prerequisites():
    """Verify required tools before starting."""
    if not shutil.which("ffmpeg"):
        print("⚠️ Warning: 'ffmpeg' was not found on your system PATH.")
        print("Please ensure FFmpeg is installed and accessible.")

    try:
        import fastapi
        import uvicorn
        import numpy
        import scipy
    except ImportError as e:
        print(f"❌ Missing required Python library: {e}")
        print("Please run: pip install fastapi uvicorn numpy scipy")
        sys.exit(1)


def open_browser_delayed(url: str, delay: float = 1.2):
    def _open():
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception:
            pass
    threading.Thread(target=_open, daemon=True).start()


def main():
    parser = argparse.ArgumentParser(description="GTA Clipper — Free Local Gaming Highlight Clipper")
    parser.add_argument("--host", default="127.0.0.1", help="Host address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on (default: 8000)")
    parser.add_argument("--no-browser", action="store_true", help="Do not open browser automatically")
    args = parser.parse_args()

    check_prerequisites()

    url = f"http://{args.host}:{args.port}"
    print("=" * 65)
    print(" 🎮 GTA CLIPPER — Free Local Gaming Highlight Clipper")
    print(f" 🚀 Running locally at: {url}")
    print(" ⚡ CPU-First INT8 Quantized Architecture (Zero API keys needed)")
    print("=" * 65)

    if not args.no_browser:
        open_browser_delayed(url)

    import uvicorn
    from app.backend.server import app

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
