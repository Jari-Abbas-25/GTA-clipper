"""Twitch Chat Signal Analyzer.

Computes:
1. Chat velocity (messages per second)
2. Rolling median baseline (120s window)
3. Spike ratio (e.g. 5.2x baseline)
4. Emote bursts, reaction keywords, and emoji spikes
5. Copy-paste spam wave detection across unique users
6. Stream broadcast delay adjustment (shifts chat curve backwards by 5s)
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.ndimage import median_filter

STREAM_DELAY_SECONDS = 5.0
BASELINE_WINDOW_S = 121
REACTION_WINDOW_S = 5
MIN_CHAT_MESSAGES = 10

REACTION_PATTERNS = [
    # Universal / Twitch emotes
    r"\b(?:kekw|lul|omegalul|pepelaugh|pog|poggers|pogchamp|kappa|monkas|pepega|sadge|copium)\b",
    # Gaming & GTA reactions
    r"\b(?:wtf|omg|bruh|holy|insane|clutch|wasted|no way|gg|ez|cheat|aimbot|headshot|busted)\b",
    # Laughter representations
    r"(?:ha){3,}|(?:ah){3,}|(?:he){3,}|(?:ja){3,}|(?:xd)+|lmf?ao+|rofl+",
    # Punctuation bursts
    r"\?{2,}|\!{2,}|\.{3,}",
    # Reaction emojis
    r"😂|🤣|😭|💀|😱|🔥|👀|😳|🤯|😮|👏"
]
REACTION_REGEX = re.compile("|".join(REACTION_PATTERNS), re.IGNORECASE)


@dataclass
class ChatReason:
    time: float
    code: str   # "chat_spike", "chat_reactions", "reaction_wave"
    value: str  # "5.2x", "KEKW"
    score: float


def normalize_reaction_text(text: str) -> str:
    t = text.strip().casefold()
    # Collapse repetitive letters (e.g., "kekwwww" -> "kekww", "noooo" -> "noo")
    return re.sub(r"(.)\1{2,}", r"\1\1", t)


def compute_chat_signals(
    chat_path: Path,
    duration_s: float
) -> tuple[np.ndarray, list[ChatReason]]:
    """Analyze chat messages and calculate normalized hype score [0..1] per second."""
    total_seconds = max(1, math.ceil(duration_s))
    if not chat_path.is_file():
        return np.zeros(total_seconds, dtype=np.float32), []

    try:
        with open(chat_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return np.zeros(total_seconds, dtype=np.float32), []

    messages = data.get("messages", [])
    if len(messages) < MIN_CHAT_MESSAGES:
        return np.zeros(total_seconds, dtype=np.float32), []

    # Map messages to 1-second bins shifted by delay
    msg_counts = np.zeros(total_seconds, dtype=np.float32)
    reaction_counts = np.zeros(total_seconds, dtype=np.float32)
    reaction_texts: dict[int, Counter] = {}

    # Copy-paste wave detection across unique users
    by_text: dict[str, list[tuple[float, int]]] = {}
    for t_sec, text, author_idx in messages:
        norm = normalize_reaction_text(text)[:40]
        if norm and len(norm) > 1 and not (norm.isdigit() and len(norm) <= 2):
            by_text.setdefault(norm, []).append((float(t_sec), int(author_idx)))

    wave_keys: set[str] = set()
    for key, instances in by_text.items():
        if len(instances) < 3:
            continue
        times = [x[0] for x in instances]
        for i in range(len(times) - 2):
            # 3 occurrences within 5 seconds with at least 3 distinct users
            if (times[i + 2] - times[i]) <= REACTION_WINDOW_S:
                unique_authors = {instances[j][1] for j in range(i, i + 3)}
                if len(unique_authors) >= 3:
                    wave_keys.add(key)
                    break

    for t_sec, text, _author_idx in messages:
        target_s = int(float(t_sec) - STREAM_DELAY_SECONDS)
        if 0 <= target_s < total_seconds:
            msg_counts[target_s] += 1.0
            norm = normalize_reaction_text(text)[:40]
            is_rx = bool(REACTION_REGEX.search(text)) or (norm in wave_keys)
            if is_rx:
                reaction_counts[target_s] += 1.0
                if target_s not in reaction_texts:
                    reaction_texts[target_s] = Counter()
                # Find matched keyword or use cleaned word
                m = REACTION_REGEX.search(text)
                found = m.group(0).upper() if m else norm.upper()
                reaction_texts[target_s][found] += 1

    # Rolling median baseline for velocity
    baseline = median_filter(msg_counts, size=BASELINE_WINDOW_S, mode="nearest")
    baseline = np.maximum(baseline, 0.4)  # Floor to avoid div-by-zero

    # Spike ratio
    excess = msg_counts - baseline
    spike_ratio = excess / baseline

    # Score synthesis: combines message velocity spike and reaction burst density
    rate_score = np.clip((spike_ratio - 1.0) / 4.0, 0.0, 1.0)
    rx_ratio = np.where(msg_counts > 0, reaction_counts / np.maximum(msg_counts, 1.0), 0.0)
    rx_density_score = np.clip((reaction_counts - 2.0) / 6.0, 0.0, 1.0)
    combined = 0.55 * rate_score + 0.45 * (rx_ratio * rx_density_score)
    combined = np.clip(combined, 0.0, 1.0).astype(np.float32)

    # Peak detection for reasons
    reasons: list[ChatReason] = []
    for s in range(1, total_seconds - 1):
        if combined[s] >= 0.40 and combined[s] >= combined[s - 1] and combined[s] >= combined[s + 1]:
            score = float(combined[s])
            ratio = float(spike_ratio[s]) + 1.0
            if ratio >= 2.0:
                reasons.append(ChatReason(float(s), "chat_spike", f"{ratio:.1f}x", score))

            if s in reaction_texts and reaction_texts[s]:
                top_rx, count = reaction_texts[s].most_common(1)[0]
                if count >= 2:
                    reasons.append(ChatReason(float(s), "chat_reactions", top_rx, score))

    return combined, reasons
