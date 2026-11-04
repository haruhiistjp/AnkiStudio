"""Minimal OpenAI-compatible chat client for the deck redactor.

The user configures base URL, model and API key in Settings (stored in
the project's settings table) — any /chat/completions endpoint works:
OpenAI, Groq, OpenRouter, a local llama.cpp/ollama server, etc. No SDK
dependency: one urllib POST.
"""
from __future__ import annotations

import json
import urllib.request

DEFAULTS = {
    "ai_base": "",          # e.g. https://api.openai.com/v1
    "ai_key": "",
    "ai_model": "",         # e.g. gpt-4o-mini
    "ai_prompt_card": (
        "You write concise English explanations for Japanese sentence "
        "cards in an Anki deck. Given a grammar point and one example "
        "sentence, explain how the point is used in THAT sentence in 1-3 "
        "sentences. Output only the explanation text."),
    "ai_prompt_block": (
        "You write concise English explanations for Japanese sentence "
        "cards in an Anki deck. You will receive a grammar point and a "
        "numbered list of example sentences. For each, explain how the "
        "point is used in that sentence in 1-3 sentences. Respond with "
        "ONLY a JSON array: [{\"n\": <number>, \"note\": \"<explanation>\"}, …] "
        "with exactly one object per input sentence, same order, no "
        "commentary."),
}


def configured(store) -> bool:
    return bool(store.get_setting("ai_base") and store.get_setting("ai_model"))


def chat(store, messages: list[dict], max_tokens: int = 800,
         temperature: float = 0.3) -> str:
    base = store.get_setting("ai_base").rstrip("/")
    key = store.get_setting("ai_key")
    model = store.get_setting("ai_model")
    if not (base and model):
        raise ValueError("AI API is not configured — set base URL, model "
                         "and key in Settings")
    body = json.dumps({"model": model, "messages": messages,
                       "max_tokens": max_tokens,
                       "temperature": temperature}).encode()
    req = urllib.request.Request(
        base + "/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise ValueError(f"AI API error {e.code}: {detail}")
    except urllib.error.URLError as e:
        raise ValueError(f"cannot reach the AI API: {e.reason}")
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, AttributeError):
        raise ValueError(f"unexpected AI API response: {str(data)[:200]}")


def extract_json_array(text: str) -> list:
    """Pull the JSON array out of a model reply that may wrap it in
    prose or code fences."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        raise ValueError("the model did not return a JSON array")
    try:
        out = json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise ValueError(f"unparseable JSON from the model: {e}")
    if not isinstance(out, list):
        raise ValueError("the model did not return a JSON array")
    return out
