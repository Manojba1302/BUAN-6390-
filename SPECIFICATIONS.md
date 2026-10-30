# Specifications

Every technology and model this project uses. Keep this current: it is the file
Vijay asked for, and it is what we read from in the demo.

## Services

| Service | Image or framework | Version | Port | Why |
| --- | --- | --- | --- | --- |
| Database | pgvector/pgvector | pg16 | 5432 | Postgres with pgvector, as the sponsor specified. Not ChromaDB. |
| Queue | rabbitmq | 3.13-management | 5672, 15672 | Durable queue, and the management UI is useful on screen during a demo |
| Object storage | source-built MinIO | RELEASE.2025-10-15T17-29-55Z | 9000, 9001 | S3 API locally; swap the endpoint for real S3 at demo time |
| API | FastAPI | 0.115 | 8000 | Vijay named FastAPI with an organised folder structure |
| Worker | Python consumer | 3.12 | n/a | Extraction runs off the queue, never in the request |
| Front end | React + TypeScript + Vite | 18 / 5.7 / 6 | 5173 | Same stack as the lender portal we studied |
| Models | Ollama container | latest | 11435 (host) / 11434 (container) | Runs on our machines and on the sponsor's |

## Models

What `.env` runs today (all local through Ollama, on CPU):

| Role | Model | Size | Where it runs | Notes |
| --- | --- | --- | --- | --- |
| Stage 1 classification | `qwen2.5vl:3b` | 3B | API request path | Small vision model; checks the document type only, persists nothing |
| Stage 2 classification | `qwen2.5vl:3b` | 3B | Worker | Writes `file_classification`, the record of truth |
| Extraction | `qwen2.5vl:3b` | 3B | Worker | Same small model as classification to fit laptop CPUs; the meeting plan was a larger extraction model (`llama3.1:8b` is the fallback default) |
| OCR | Tesseract 5 | n/a | Worker | Reads photos and scans; values from the model are checked against this text |
| Embeddings | `nomic-embed-text` | 137M | Worker and API | 768 dimensions in pgvector; changing it needs a full re-index |
| Chat answers | `llama3.1:8b` (default `CHAT_MODEL`) | 8B | API | Optional: OpenRouter for chat generation only (`CHAT_PROVIDER=openrouter`); documents and embeddings stay local |

Pull them once:

```
ollama pull qwen2.5vl:3b
ollama pull llama3.1:8b
ollama pull nomic-embed-text
```

## Python packages

Backend: fastapi, uvicorn, sqlalchemy 2, psycopg 3, pydantic 2, pydantic-settings,
python-multipart, pika, boto3, httpx, pillow, pillow-heif, pymupdf, langgraph (chat
session memory), reportlab (PDF generation from Markdown templates), cryptography.

Worker: sqlalchemy 2, psycopg 3, pika, boto3, httpx, pillow, pillow-heif (iPhone HEIC
photos), pymupdf, pytesseract (with the `tesseract-ocr` system package), cryptography.

## Front-end packages

react, react-dom, vite, @vitejs/plugin-react, typescript. No UI framework and no
CSS framework: the design system is one stylesheet of tokens and components, so
nothing fights us on the look.

## Decisions worth remembering

- The form is data. `backend/app/data/field_dictionary.json` drives the screens;
  the front end renders it and never hard-codes a field.
- Document types are data too. `shared/document_types.json` holds the definition,
  the printed signals, the regex backup and the extraction schema for all five
  types, and both Python services read the same file.
- Classification happens twice. Stage 1 is advisory and persists nothing;
  stage 2, in the worker, writes `file_classification` and is the record of truth.
- The model never sees the filename or the category the customer picked.
- A mismatch warns and never blocks.
- Nothing reaches storage until the customer presses Upload.

## Authentication
Password accounts use salted scrypt hashes and opaque, revocable HttpOnly cookie sessions. Reset links are single-use and expire after 30 minutes. Mailpit v1.27 receives local reset emails; HTTPS and real SMTP are required for deployment. Email-only development authentication has been removed.

## Encryption at rest
`FIELD_ENCRYPTION_KEY` (a Fernet key) encrypts SSN, license and account numbers and dates of birth in
the extraction and application tables. Without it those values are stored in plain text. Document
text in `document_chunk` and the Markdown files is not encrypted.

## Re-reading a document
Uploading the same file again reuses the stored copy and does not read it again. A failed read, or a
completed read missing key fields (for example a license number), offers Retry reading in the review
panel, which queues the saved file again. Customer corrections are kept.
