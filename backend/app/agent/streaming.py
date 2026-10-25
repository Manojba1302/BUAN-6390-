"""Live answer text for the chat stream.

The model writes one JSON object; only the growing "answer" string is shown while it
types. Citations and quote checks still run on the complete reply, which replaces the
draft when it is ready, so an unverified draft is never kept.
"""
from contextvars import ContextVar
import json

SINK = ContextVar("chat_stream_sink", default=None)


def forwarder():
    """A callback for ollama.generate_json(on_text=...), or None when nobody is streaming."""
    sink = SINK.get()
    if sink is None:
        return None
    last = {"text": ""}

    def forward(raw):
        text = partial_answer(raw)
        if text and text != last["text"]:
            last["text"] = text
            sink(text)
    return forward


def partial_answer(raw):
    """The decoded value of "answer" so far, from incomplete JSON text."""
    start = raw.find('"answer"')
    if start < 0:
        return ""
    colon = raw.find(":", start + 8)
    quote = raw.find('"', colon + 1) if colon >= 0 else -1
    if quote < 0:
        return ""
    body, escaped = [], False
    for char in raw[quote + 1:]:
        if char == '"' and not escaped:
            break
        body.append(char)
        escaped = char == "\\" and not escaped
    text = "".join(body).rstrip("\\")
    try:
        return json.loads('"' + text + '"')
    except json.JSONDecodeError:
        return text.replace("\\n", "\n").replace('\\"', '"')
