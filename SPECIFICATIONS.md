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

| Role | Model | Size | Where it runs | Budget |
| --- | --- | --- | --- | --- |
| Stage 1 classification | `llama3.2-vision:11b` | 11B | API request path | target under 2 seconds (not verified) |
| Stage 2 classification | `llama3.2-vision:11b` | 11B | Worker | seconds |
| Extraction | `llama3.1:8b` | 8B | Worker | target up to a minute (not verified) |
| Embeddings | `nomic-embed-text` | 137M | Worker | milliseconds, 768 dimensions |

Pull them once:

```
docker compose --profile models exec ollama ollama pull llama3.2-vision:11b
docker compose --profile models exec ollama ollama pull llama3.1:8b
docker compose --profile models exec ollama ollama pull nomic-embed-text
```

A smaller stage 1 model is worth testing (`moondream`, `qwen2.5vl:3b`) if 11B is
too slow on a laptop. The budget matters more than the size: the customer is
watching that spinner.

## Python packages

Backend: fastapi, uvicorn, sqlalchemy 2, psycopg 3, pydantic 2, pydantic-settings,
python-multipart, pika, boto3, httpx, pillow, pymupdf.

Worker: sqlalchemy 2, psycopg 3, pika, boto3, httpx, pillow, pymupdf, pytesseract
(with the `tesseract-ocr` system package).

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


