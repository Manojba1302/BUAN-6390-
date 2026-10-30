"""Shared encoder identity for the existing 768-dimensional document index."""
import os

MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
DIMENSIONS = 768
# Changing encoders requires a deliberate full-index migration, not a chat-model swap.
if MODEL != "nomic-embed-text":
    raise RuntimeError("This index requires EMBED_MODEL=nomic-embed-text; migrate and rebuild the index before changing encoders.")
