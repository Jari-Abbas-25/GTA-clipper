"""Speech Transcription & Timestamped Caption Generator.

Uses faster-whisper on CPU with INT8 quantization.
Optimized for candidate-window transcription (saving 90%+ CPU time compared to full-VOD transcription).
Generates word-level timestamps and ASS subtitle files for FFmpeg burning.
"""

from __future__ import annotations

import math
import os
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

try:
    from faster_whisper import WhisperModel
    FASTER_WHISPER_AVAILABLE = True
except ImportError:
    FASTER_WHISPER_AVAILABLE = False


@dataclass
class WordTiming:
    start: float  # Absolute seconds from clip/video start
    end: float
    word: str


@dataclass
class SubtitleSegment:
    start: float
    end: float
    text: str
    words: list[WordTiming]


_whisper_model_cache: dict[str, WhisperModel] = {}


def get_whisper_model(model_size: str = "tiny") -> WhisperModel:
    """Retrieve or initialize cached INT8 CPU faster-whisper model."""
    if not FASTER_WHISPER_AVAILABLE:
        raise RuntimeError("faster-whisper is not installed. Run: pip install faster-whisper")

    if model_size not in _whisper_model_cache:
        # compute_type='int8' ensures low RAM and fast CPU inference on Intel Core i5
        model = WhisperModel(model_size, device="cpu", compute_type="int8", cpu_threads=4)
        _whisper_model_cache[model_size] = model
    return _whisper_model_cache[model_size]


def read_audio_window(wav_path: Path, start_s: float, end_s: float) -> np.ndarray:
    """Read a segment of 16kHz mono WAV as float32."""
    with wave.open(str(wav_path), "rb") as w:
        sr = w.getframerate()
        total_frames = w.getnframes()
        frame_start = max(0, int(start_s * sr))
        frame_end = min(total_frames, int(end_s * sr))
        n_frames = max(0, frame_end - frame_start)
        if n_frames == 0:
            return np.zeros(0, dtype=np.float32)
        w.setpos(frame_start)
        raw = w.readframes(n_frames)
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        return samples


def transcribe_window(
    wav_path: Path,
    start_s: float,
    end_s: float,
    language: str | None = None,
    model_size: str = "tiny"
) -> list[SubtitleSegment]:
    """Transcribe a specific time window with word-level timestamps.
    
    Timestamps in returned segments are RELATIVE TO start_s (0.0 = start of clip).
    """
    audio_slice = read_audio_window(wav_path, start_s, end_s)
    if len(audio_slice) < 16000 * 0.5:  # Less than 0.5s audio
        return []

    model = get_whisper_model(model_size)
    segments, info = model.transcribe(
        audio_slice,
        language=language,
        word_timestamps=True,
        beam_size=1,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=400)
    )

    results: list[SubtitleSegment] = []
    for seg in segments:
        words: list[WordTiming] = []
        if seg.words:
            for w in seg.words:
                words.append(WordTiming(
                    start=round(float(w.start), 3),
                    end=round(float(w.end), 3),
                    word=w.word.strip()
                ))
        results.append(SubtitleSegment(
            start=round(float(seg.start), 3),
            end=round(float(seg.end), 3),
            text=seg.text.strip(),
            words=words
        ))
    return results


def format_ass_timestamp(seconds: float) -> str:
    """Format seconds into ASS timestamp string: H:MM:SS.cs"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - math.floor(seconds)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def generate_ass_subtitles(
    segments: list[SubtitleSegment],
    output_path: Path,
    style: Literal["bold", "karaoke", "clean", "minimal"] = "bold",
    font_size: int = 68,
    highlight_color: str = "&H006AB5D9",  # Gold (#D9B56A in BGR hex)
    primary_color: str = "&H00FFFFFF",    # White
    outline_color: str = "&H00000000"     # Black
) -> Path:
    """Generate professional 1080x1920 ASS subtitle file with word highlight animations."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: BoldCaption,Impact,{font_size},{primary_color},&H000000FF,{outline_color},&H80000000,-1,0,0,0,100,100,1,0,1,6,3,2,60,60,320,1
Style: CleanCaption,Arial,{int(font_size * 0.85)},{primary_color},&H000000FF,{outline_color},&H99000000,0,0,0,0,100,100,0,0,1,4,1,2,60,60,280,1
Style: MinimalCaption,Arial,{int(font_size * 0.7)},{primary_color},&H000000FF,{outline_color},&H66000000,0,0,0,0,100,100,0,0,1,3,0,2,60,60,240,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    dialogue_lines = []

    for seg in segments:
        if not seg.words:
            # Fallback to segment whole text
            t_start = format_ass_timestamp(seg.start)
            t_end = format_ass_timestamp(seg.end)
            dialogue_lines.append(
                f"Dialogue: 0,{t_start},{t_end},BoldCaption,,0,0,0,,{seg.text.upper()}"
            )
            continue

        # Group words into short punchy lines (3-5 words per card)
        words = seg.words
        chunk_size = 4
        for i in range(0, len(words), chunk_size):
            chunk = words[i : i + chunk_size]
            chunk_start = chunk[0].start
            chunk_end = chunk[-1].end

            if style == "bold":
                # For each word in the chunk, create a frame where that word is highlighted
                for current_idx, current_w in enumerate(chunk):
                    w_start = format_ass_timestamp(current_w.start)
                    w_end = format_ass_timestamp(current_w.end)
                    formatted_words = []
                    for idx, w in enumerate(chunk):
                        word_str = w.word.upper()
                        if idx == current_idx:
                            formatted_words.append(f"{{\\c{highlight_color}\\b1}}{word_str}{{\\c{primary_color}\\b0}}")
                        else:
                            formatted_words.append(word_str)
                    dialogue_lines.append(
                        f"Dialogue: 0,{w_start},{w_end},BoldCaption,,0,0,0,,{' '.join(formatted_words)}"
                    )
            elif style == "karaoke":
                t_start = format_ass_timestamp(chunk_start)
                t_end = format_ass_timestamp(chunk_end)
                karaoke_parts = []
                for w in chunk:
                    dur_cs = max(1, int(round((w.end - w.start) * 100)))
                    karaoke_parts.append(f"{{\\k{dur_cs}}}{w.word.upper()}")
                dialogue_lines.append(
                    f"Dialogue: 0,{t_start},{t_end},BoldCaption,,0,0,0,,{' '.join(karaoke_parts)}"
                )
            else:
                t_start = format_ass_timestamp(chunk_start)
                t_end = format_ass_timestamp(chunk_end)
                full_text = " ".join(w.word for w in chunk)
                chosen_style = "CleanCaption" if style == "clean" else "MinimalCaption"
                dialogue_lines.append(
                    f"Dialogue: 0,{t_start},{t_end},{chosen_style},,0,0,0,,{full_text}"
                )

    content = header + "\n".join(dialogue_lines) + "\n"
    output_path.write_text(content, encoding="utf-8")
    return output_path
