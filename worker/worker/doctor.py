"""Check the worker can reach Ollama and has every model it is configured to use.

    python -m worker.doctor

A missing model makes classification come back "unknown" and extraction fail,
so run this first whenever uploads stop being recognised.
"""
from __future__ import annotations

import sys
import time

import httpx
import ollama

from worker.config import config

CHAT_MODELS = ("llama3.1:8b",)       # backend/app/api/v1/chat.py uses this for answers


def wanted_models() -> dict[str, str]:
    """Model name -> what uses it."""
    wanted: dict[str, str] = {}
    for role, name in (("classifier", config.classifier_model), ("vision", config.vision_model),
                       ("extractor", config.extractor_model), ("embeddings", config.embed_model)):
        wanted.setdefault(name, role)
        if role not in wanted[name]:
            wanted[name] += f", {role}"
    for name in CHAT_MODELS:
        wanted.setdefault(name, "chat (backend)")
    return wanted


def installed_models() -> set[str]:
    response = httpx.get(f"{ollama.BASE_URL}/api/tags", timeout=5.0)
    response.raise_for_status()
    names = {m["name"] for m in response.json().get("models", [])}
    return names | {n.removesuffix(":latest") for n in names}


def timed_call(model: str) -> str:
    started = time.perf_counter()
    try:
        ollama.generate_json(model=model, prompt='Reply with {"ok": true}', timeout=180.0)
    except ollama.OllamaError as exc:
        return f"FAILED: {exc}"
    return f"ok in {time.perf_counter() - started:.1f} s"


def main() -> int:
    print(f"Ollama URL: {ollama.BASE_URL}")
    try:
        installed = installed_models()
    except httpx.HTTPError as exc:
        print(f"  NOT REACHABLE: {exc}\n  Is Ollama running? Does OLLAMA_BASE_URL in .env point at it?")
        return 1
    missing = [m for m in wanted_models() if m not in installed]
    for name, role in wanted_models().items():
        print(f"  {'ok     ' if name not in missing else 'MISSING'} {name:<22} ({role})")
    if missing:
        print(f"\nPull the missing models where Ollama runs:  ollama pull {' '.join(missing)}")
    if config.classifier_model not in missing:
        print(f"\nTest call to {config.classifier_model}: {timed_call(config.classifier_model)}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
