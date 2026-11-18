"""Multi-Signal Highlight Detection & Ranking Engine.

Fuses:
1. Twitch Chat Activity (Velocity spike, emote bursts, reaction waves)
2. Audio Dynamics (Sudden loudness jump above rolling baseline)
3. Audio Events (Laughter, shouting, cheering via CED-mini or spectral energy)
4. Agreement Bonus (Boost when multiple independent signals agree)

Performs peak picking, smart boundary shaping (pre-roll setup + reaction tail),
non-maximum suppression, and ranking.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks

from .ai_evaluator import evaluate_candidate
from .audio_signals import AudioReason, compute_audio_events, compute_loudness_signal, compute_rms_db
from .chat_signals import ChatReason, compute_chat_signals
from .config import (
    DEFAULT_CLIP_IDEAL,
    DEFAULT_CLIP_MAX,
    DEFAULT_CLIP_MIN,
    DEFAULT_MIN_GAP,
    DEFAULT_POST_ROLL,
    DEFAULT_PRE_ROLL,
)


@dataclass
class HighlightCandidate:
    id: str
    rank: int
    start: float
    end: float
    duration: float
    peak: float
    hype_score: int
    reasons: list[dict]
    category: str = "Gaming Highlight"
    explanation: str = ""
    suggested_title: str = ""
    ai_powered: bool = False
    accepted: bool = True  # Selected for clipping by default


@dataclass
class DetectionResult:
    duration: float
    candidates: list[HighlightCandidate]
    hype_curve: list[int]          # Max-pooled downsampled curve (0..100)
    signals_present: list[str]     # ["chat", "loudness", "events"]
    reasons_summary: list[dict]


def fuse_signals(
    duration_s: float,
    chat_curve: np.ndarray | None,
    loudness_curve: np.ndarray,
    event_curve: np.ndarray | None,
    weights: dict[str, float] | None = None
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Combine available signals into smoothed hype curve [0..1]."""
    total_seconds = max(1, math.ceil(duration_s))
    w_map = weights or {"chat": 0.40, "loudness": 0.35, "events": 0.25}

    active_signals = []
    accum = np.zeros(total_seconds, dtype=np.float32)
    weight_sum = 0.0

    # Loudness (if audio energy detected)
    if np.max(loudness_curve) > 0.02:
        accum += loudness_curve * w_map["loudness"]
        weight_sum += w_map["loudness"]
        active_signals.append("loudness")

    # Chat (if available)
    if chat_curve is not None and np.max(chat_curve) > 0.05:
        accum += chat_curve * w_map["chat"]
        weight_sum += w_map["chat"]
        active_signals.append("chat")

    # Audio events (laughter / shouting)
    if event_curve is not None and np.max(event_curve) > 0.05:
        accum += event_curve * w_map["events"]
        weight_sum += w_map["events"]
        active_signals.append("events")

    # If all curves were near-zero, fall back to loudness curve
    if weight_sum == 0.0:
        accum = loudness_curve
        weight_sum = 1.0
        active_signals.append("loudness")

    # Normalize by active weights
    raw_hype = accum / max(weight_sum, 0.01)

    # Agreement bonus: if 2 or more signals fire simultaneously (>0.35), boost by up to 25%
    agreed = np.zeros(total_seconds, dtype=np.float32)
    sig_count = (loudness_curve > 0.35).astype(np.int32)
    if chat_curve is not None:
        sig_count += (chat_curve > 0.35).astype(np.int32)
    if event_curve is not None:
        sig_count += (event_curve > 0.35).astype(np.int32)

    agreed = np.where(sig_count >= 2, 0.20, 0.0)
    boosted = np.clip(raw_hype + agreed, 0.0, 1.0)

    # Gaussian smoothing to create continuous hype wave
    smoothed = gaussian_filter1d(boosted, sigma=2.0)
    return raw_hype, smoothed, active_signals


def calculate_clip_window(
    peak_s: float,
    curve: np.ndarray,
    duration_s: float,
    min_len: float = DEFAULT_CLIP_MIN,
    ideal_len: float = DEFAULT_CLIP_IDEAL,
    max_len: float = DEFAULT_CLIP_MAX,
    pre_roll: float = DEFAULT_PRE_ROLL,
    post_roll: float = DEFAULT_POST_ROLL
) -> tuple[float, float]:
    """Calculate natural start and end boundaries around a highlight peak."""
    n = len(curve)
    p = int(round(peak_s))
    threshold = curve[p] * 0.45

    # Walk left to find setup valley
    left = p
    while left > 0 and curve[left - 1] >= threshold and (p - left) < max_len:
        left -= 1

    # Walk right to find calm-down valley
    right = p
    while right < n - 1 and curve[right + 1] >= threshold and (right - p) < max_len:
        right += 1

    # Apply pre-roll and post-roll
    start = max(0.0, min(float(left), peak_s - pre_roll))
    end = min(duration_s, max(float(right), peak_s + post_roll))

    # Duration constraints
    length = end - start
    if length < min_len:
        diff = min_len - length
        start = max(0.0, start - diff * 0.4)
        end = min(duration_s, end + diff * 0.6)

    if end - start > max_len:
        # Keep peak well inside clip
        start = max(0.0, peak_s - max_len * 0.6)
        end = min(duration_s, start + max_len)

    return round(start, 2), round(end, 2)


def run_highlight_detection(
    wav_path: Path,
    chat_path: Path | None = None,
    top_n: int = 15,
    min_score_threshold: float = 0.25
) -> DetectionResult:
    """Full highlight analysis pipeline."""
    # 1. Audio analysis
    rms_db, duration_s = compute_rms_db(wav_path)
    loudness_curve, audio_reasons = compute_loudness_signal(rms_db, duration_s)
    events_curve, event_reasons = compute_audio_events(wav_path, duration_s)

    # 2. Chat analysis (if chat.json exists)
    chat_curve = None
    chat_reasons = []
    if chat_path and chat_path.is_file():
        chat_curve, chat_reasons = compute_chat_signals(chat_path, duration_s)

    # 3. Multi-signal fusion
    raw_hype, smoothed_hype, active_sigs = fuse_signals(
        duration_s, chat_curve, loudness_curve, events_curve
    )

    # 4. Peak picking
    min_dist_frames = int(min(DEFAULT_MIN_GAP, max(5, duration_s / 5)))
    peaks, props = find_peaks(
        smoothed_hype,
        height=min_score_threshold,
        distance=min_dist_frames,
        prominence=0.06
    )

    if len(peaks) == 0:
        # Fallback to local peaks with relaxed threshold
        peaks, _ = find_peaks(smoothed_hype, distance=min_dist_frames)

    if len(peaks) == 0 and len(smoothed_hype) > 0:
        # Absolute fallback: global peak
        peaks = np.array([int(np.argmax(smoothed_hype))])

    all_reasons = audio_reasons + event_reasons + chat_reasons

    # 5. Extract candidate intervals
    raw_candidates = []
    for p in peaks:
        peak_time = float(p)
        peak_score = float(smoothed_hype[p])
        start, end = calculate_clip_window(peak_time, smoothed_hype, duration_s)

        # Gather relevant reasons within window
        matched_reasons = []
        for r in all_reasons:
            if (start - 2.0) <= r.time <= (end + 2.0):
                matched_reasons.append({
                    "time": round(r.time, 1),
                    "code": r.code,
                    "value": r.value,
                    "score": round(r.score, 2)
                })

        # Deduplicate reasons by code
        unique_reasons = []
        seen_codes = set()
        for mr in sorted(matched_reasons, key=lambda x: x["score"], reverse=True):
            if mr["code"] not in seen_codes:
                seen_codes.add(mr["code"])
                unique_reasons.append(mr)

        raw_candidates.append({
            "peak": peak_time,
            "start": start,
            "end": end,
            "raw_score": peak_score,
            "reasons": unique_reasons[:4]
        })

    # Sort candidates by raw score descending
    raw_candidates.sort(key=lambda c: c["raw_score"], reverse=True)

    # 6. Non-maximum suppression (eliminate heavily overlapping clips)
    final_picks = []
    for cand in raw_candidates:
        c_start, c_end = cand["start"], cand["end"]
        overlap = False
        for chosen in final_picks:
            o_start = max(c_start, chosen["start"])
            o_end = min(c_end, chosen["end"])
            if o_end > o_start:
                intersection = o_end - o_start
                union = max(c_end, chosen["end"]) - min(c_start, chosen["start"])
                if (intersection / union) > 0.35:
                    overlap = True
                    break
        if not overlap:
            final_picks.append(cand)
            if len(final_picks) >= top_n:
                break

    # 7. Rank and evaluate candidates (0..100 relative hype score)
    max_score = max((c["raw_score"] for c in final_picks), default=1.0)
    candidates_list: list[HighlightCandidate] = []

    for i, c in enumerate(final_picks):
        rank = i + 1
        cid = f"c{rank:02d}"
        scaled_score = int(np.clip(round((c["raw_score"] / max(max_score, 0.01)) * 95.0 + 5.0), 5, 99))

        # Evaluate candidate with AI or heuristic
        eval_res = evaluate_candidate(
            start=c["start"],
            end=c["end"],
            hype_score=scaled_score,
            reasons=c["reasons"],
            transcript_text=""
        )

        candidates_list.append(HighlightCandidate(
            id=cid,
            rank=rank,
            start=c["start"],
            end=c["end"],
            duration=round(c["end"] - c["start"], 1),
            peak=c["peak"],
            hype_score=scaled_score,
            reasons=c["reasons"],
            category=eval_res.category,
            explanation=eval_res.explanation,
            suggested_title=eval_res.suggested_title,
            ai_powered=eval_res.ai_powered
        ))

    # Downsample smoothed hype curve to 1 point per second (or max-pooled if long)
    points = [int(round(v * 100)) for v in smoothed_hype]

    reasons_summary = [
        {"code": "loudness_spike", "label": "Loudness Jump", "count": len(audio_reasons)},
        {"code": "laughter", "label": "Laughter / Joy", "count": sum(1 for r in event_reasons if r.code == "laughter")},
        {"code": "shouting", "label": "Shouting / Hype", "count": sum(1 for r in event_reasons if r.code == "shouting")},
        {"code": "chat_spike", "label": "Chat Spikes", "count": sum(1 for r in chat_reasons if r.code == "chat_spike")},
        {"code": "chat_reactions", "label": "Emote Waves", "count": sum(1 for r in chat_reasons if r.code == "chat_reactions")},
    ]

    return DetectionResult(
        duration=round(duration_s, 2),
        candidates=candidates_list,
        hype_curve=points,
        signals_present=active_sigs,
        reasons_summary=reasons_summary
    )
