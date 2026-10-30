# Chat evaluation lake — metadata-first foundation

## Purpose and boundaries
PostgreSQL remains the operational conversation store. A separate private MinIO/S3 bucket stores metadata-only evaluation objects under `chat/date=YYYY-MM-DD/request-id.json`. No question, answer, prompt, filename, readable document text, raw file/customer/application/conversation ID, email, or extracted financial amount is included. Pydantic allowlists drop unexpected fields before storage. This deliberate restriction avoids relying on incomplete PII detection. Conversation storage remains a separate privacy/retention concern.

Records include schema version, random request ID, timestamp, route/outcome, HMAC-pseudonymous session/source references, document page numbers, available lexical/semantic scores, model settings and timings. HMAC identifiers are linkable pseudonyms, not anonymized data. Protect the dedicated key and restrict bucket access; the writer refuses detectable anonymous Allow policies. Deployment credentials currently reuse the configured storage client; production should use a dedicated least-privilege identity.

## Enable
Logging is opt-in (`CHAT_EVALUATION_ENABLED=false` by default in source). Set these in the untracked local environment:

```
CHAT_EVALUATION_ENABLED=true
CHAT_EVALUATION_BUCKET=chat-evaluations
CHAT_EVALUATION_RETENTION_DAYS=30
CHAT_EVALUATION_HMAC_KEY=<dedicated random secret>
```

The evaluation bucket must differ from the document bucket. Never commit the key. Without a configured key, pseudonyms are process-local and change on restart. Local deployment has been enabled with a generated untracked key.

Recreate the backend to load changed environment settings: `docker compose up -d --no-deps backend`.

New buckets receive a prefix-scoped expiry rule (30 days by default). Existing buckets are not given or overwritten with a lifecycle policy automatically; administrators must verify expiry separately. Changing retention settings does not alter an existing bucket's policy. Expiry is asynchronous object-store lifecycle processing, not a precise scheduled deletion guarantee. Rotation/deletion and legal retention requirements need an agreed policy before production.

## Daily report

```
docker compose exec backend python -m scripts.summarize_chat_evaluations --date 2026-10-17
```

The report returns route/outcome counts and p50/p95 latency by stage. Missing first-token timings are excluded, not interpreted as zero. Fast field routes have no LLM first token. First token measures the first model output fragment, potentially JSON syntax, not the first answer visible to the user. The UI still receives completed validated answers.

Outcome answered means a response with citations or inventory was produced, NOT correctness. Semantic quality requires expected answers/source checks against safe synthetic or explicitly approved evaluation datasets. Existing tests cover exact facts, paraphrases, source ownership, corrections, follow-ups, uncertainty, scope and privacy; broad live LLM accuracy remains unresolved.

## Delivery guarantees
A 256-entry in-process background queue keeps S3 calls off the answer path. Writes use short network timeouts. Full queues and failed writes emit content-free warnings. This is best-effort telemetry: process crashes/reloads can lose queued events; there is no durable spool or retry/dead-letter queue. A durable queue is future work if audit-grade completeness is required. Requests rejected before entering chat generation (for example pending-conversation conflicts) are not all recorded.

## Verification on October 17
Three real existing-document requests stored three schema-compliant records: inventory, field lookup and scope refusal. The generated report counted two answered responses and one out-of-scope response, with total latency p50 0.0066s/p95 0.0342s. This small fast-path check is not an LLM performance or accuracy benchmark. Verified the newly created bucket's 30-day lifecycle rule. Unit tests cover content exclusion, context isolation, queue/storage failure behavior, anonymous policy rejection, partial generation timing and missing-timing report samples.

No source documents or customer extraction records were modified by this logging work. No Git push was performed.
