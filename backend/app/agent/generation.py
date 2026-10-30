"""Selectable chat generation; document extraction and embeddings remain local."""
import json
import os
import time
import httpx
import ollama

URL = "https://openrouter.ai/api/v1/chat/completions"


class GenerationError(ollama.OllamaError):
    def __init__(self, message):
        self.public_message = message
        super().__init__(message)


def model_name():
    return os.getenv("OPENROUTER_MODEL", "") if os.getenv("CHAT_PROVIDER", "ollama") == "openrouter" else os.getenv("CHAT_MODEL", "llama3.1:8b")


def token_limit():
    return 2048 if os.getenv("CHAT_PROVIDER", "ollama") == "openrouter" else 512


def generate_json(**kwargs):
    provider = os.getenv("CHAT_PROVIDER", "ollama")
    if provider == "ollama":
        return ollama.generate_json(**kwargs)
    if provider != "openrouter":
        raise GenerationError("The chat provider is not configured correctly.")
    return _remote(kwargs)


def _configuration(model):
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise GenerationError("OpenRouter is not configured. Ask the administrator to add its API key.")
    if not model or not model.endswith(":free"):
        raise GenerationError("Select a named OpenRouter :free model for this trial.")
    return {"Authorization": "Bearer " + key, "Content-Type": "application/json"}


def _payload(args):
    return {"model": args["model"], "messages": [{"role": "user", "content": args["prompt"]}],
            "temperature": 0, "max_tokens": args.get("options", {}).get("num_predict", 512), "stream": True,
            "provider": {"require_parameters": True, "allow_fallbacks": False, "data_collection": "deny"},
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "document_answer", "strict": True, "schema": args["response_schema"]}}}


def _status(response):
    messages = {401: "OpenRouter rejected the API key. Check the server configuration.",
                402: "OpenRouter cannot serve this request with the current account limits.",
                404: "OpenRouter has no compatible endpoint for this model and data policy. Check model availability and privacy settings.",
                429: "OpenRouter or the selected model is rate-limited. Please try again later."}
    if response.status_code >= 400:
        raise GenerationError(messages.get(response.status_code, "OpenRouter is unavailable or this model does not support the required output format."))


def _delta(line):
    if not line.startswith("data:"):
        return "", False
    data = line[5:].strip()
    if data == "[DONE]":
        return "", True
    item = json.loads(data)
    if item.get("error"):
        raise GenerationError("OpenRouter could not complete the answer. Please try again.")
    choices = item.get("choices", [])
    if not choices:
        return "", False
    if choices[0].get("finish_reason") in ("length", "content_filter", "error"):
        raise GenerationError("OpenRouter returned an incomplete answer. Please try a more specific question.")
    return choices[0].get("delta", {}).get("content") or "", False


def _read(response, args, clock):
    chunks, size, done = [], 0, False
    for line in response.iter_lines():
        if time.monotonic() - clock[0] > args.get("timeout", 120):
            raise GenerationError("OpenRouter took too long. Please try again.")
        content, done = _delta(line)
        if done:
            break
        if content:
            clock[1] = clock[1] if clock[1] is not None else time.monotonic() - clock[0]
            chunks.append(content); size += len(content)
            if size > 128000:
                raise GenerationError("OpenRouter returned an oversized answer.")
            if args.get("on_text"):
                args["on_text"]("".join(chunks))
    if not done:
        raise GenerationError("OpenRouter disconnected before completing the answer. Please try again.")
    result = json.loads("".join(chunks))
    if not isinstance(result, dict):
        raise GenerationError("OpenRouter returned an invalid answer.")
    return result


def _remote(args):
    headers, clock = _configuration(args["model"]), [time.monotonic(), None]
    try:
        with httpx.stream("POST", URL, headers=headers, json=_payload(args), timeout=args.get("timeout", 120)) as response:
            _status(response)
            return _read(response, args, clock)
    except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise GenerationError("OpenRouter could not return a valid answer. Please try again.") from exc
    finally:
        callback = args.get("metrics_callback")
        if callback:
            callback(clock[1], time.monotonic() - clock[0])
