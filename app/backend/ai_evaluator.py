"""Local AI Candidate Evaluator.

Connects to Ollama (http://localhost:11434) to evaluate candidate highlights using:
- Transcript text
- Chat reaction spikes
- Audio excitement levels
- Timing context

If Ollama is not installed or offline, seamlessly falls back to rule-based gaming heuristic analysis.
Zero-cost, zero external API keys.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import requests

OLLAMA_ENDPOINT = "http://localhost:11434"
DEFAULT_MODELS = ["llama3.2:3b", "llama3.2", "qwen2.5:3b", "phi3.5", "gemma2:2b", "mistral"]


@dataclass
class CandidateEvaluation:
    rank_score: int
    category: str
    explanation: str
    suggested_title: str
    ai_powered: bool


def is_ollama_available() -> tuple[bool, str | None]:
    """Check if local Ollama daemon is running and return best available model."""
    try:
        r = requests.get(f"{OLLAMA_ENDPOINT}/api/tags", timeout=1.5)
        if r.status_code == 200:
            models_info = r.json().get("models", [])
            installed_names = [m.get("name", "") for m in models_info]
            for target in DEFAULT_MODELS:
                for inst in installed_names:
                    if inst.startswith(target):
                        return True, inst
            if installed_names:
                return True, installed_names[0]
            return True, None
    except Exception:
        pass
    return False, None


def rule_based_evaluate(
    start: float,
    end: float,
    hype_score: int,
    reasons: list[dict],
    transcript_text: str = ""
) -> CandidateEvaluation:
    """Smart heuristic evaluator when Ollama is offline."""
    reason_codes = {r.get("code") for r in reasons}
    values = [r.get("value", "") for r in reasons]

    category = "Gaming Highlight"
    explanation_parts = []
    title = "Epic Gaming Moment"

    if "chat_spike" in reason_codes:
        spike_val = next((r.get("value") for r in reasons if r.get("code") == "chat_spike"), "")
        explanation_parts.append(f"Chat exploded with {spike_val} activity surge")

    if "chat_reactions" in reason_codes:
        rx = next((r.get("value") for r in reasons if r.get("code") == "chat_reactions"), "")
        if rx in ["KEKW", "LUL", "HAHA", "XD", "ROFL"]:
            category = "Funny Moment"
            title = f"Chat Lost It! {rx}"
            explanation_parts.append(f"Viewer reaction wave ({rx})")
        elif rx in ["WTF", "OMG", "NO WAY"]:
            category = "Insane Climax"
            title = f"No Way That Just Happened ({rx})"
            explanation_parts.append(f"Disbelief reaction ({rx})")
        else:
            explanation_parts.append(f"Viewer spam burst ({rx})")

    if "laughter" in reason_codes:
        category = "Hilarious Reaction"
        title = "Uncontrollable Laughter!"
        explanation_parts.append("Player laughter detected")

    if "shouting" in reason_codes or "loudness_spike" in reason_codes:
        if category == "Gaming Highlight":
            category = "Hyped Action"
            title = "Intense Play!"
        explanation_parts.append("Audio loudness spike")

    if transcript_text:
        words = transcript_text.strip().split()
        if len(words) >= 3:
            first_words = " ".join(words[:5]).capitalize()
            title = f"{first_words}..."

    if not explanation_parts:
        explanation_parts.append("High overall viewer and audio engagement")

    return CandidateEvaluation(
        rank_score=hype_score,
        category=category,
        explanation=" & ".join(explanation_parts) + ".",
        suggested_title=title,
        ai_powered=False
    )


def evaluate_candidate(
    start: float,
    end: float,
    hype_score: int,
    reasons: list[dict],
    transcript_text: str = ""
) -> CandidateEvaluation:
    """Evaluate candidate moment using local Ollama if available, otherwise heuristic fallback."""
    available, model_name = is_ollama_available()
    if not available or not model_name:
        return rule_based_evaluate(start, end, hype_score, reasons, transcript_text)

    prompt = f"""You are an expert gaming editor clipping GTA 6 and stream highlights for YouTube Shorts & TikTok.
Evaluate this candidate highlight moment:
- Duration: {end - start:.1f} seconds (from {start:.1f}s to {end:.1f}s)
- Audio & Chat Signals: {json.dumps(reasons)}
- Spoken Words: "{transcript_text}"

Respond with ONLY valid JSON with keys:
"category": one of ["Clutch Play", "Funny Reaction", "Epic Fail", "Insane Action", "Story Moment"]
"explanation": a punchy 1-sentence explanation of why this moment is engaging
"suggested_title": a click-worthy 4-8 word title
"rank_score": an integer from 1 to 100
"""

    try:
        r = requests.post(
            f"{OLLAMA_ENDPOINT}/api/generate",
            json={
                "model": model_name,
                "prompt": prompt,
                "format": "json",
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 120}
            },
            timeout=8.0
        )
        if r.status_code == 200:
            parsed = json.loads(r.json().get("response", "{}"))
            return CandidateEvaluation(
                rank_score=int(parsed.get("rank_score", hype_score)),
                category=str(parsed.get("category", "Gaming Highlight")),
                explanation=str(parsed.get("explanation", "High excitement detected.")),
                suggested_title=str(parsed.get("suggested_title", "GTA Highlight")),
                ai_powered=True
            )
    except Exception:
        pass

    return rule_based_evaluate(start, end, hype_score, reasons, transcript_text)
