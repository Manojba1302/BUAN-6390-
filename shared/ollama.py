"""Thin Ollama client shared by the API and the worker.

Only two calls are needed in phase 1: a JSON-mode generate (with or without an
image) and an embedding. Keeping this small means one place to change when we
swap models.
"""
from __future__ import annotations

import base64
import json
import logging
import os

import httpx

log = logging.getLogger(__name__)

BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")


class OllamaError(RuntimeError):
    pass


def generate_json(
    *, model: str, prompt: str, images: list[bytes] | None = None,
    timeout: float = 60.0, temperature: float = 0.0,
) -> dict:
    """Ask the model for one JSON object and parse it.

    format=json makes Ollama constrain the output, temperature 0 makes the
    answer repeatable, which matters when we measure accuracy.
    """
    payload: dict = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": temperature},
    }
    if images:
        payload["images"] = [base64.b64encode(i).decode() for i in images]

    try:
        r = httpx.post(f"{BASE_URL}/api/generate", json=payload, timeout=timeout)
        r.raise_for_status()
        raw = r.json().get("response", "")
    except httpx.HTTPError as exc:
        raise OllamaError(f"ollama request failed: {exc}") from exc

    return _parse(raw)


def _parse(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(raw[start:end + 1])
            except json.JSONDecodeError:
                pass
    raise OllamaError(f"model did not return JSON: {raw[:200]}")


def embed(*, model: str, text: str, timeout: float = 60.0) -> list[float]:
    try:
        r = httpx.post(f"{BASE_URL}/api/embeddings",
                       json={"model": model, "prompt": text}, timeout=timeout)
        r.raise_for_status()
        return r.json()["embedding"]
    except (httpx.HTTPError, KeyError) as exc:
        raise OllamaError(f"embedding failed: {exc}") from exc


def health() -> bool:
    try:
        return httpx.get(f"{BASE_URL}/api/tags", timeout=5.0).status_code == 200
    except httpx.HTTPError:
        return False
