# OpenRouter chat trial

Chat answer generation can use OpenRouter; extraction, OCR, embeddings, PostgreSQL retrieval and citation verification stay local. Default CHAT_PROVIDER=ollama preserves the existing behavior. The adapter permits only named :free models, requires structured-output support, denies data-collection endpoints, and does not silently fall back to another model/provider or paid requests.

## Credentials
Create a key at https://openrouter.ai/settings/keys and put it in the ignored root .env file. Never put it in frontend variables, source code, screenshots, logs or Git.

```dotenv
CHAT_PROVIDER=openrouter
OPENROUTER_API_KEY=your_key_here
OPENROUTER_MODEL=dots-studio/dots-3-note-preview:free
EMBED_MODEL=nomic-embed-text
```

The example model was listed with structured-output support on October 25, 2026. Listing does not guarantee availability, quality, or eligibility with data-collection denied. Verify against the actual account before the demo. Do not use openrouter/free for reproducible comparisons; select a named free model.

Apply changed environment values with `docker compose up -d --force-recreate backend`. A restart alone does not reload .env values into an existing container. To return to local generation, set CHAT_PROVIDER=ollama and recreate only backend.

## Embeddings
Both query and ingestion import shared/embedding_config.py. The existing index requires nomic-embed-text and 768 dimensions; alternative EMBED_MODEL values are rejected. Document/query task prefixes stay unchanged. Keep the installed encoder artifact consistent across hosts; changing encoder weights needs a deliberate re-index, even if dimensions match. This change does not migrate existing vectors or store encoder digests per row.

## Behavior and tests
The adapter streams the JSON answer through the existing UI callback. Existing support-quote and citation checks still run on the final answer. Invalid/truncated output and upstream errors fail explicitly; 429 gets a free-model quota message. No automatic retries consume additional free calls.

Run `docker exec homeflow-backend-1 python -m unittest tests.generation_test tests.code_standards_test` for isolated adapter tests. Run the existing synthetic quality harness against a disposable database named review with CHAT_PROVIDER, OPENROUTER_MODEL and a server-side key supplied. Do not use real customer records in the initial remote trial. Calls send the question and retrieved evidence to OpenRouter and its selected inference provider, even though retrieval/embeddings are local.

Adapter mocks verify request/stream/error behavior, not model accuracy. See the live verification notes below for the separate synthetic model checks.

Official references:
- https://openrouter.ai/docs/quickstart
- https://openrouter.ai/docs/guides/features/structured-outputs
- https://openrouter.ai/docs/api_reference/limits
- https://openrouter.ai/docs/guides/privacy/provider-logging

## Live synthetic verification — October 27, 2026

The saved key was accepted. Four synthetic cases passed the actual answer/citation verifier with dots-studio/dots-3-note-preview:free: lease expiry (10.17s), deposit (9.61s), missing fee (10.50s), and cross-document names (15.14s). Remote output allowance is 2048 tokens; local remains 512. All 65 related regression tests passed. These direct-evidence checks do not cover retrieval, database persistence or the UI. No real customer evidence was transmitted.

The developer subsequently authorized live-app activation: the local deployment uses CHAT_PROVIDER=openrouter with a named free model. Each deployment must supply its own ignored environment settings and API key. Other tested free models were rate-limited or incompatible with current data-policy restrictions; restrictions were not relaxed.
