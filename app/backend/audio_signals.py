"""Audio Analysis & Event Detection Engine.

Extracts 16 kHz mono WAV and analyzes:
1. Sudden loudness jumps above a rolling baseline (avoids false positives from steady loud music/explosions)
2. Audio excitement & laughter/shouting using sherpa-onnx CED-mini or high-frequency spectral dynamics fallback
3. Peak picking and reason event generation
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import tarfile
import urllib.request
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
from scipy.ndimage import median_filter

from .config import FFMPEG_PATH, MODELS_DIR

SAMPLE_RATE = 16000
SILENCE_DB = -55.0
BASELINE_S = 60
JUMP_LOOKBACK_S = 3
FPS = 2  # 2 frames per second (0.5s interval)

# CED-mini audio event model (10MB INT8 ONNX, Apache-2.0)
CED_DIR = MODELS_DIR / "ced-mini"
CED_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "audio-tagging-models/sherpa-onnx-ced-mini-audio-tagging-2024-04-19.tar.bz2"
)
CED_FILES = ("model.int8.onnx", "class_labels_indices.csv")


@dataclass
class AudioReason:
    time: float
    code: str  # "loudness_spike", "laughter", "shouting", "cheering"
    value: str  # "+12 dB", "laughter"
    score: float


def extract_audio_wav(
    video_path: Path,
    wav_path: Path,
    on_progress: Callable[[float], None] | None = None
) -> Path:
    """Extract 16kHz mono 16-bit WAV from video using FFmpeg."""
    if wav_path.is_file() and wav_path.stat().st_size > 44:
        return wav_path

    wav_path.parent.mkdir(parents=True, exist_ok=True)
    temp_wav = wav_path.with_suffix(".temp.wav")

    cmd = [
        FFMPEG_PATH, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video_path),
        "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE),
        "-c:a", "pcm_s16le",
        str(temp_wav)
    ]

    subprocess.run(cmd, check=True)
    if temp_wav.is_file():
        if wav_path.is_file():
            wav_path.unlink()
        temp_wav.rename(wav_path)
    return wav_path


def get_wav_duration(wav_path: Path) -> float:
    with wave.open(str(wav_path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def compute_rms_db(wav_path: Path) -> tuple[np.ndarray, float]:
    """Compute streamed RMS dB values every 0.5 seconds."""
    hop = int(SAMPLE_RATE * 0.5)
    block_samples = hop * 120  # 60 seconds per block
    db_list: list[np.ndarray] = []

    with wave.open(str(wav_path), "rb") as w:
        total_frames = w.getnframes()
        sr = w.getframerate()
        duration = total_frames / float(sr)

        while True:
            raw = w.readframes(block_samples)
            if not raw:
                break
            samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            n_hops = len(samples) // hop
            if n_hops > 0:
                frames = samples[: n_hops * hop].reshape(n_hops, hop)
                mean_sq = np.mean(frames ** 2, axis=1)
                db_list.append(10.0 * np.log10(mean_sq + 1e-10))
            rem = len(samples) % hop
            if rem > 0:
                tail = samples[n_hops * hop :]
                db_list.append(np.array([10.0 * np.log10(np.mean(tail ** 2) + 1e-10)]))

    if not db_list:
        return np.array([-80.0], dtype=np.float32), 0.0

    rms_db = np.concatenate(db_list).astype(np.float32)
    return rms_db, duration


def compute_loudness_signal(rms_db: np.ndarray, duration_s: float) -> tuple[np.ndarray, list[AudioReason]]:
    """Compute sudden loudness jump above rolling baseline.
    
    Returns:
    - 1-second resolution score curve [0..1]
    - List of AudioReason events
    """
    total_seconds = max(1, math.ceil(duration_s))
    if len(rms_db) == 0:
        return np.zeros(total_seconds, dtype=np.float32), []

    db = rms_db.astype(np.float64)
    voiced = np.where(db > SILENCE_DB, db, np.nan)
    fill = np.nanmedian(voiced) if np.isfinite(voiced).any() else -40.0
    valid_db = np.where(np.isfinite(voiced), voiced, fill)

    # Rolling median filter (adaptive for short or long clips)
    filter_size = min(max(3, len(valid_db) // 2 * 2 + 1), BASELINE_S * FPS + 1)
    if len(valid_db) >= filter_size:
        baseline = median_filter(valid_db, size=filter_size, mode="nearest")
    else:
        baseline = np.full_like(valid_db, fill)
    excess = db - baseline

    # Short lookback jump (now vs average of last 3 seconds)
    k = max(1, JUMP_LOOKBACK_S * FPS)
    csum = np.concatenate([[0.0], np.cumsum(db)])
    idx = np.arange(len(db))
    a = np.maximum(0, idx - k)
    cnt = idx - a
    prev_mean = np.where(cnt > 0, (csum[idx] - csum[a]) / np.maximum(cnt, 1), db)
    jump = db - prev_mean

    # Frame score combination
    def clip01(v):
        return np.clip(v, 0.0, 1.0)

    frame_score = 0.6 * clip01((excess - 2.0) / 8.0) + 0.4 * clip01((jump - 2.5) / 6.0)
    frame_score[db < SILENCE_DB] = 0.0

    # Aggregate to 1-second resolution
    scores_1s = np.zeros(total_seconds, dtype=np.float32)
    excess_1s = np.zeros(total_seconds, dtype=np.float32)

    for s in range(total_seconds):
        i0 = s * FPS
        i1 = min(len(frame_score), (s + 1) * FPS)
        if i1 > i0:
            scores_1s[s] = np.max(frame_score[i0:i1])
            excess_1s[s] = np.max(excess[i0:i1])

    # Find peaks for reason events
    reasons: list[AudioReason] = []
    for s in range(1, total_seconds - 1):
        if scores_1s[s] > 0.45 and scores_1s[s] >= scores_1s[s - 1] and scores_1s[s] >= scores_1s[s + 1]:
            if excess_1s[s] >= 3.0:
                reasons.append(
                    AudioReason(
                        time=float(s),
                        code="loudness_spike",
                        value=f"+{excess_1s[s]:.0f} dB",
                        score=float(scores_1s[s])
                    )
                )

    return scores_1s, reasons


def ensure_ced_model() -> bool:
    """Download CED-mini audio event model if missing."""
    if all((CED_DIR / f).is_file() for f in CED_FILES):
        return True
    try:
        CED_DIR.mkdir(parents=True, exist_ok=True)
        archive_path = CED_DIR / "ced_download.tar.bz2"
        urllib.request.urlretrieve(CED_URL, archive_path)
        with tarfile.open(archive_path, "r:bz2") as tar:
            for member in tar.getmembers():
                base = Path(member.name).name
                if base in CED_FILES and member.isfile():
                    src = tar.extractfile(member)
                    if src:
                        (CED_DIR / base).write_bytes(src.read())
        archive_path.unlink(missing_ok=True)
        return all((CED_DIR / f).is_file() for f in CED_FILES)
    except Exception:
        return False


def compute_audio_events(wav_path: Path, duration_s: float) -> tuple[np.ndarray, list[AudioReason]]:
    """Detect laughter, shouting, and cheering using sherpa-onnx or spectral dynamics.
    
    Returns:
    - 1-second resolution audio excitement score curve [0..1]
    - List of AudioReason events
    """
    total_seconds = max(1, math.ceil(duration_s))
    scores_1s = np.zeros(total_seconds, dtype=np.float32)
    reasons: list[AudioReason] = []

    # Attempt sherpa-onnx CED-mini if model ready
    has_model = ensure_ced_model()
    has_sherpa = False
    try:
        import sherpa_onnx
        has_sherpa = True
    except ImportError:
        pass

    if has_model and has_sherpa:
        try:
            import csv
            # Read class labels
            labels_path = CED_DIR / "class_labels_indices.csv"
            labels_map: dict[str, int] = {}
            with open(labels_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    labels_map[row["display_name"]] = int(row["index"])

            laughter_indices = {labels_map[k] for k in ["Laughter", "Giggle", "Chuckle, chortle"] if k in labels_map}
            shouting_indices = {labels_map[k] for k in ["Shout", "Yell", "Screaming", "Whoop"] if k in labels_map}
            cheering_indices = {labels_map[k] for k in ["Cheering", "Applause", "Clapping"] if k in labels_map}

            config = sherpa_onnx.AudioTaggingConfig(
                model=sherpa_onnx.OfflineModelConfig(
                    ced=str(CED_DIR / "model.int8.onnx"),
                    num_threads=2,
                    debug=False
                ),
                labels=str(labels_path),
                top_k=5
            )
            tagger = sherpa_onnx.AudioTagging(config)

            # Analyze 2-second windows
            window_len = int(SAMPLE_RATE * 2.0)
            with wave.open(str(wav_path), "rb") as w:
                for s in range(0, total_seconds, 2):
                    w.setpos(min(w.getnframes(), s * SAMPLE_RATE))
                    raw = w.readframes(window_len)
                    if len(raw) < window_len:
                        break
                    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                    stream = tagger.create_stream()
                    stream.accept_waveform(SAMPLE_RATE, samples)
                    events = tagger.compute(stream)

                    max_laughter = 0.0
                    max_shout = 0.0
                    max_cheer = 0.0

                    for ev in events:
                        idx = ev.index
                        prob = ev.prob
                        if idx in laughter_indices:
                            max_laughter = max(max_laughter, prob)
                        elif idx in shouting_indices:
                            max_shout = max(max_shout, prob)
                        elif idx in cheering_indices:
                            max_cheer = max(max_cheer, prob)

                    score = min(1.0, max_laughter * 1.5 + max_shout * 1.4 + max_cheer * 1.2)
                    for sec in range(s, min(total_seconds, s + 2)):
                        scores_1s[sec] = max(scores_1s[sec], score)

                    if max_laughter >= 0.35:
                        reasons.append(AudioReason(float(s), "laughter", "laughter", float(max_laughter)))
                    elif max_shout >= 0.35:
                        reasons.append(AudioReason(float(s), "shouting", "shouting", float(max_shout)))
                    elif max_cheer >= 0.40:
                        reasons.append(AudioReason(float(s), "cheering", "cheering", float(max_cheer)))

            return scores_1s, reasons
        except Exception:
            pass  # Fall back to spectral energy dynamics

    # High-performance spectral / high-frequency energy ratio fallback
    # Laughter and screaming create notable high-frequency energy shifts (1500Hz - 6000Hz)
    hop_len = SAMPLE_RATE
    with wave.open(str(wav_path), "rb") as w:
        for s in range(total_seconds):
            raw = w.readframes(hop_len)
            if not raw:
                break
            samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            if len(samples) < hop_len // 2:
                break
            # Zero-crossing rate & high frequency energy estimate
            zcr = np.mean(np.abs(np.diff(np.sign(samples)))) * 0.5
            rms = np.sqrt(np.mean(samples ** 2) + 1e-10)
            if rms > 0.04 and zcr > 0.15:
                score = float(np.clip((zcr - 0.15) * 3.0 + (rms - 0.04) * 2.0, 0.0, 1.0))
                scores_1s[s] = score
                if score > 0.6:
                    reasons.append(AudioReason(float(s), "shouting", "audio excitement", score))

    return scores_1s, reasons
