"""Unified AI Candidate Evaluator & Provider Manager.

Supports:
1. Local AI:
   - Ollama (http://localhost:11434) with model discovery & selection
   - Built-in CPU-first ML components: faster-whisper INT8 & sherpa-onnx (CED-mini)
   - Intelligent gaming heuristic fallback (100% free, runs offline on CPU)
2. API AI:
   - DeepSeek API (https://api.deepseek.com/v1)
   - OpenRouter API (https://openrouter.ai/api/v1)
   - Secure local-only key storage, masked UI representation, zero credential leakage
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import requests

from .config import BASE_DIR

CONFIG_FILE = BASE_DIR / ".ai_config.json"
OLLAMA_DEFAULT_URL = "http://localhost:11434"
DEEPSEEK_DEFAULT_URL = "https://api.deepseek.com/v1"
OPENROUTER_DEFAULT_URL = "https://openrouter.ai/api/v1"

RECOMMENDED_OLLAMA_MODELS = ["llama3.2:3b", "llama3.2", "qwen2.5:3b", "phi3.5", "gemma2:2b", "mistral"]


@dataclass
class CandidateEvaluation:
    rank_score: int
    category: str
    explanation: str
    suggested_title: str
    ai_powered: bool
    provider: str = "heuristics"


def _mask_key(key: str | None) -> str:
    """Mask API key for secure frontend display (e.g. sk-****...abcd)."""
    if not key:
        return ""
    clean = key.strip()
    if len(clean) <= 8:
        return "sk-****"
    return f"{clean[:4]}****...{clean[-4:]}"


def load_ai_config() -> dict[str, Any]:
    """Load AI configuration, returning masked API keys for public/frontend consumption."""
    default_config: dict[str, Any] = {
        "mode": "local",  # "local" or "api"
        "provider": "ollama",  # "ollama", "deepseek", "openrouter", "heuristics"
        "ollama_url": OLLAMA_DEFAULT_URL,
        "ollama_model": "",
        "deepseek_url": DEEPSEEK_DEFAULT_URL,
        "deepseek_model": "deepseek-chat",
        "has_deepseek_key": False,
        "deepseek_key_masked": "",
        "openrouter_url": OPENROUTER_DEFAULT_URL,
        "openrouter_model": "deepseek/deepseek-chat",
        "has_openrouter_key": False,
        "openrouter_key_masked": "",
    }

    if not CONFIG_FILE.is_file():
        return default_config

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        cfg = default_config.copy()
        cfg.update({k: v for k, v in data.items() if k not in ["deepseek_key", "openrouter_key"]})
        
        # Check keys securely
        ds_key = data.get("deepseek_key", "")
        cfg["has_deepseek_key"] = bool(ds_key)
        cfg["deepseek_key_masked"] = _mask_key(ds_key)

        or_key = data.get("openrouter_key", "")
        cfg["has_openrouter_key"] = bool(or_key)
        cfg["openrouter_key_masked"] = _mask_key(or_key)

        return cfg
    except Exception:
        return default_config


def _load_raw_keys() -> tuple[str, str]:
    """Retrieve raw unmasked keys internally on backend only."""
    if not CONFIG_FILE.is_file():
        return "", ""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("deepseek_key", ""), data.get("openrouter_key", "")
    except Exception:
        return "", ""


def save_ai_config(updates: dict[str, Any]) -> dict[str, Any]:
    """Save AI configuration securely to local .ai_config.json."""
    current_data = {}
    if CONFIG_FILE.is_file():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                current_data = json.load(f)
        except Exception:
            current_data = {}

    # Handle DeepSeek key
    new_ds_key = updates.get("deepseek_key")
    if new_ds_key is not None:
        if new_ds_key.strip() == "":
            current_data.pop("deepseek_key", None)
        elif not ("****" in new_ds_key):  # Not placeholder
            current_data["deepseek_key"] = new_ds_key.strip()

    # Handle OpenRouter key
    new_or_key = updates.get("openrouter_key")
    if new_or_key is not None:
        if new_or_key.strip() == "":
            current_data.pop("openrouter_key", None)
        elif not ("****" in new_or_key):  # Not placeholder
            current_data["openrouter_key"] = new_or_key.strip()

    # Update other fields
    for k in [
        "mode", "provider", "ollama_url", "ollama_model",
        "deepseek_url", "deepseek_model", "openrouter_url", "openrouter_model"
    ]:
        if k in updates and updates[k] is not None:
            current_data[k] = updates[k]

    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(current_data, f, indent=2)

    return load_ai_config()


def get_ollama_status(url: str | None = None) -> tuple[bool, list[str], str | None]:
    """Check if local Ollama daemon is running, returning list of models and recommended model."""
    endpoint = (url or OLLAMA_DEFAULT_URL).rstrip("/")
    try:
        r = requests.get(f"{endpoint}/api/tags", timeout=1.5)
        if r.status_code == 200:
            models_info = r.json().get("models", [])
            installed_names = [m.get("name", "") for m in models_info if m.get("name")]
            recommended = None
            for target in RECOMMENDED_OLLAMA_MODELS:
                for inst in installed_names:
                    if inst.startswith(target):
                        recommended = inst
                        break
                if recommended:
                    break
            if not recommended and installed_names:
                recommended = installed_names[0]
            return True, installed_names, recommended
    except Exception:
        pass
    return False, [], None


def is_ollama_available() -> tuple[bool, str | None]:
    """Check Ollama availability for system status."""
    cfg = load_ai_config()
    url = cfg.get("ollama_url") or OLLAMA_DEFAULT_URL
    ok, models, rec = get_ollama_status(url)
    model = cfg.get("ollama_model") or rec
    return ok, model


def test_ai_connection(
    provider: str,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Verify connectivity with chosen AI provider."""
    provider = provider.lower()
    raw_ds_key, raw_or_key = _load_raw_keys()

    if provider == "ollama":
        url = (base_url or OLLAMA_DEFAULT_URL).rstrip("/")
        ok, models, rec = get_ollama_status(url)
        if not ok:
            return {
                "success": False,
                "message": f"Could not connect to Ollama at {url}. Make sure Ollama is installed and running.",
                "models": [],
            }
        return {
            "success": True,
            "message": f"Connected to Ollama! Found {len(models)} installed model(s).",
            "models": models,
            "recommended": rec,
        }

    elif provider == "deepseek":
        url = (base_url or DEEPSEEK_DEFAULT_URL).rstrip("/")
        key = api_key if (api_key and "****" not in api_key) else raw_ds_key
        if not key:
            return {"success": False, "message": "DeepSeek API key is required."}

        target_model = model or "deepseek-chat"
        endpoint = f"{url}/chat/completions" if not url.endswith("/chat/completions") else url

        try:
            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            }
            body = {
                "model": target_model,
                "messages": [{"role": "user", "content": "Respond with 'OK'"}],
                "max_tokens": 5,
            }
            res = requests.post(endpoint, headers=headers, json=body, timeout=8.0)
            if res.status_code == 200:
                return {
                    "success": True,
                    "message": f"DeepSeek API connected successfully! (model: {target_model})",
                }
            else:
                err_text = res.text[:200]
                return {
                    "success": False,
                    "message": f"DeepSeek returned HTTP {res.status_code}: {err_text}",
                }
        except Exception as e:
            return {"success": False, "message": f"Connection error: {e}"}

    elif provider == "openrouter":
        url = (base_url or OPENROUTER_DEFAULT_URL).rstrip("/")
        key = api_key if (api_key and "****" not in api_key) else raw_or_key
        if not key:
            return {"success": False, "message": "OpenRouter API key is required."}

        target_model = model or "deepseek/deepseek-chat"
        endpoint = f"{url}/chat/completions" if not url.endswith("/chat/completions") else url

        try:
            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:8000",
                "X-Title": "GTA Clipper",
            }
            body = {
                "model": target_model,
                "messages": [{"role": "user", "content": "Respond with 'OK'"}],
                "max_tokens": 5,
            }
            res = requests.post(endpoint, headers=headers, json=body, timeout=8.0)
            if res.status_code == 200:
                return {
                    "success": True,
                    "message": f"OpenRouter connected successfully! (model: {target_model})",
                }
            else:
                err_text = res.text[:200]
                return {
                    "success": False,
                    "message": f"OpenRouter returned HTTP {res.status_code}: {err_text}",
                }
        except Exception as e:
            return {"success": False, "message": f"Connection error: {e}"}

    elif provider == "heuristics":
        return {
            "success": True,
            "message": "Local signal heuristics active. Zero cost, no external setup required.",
        }

    return {"success": False, "message": f"Unknown provider: {provider}"}


def rule_based_evaluate(
    start: float,
    end: float,
    hype_score: int,
    reasons: list[dict],
    transcript_text: str = "",
) -> CandidateEvaluation:
    """Smart heuristic gaming evaluator running CPU-only without external APIs."""
    reason_codes = {r.get("code") for r in reasons}

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
            explanation_parts.append(f"Viewer reaction burst ({rx})")

    if "laughter" in reason_codes:
        category = "Hilarious Reaction"
        title = "Uncontrollable Laughter!"
        explanation_parts.append("Player laughter detected")

    if "shouting" in reason_codes or "loudness_spike" in reason_codes:
        if category == "Gaming Highlight":
            category = "Hyped Action"
            title = "Intense Play!"
        explanation_parts.append("Audio loudness burst")

    if transcript_text:
        words = transcript_text.strip().split()
        if len(words) >= 3:
            first_words = " ".join(words[:5]).capitalize()
            title = f"{first_words}..."

    if not explanation_parts:
        explanation_parts.append("High overall viewer engagement and audio energy")

    return CandidateEvaluation(
        rank_score=hype_score,
        category=category,
        explanation=" & ".join(explanation_parts) + ".",
        suggested_title=title,
        ai_powered=False,
        provider="heuristics",
    )


def evaluate_candidate(
    start: float,
    end: float,
    hype_score: int,
    reasons: list[dict],
    transcript_text: str = "",
) -> CandidateEvaluation:
    """Unified candidate evaluation function routing to active AI provider (Ollama, DeepSeek, OpenRouter, or Heuristics)."""
    cfg = load_ai_config()
    mode = cfg.get("mode", "local")
    provider = cfg.get("provider", "ollama")

    prompt = f"""You are an expert gaming highlight editor clipping GTA 6 gameplay for YouTube Shorts, TikTok, and Instagram Reels.
Evaluate this candidate highlight moment:
- Duration: {end - start:.1f} seconds (from {start:.1f}s to {end:.1f}s)
- Audio & Chat Signals: {json.dumps(reasons)}
- Spoken Words Transcript: "{transcript_text}"

Respond with ONLY valid JSON with keys:
"category": one of ["Clutch Play", "Funny Reaction", "Epic Fail", "Insane Action", "Story Moment"]
"explanation": a punchy 1-sentence explanation of why this moment is engaging
"suggested_title": a click-worthy 4-8 word title
"rank_score": an integer from 1 to 100
"""

    raw_ds_key, raw_or_key = _load_raw_keys()

    # 1. API AI Mode (DeepSeek or OpenRouter)
    if mode == "api":
        if provider == "deepseek" and raw_ds_key:
            url = cfg.get("deepseek_url") or DEEPSEEK_DEFAULT_URL
            endpoint = f"{url.rstrip('/')}/chat/completions"
            model = cfg.get("deepseek_model") or "deepseek-chat"
            try:
                headers = {"Authorization": f"Bearer {raw_ds_key}", "Content-Type": "application/json"}
                body = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 150,
                    "response_format": {"type": "json_object"},
                }
                res = requests.post(endpoint, headers=headers, json=body, timeout=10.0)
                if res.status_code == 200:
                    content = res.json()["choices"][0]["message"]["content"]
                    parsed = json.loads(content)
                    return CandidateEvaluation(
                        rank_score=int(parsed.get("rank_score", hype_score)),
                        category=str(parsed.get("category", "Gaming Highlight")),
                        explanation=str(parsed.get("explanation", "High excitement detected.")),
                        suggested_title=str(parsed.get("suggested_title", "Highlight")),
                        ai_powered=True,
                        provider="deepseek",
                    )
            except Exception:
                pass  # Fallback to heuristics

        elif provider == "openrouter" and raw_or_key:
            url = cfg.get("openrouter_url") or OPENROUTER_DEFAULT_URL
            endpoint = f"{url.rstrip('/')}/chat/completions"
            model = cfg.get("openrouter_model") or "deepseek/deepseek-chat"
            try:
                headers = {
                    "Authorization": f"Bearer {raw_or_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "http://localhost:8000",
                    "X-Title": "GTA Clipper",
                }
                body = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 150,
                }
                res = requests.post(endpoint, headers=headers, json=body, timeout=10.0)
                if res.status_code == 200:
                    content = res.json()["choices"][0]["message"]["content"]
                    match = re.search(r"\{.*\}", content, re.DOTALL)
                    json_str = match.group(0) if match else content
                    parsed = json.loads(json_str)
                    return CandidateEvaluation(
                        rank_score=int(parsed.get("rank_score", hype_score)),
                        category=str(parsed.get("category", "Gaming Highlight")),
                        explanation=str(parsed.get("explanation", "High excitement detected.")),
                        suggested_title=str(parsed.get("suggested_title", "Highlight")),
                        ai_powered=True,
                        provider="openrouter",
                    )
            except Exception:
                pass  # Fallback to heuristics

    # 2. Local AI Mode (Ollama)
    elif mode == "local" and provider == "ollama":
        url = (cfg.get("ollama_url") or OLLAMA_DEFAULT_URL).rstrip("/")
        ok, models, rec = get_ollama_status(url)
        model_name = cfg.get("ollama_model") or rec
        if ok and model_name:
            try:
                r = requests.post(
                    f"{url}/api/generate",
                    json={
                        "model": model_name,
                        "prompt": prompt,
                        "format": "json",
                        "stream": False,
                        "options": {"temperature": 0.3, "num_predict": 120},
                    },
                    timeout=8.0,
                )
                if r.status_code == 200:
                    parsed = json.loads(r.json().get("response", "{}"))
                    return CandidateEvaluation(
                        rank_score=int(parsed.get("rank_score", hype_score)),
                        category=str(parsed.get("category", "Gaming Highlight")),
                        explanation=str(parsed.get("explanation", "High excitement detected.")),
                        suggested_title=str(parsed.get("suggested_title", "Highlight")),
                        ai_powered=True,
                        provider="ollama",
                    )
            except Exception:
                pass  # Fallback to heuristics

    # 3. Seamless Rule-Based Fallback
    return rule_based_evaluate(start, end, hype_score, reasons, transcript_text)
