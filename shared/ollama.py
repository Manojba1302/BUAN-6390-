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
import time

import httpx

log = logging.getLogger(__name__)

BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")


class OllamaError(RuntimeError):
    pass


def generate_json(
    *, model: str, prompt: str, images: list[bytes] | None = None,
    timeout: float = 60.0, temperature: float = 0.0, options: dict | None = None, response_schema: dict | None = None, measure_first_token: bool = False, metrics_callback=None, keep_alive=None, on_text=None,
) -> dict:
    """Ask the model for one JSON object and parse it.

    format=json makes Ollama constrain the output, temperature 0 makes the
    answer repeatable, which matters when we measure accuracy.
    """
    payload = _generation_payload(model, prompt, images, temperature, options, response_schema, keep_alive)

    if measure_first_token or on_text is not None:
        return _stream_json(payload, timeout, metrics_callback, on_text)
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
    raise OllamaError("model did not return JSON")


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


def _stream_json(payload, timeout, metrics_callback=None, on_text=None):
    start, first, chunks = time.monotonic(), None, []
    try:
        with httpx.stream("POST", f"{BASE_URL}/api/generate", json={**payload,"stream":True}, timeout=timeout) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if time.monotonic()-start > timeout:
                    raise OllamaError("generation exceeded total timeout")
                item = json.loads(line) if line else {}
                if item.get("error"):
                    raise OllamaError("model generation failed")
                if item.get("response"):
                    first = first if first is not None else time.monotonic()-start
                    chunks.append(item["response"])
                    if on_text is not None:
                        on_text("".join(chunks))   # raw text so far; callers decide what to show
        return _parse("".join(chunks))
    except (httpx.HTTPError, ValueError) as exc:
        raise OllamaError("stream request failed") from exc
    finally:
        _record_stream_timing(first, start, metrics_callback)


def _record_stream_timing(first, start, callback):
    elapsed = time.monotonic()-start
    log.info("chat_generation first_token_seconds=%s total_seconds=%.3f",round(first,3) if first is not None else None,elapsed)
    if callback is not None:
        try:
            callback(first, elapsed)
        except Exception:
            log.warning("chat_generation_metrics_failed")


def _generation_payload(model, prompt, images, temperature, options, schema, keep_alive):
    payload = {"model": model, "prompt": prompt, "stream": False, "format": schema or "json",
               "options": {"temperature": temperature, **(options or {})}}
    if keep_alive is not None:
        payload["keep_alive"] = keep_alive
    if images:
        payload["images"] = [base64.b64encode(image).decode() for image in images]
    return payload
