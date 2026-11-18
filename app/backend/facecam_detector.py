"""Facecam Detection & Webcam Framing Engine.

Identifies the streamer's webcam overlay rectangle across video frames.
A facecam is a persistent window containing a live face that remains
in the same area across multiple video samples.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .config import FFMPEG_PATH


@dataclass
class FacecamRegion:
    x: float  # Normalized 0..1 (left)
    y: float  # Normalized 0..1 (top)
    w: float  # Normalized 0..1 (width)
    h: float  # Normalized 0..1 (height)
    confidence: float


def extract_frame_image(video_path: Path, timestamp_s: float) -> np.ndarray | None:
    """Extract a single frame from video at timestamp using FFmpeg."""
    cmd = [
        FFMPEG_PATH, "-ss", f"{timestamp_s:.2f}",
        "-i", str(video_path),
        "-vframes", "1",
        "-f", "image2pipe",
        "-vcodec", "rawvideo",
        "-pix_fmt", "bgr24",
        "-"
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, check=True)
        raw = proc.stdout
        if not raw:
            return None
        # Retrieve dimensions via ffprobe or assume 1920x1080
        # Instead, use JPEG pipe for reliable decoding across any resolution
    except Exception:
        pass

    cmd_jpg = [
        FFMPEG_PATH, "-ss", f"{timestamp_s:.2f}",
        "-i", str(video_path),
        "-vframes", "1",
        "-f", "image2pipe",
        "-vcodec", "mjpeg",
        "-"
    ]
    try:
        proc = subprocess.run(cmd_jpg, capture_output=True, check=True)
        img_arr = np.frombuffer(proc.stdout, dtype=np.uint8)
        frame = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
        return frame
    except Exception:
        return None


def detect_facecam(video_path: Path, duration_s: float) -> FacecamRegion | None:
    """Sample video frames to locate persistent webcam face region."""
    if duration_s < 2.0:
        return None

    # Sample ~12 frames distributed across the video
    timestamps = np.linspace(duration_s * 0.1, duration_s * 0.9, 12)
    face_boxes: list[tuple[float, float, float, float]] = []

    # Use OpenCV Haar cascade or DNN if available
    cascade_file = getattr(cv2, "data", None)
    cascade_path = getattr(cascade_file, "haarcascades", "") + "haarcascade_frontalface_default.xml"
    has_cascade = hasattr(cv2, "CascadeClassifier") and Path(cascade_path).is_file()
    classifier = cv2.CascadeClassifier(cascade_path) if has_cascade else None

    for t in timestamps:
        frame = extract_frame_image(video_path, float(t))
        if frame is None:
            continue
        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        if classifier:
            faces = classifier.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=4, minSize=(40, 40))
            for fx, fy, fw, fh in faces:
                # Convert to normalized 0..1
                face_boxes.append((fx / w, fy / h, fw / w, fh / h))

    if not face_boxes:
        # Return default top-right facecam box if gaming facecam typically sits top-right
        return FacecamRegion(x=0.72, y=0.06, w=0.24, h=0.28, confidence=0.4)

    # Cluster face boxes to find most persistent location
    boxes = np.array(face_boxes)
    # Centers
    cx = boxes[:, 0] + boxes[:, 2] / 2
    cy = boxes[:, 1] + boxes[:, 3] / 2

    # Find medians
    med_cx = float(np.median(cx))
    med_cy = float(np.median(cy))
    med_w = float(np.median(boxes[:, 2]))
    med_h = float(np.median(boxes[:, 3]))

    # Grow box to cover streamer torso / background window (1.8x face width and height)
    cam_w = min(0.40, max(0.18, med_w * 2.2))
    cam_h = min(0.45, max(0.20, med_h * 2.2))
    cam_x = max(0.0, min(1.0 - cam_w, med_cx - cam_w / 2))
    cam_y = max(0.0, min(1.0 - cam_h, med_cy - cam_h / 2))

    return FacecamRegion(
        x=round(cam_x, 3),
        y=round(cam_y, 3),
        w=round(cam_w, 3),
        h=round(cam_h, 3),
        confidence=0.85
    )
