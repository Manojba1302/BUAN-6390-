# Repeatable synthetic chat-quality evaluation

The dataset `backend/tests/fixtures/chat_quality_cases.json` contains 13 synthetic cases. Nine exercise deterministic paths: exact/reworded employer lookup, employer comparison, saved correction priority, identifier masking, missing overtime, unrelated scope unreadable documents and supported-field name comparison. Four exercise actual LLM/RAG: unfamiliar lease date, insurance exclusion, missing deposit and schema-free mixed-document names.

`backend/scripts/run_chat_quality.py` seeds synthetic customers/documents/chunks into a disposable PostgreSQL database named `review`, invokes the real chat router/service, grades expected facts/forbidden claims/exact file-page references, then removes each synthetic customer and cascading data. It refuses databases with another name. Never point it at a customer database. It does not modify MinIO documents or use customer records. Operational lake publication is intercepted, so benchmark events do not mix with customer telemetry.

Default mode prohibits model generation and runs nine deterministic cases. `--live-model` enables the four general-model cases as well; `--case CASE_ID` narrows the selection. General cases use real embedding/generation services. Text chunks have no precomputed vectors, so these cases primarily validate lexical/fallback retrieval plus model generation, not a full semantic-vector recall benchmark.

Run inside the backend image with the source checkout mounted read-only at `/review`, working directory `/review/backend`, PYTHONPATH `/review/backend:/review/shared`, SHARED_DIR `/review/shared`, CHAT_EVALUATION_ENABLED=false and DATABASE_URL pointing to the disposable initialized `review` database:

```
python -m scripts.run_chat_quality
python -m scripts.run_chat_quality --live-model --case lease_end
```

Use the isolated database container pattern already used by the test suite; apply `db/init` only to that fresh disposable volume. Never reset the application database to run evaluation.

Output is JSON Lines with case ID, pass/fail reasons, route/outcome, source match, stage timings, grader version and prompt/case hashes. It does not output answers, document text or identifiers. Failed cases return a nonzero exit status. A timeout still reports available timing metadata in the current runner.

## Meaning of a pass
A pass means the authored fact/source checks passed. It is not a general semantic correctness proof or a statistically meaningful production accuracy estimate. Substring checks can miss unsupported extra claims or valid wording; maintainers must review failures and expand narrow exact alternatives carefully. Only explicitly reviewed standalone answers such as No or Unknown receive exact-answer allowances. Model output is additionally checked by the existing quote/source guard.

## October 17 observations
- All nine deterministic cases passed against isolated real PostgreSQL data after the supported-name comparison improvement.
- Unfamiliar lease case passed with the expected date and page. Total answer time 54.7708 seconds; embedding 2.6008 seconds; retrieval 0.0126 seconds; first model output 41.5016 seconds; generation 52.1213 seconds. Model: llama3.1:8b, CPU execution, context 4096.
- Initial flood/missing-fact results were correct terse answers (No / Unknown) that the first grader incorrectly rejected. Added exact alternatives and confirmed their retests passed: approximately 20.0 and 14.2 seconds total.
- Initial mixed-name answer stated that the names differ without naming the values. Added a general prompt instruction requiring actual compared values, rather than merely a match/difference conclusion. The prompt-only retest still failed completeness. Added a deterministic supported-name comparison that explicitly lists values and disclaims ownership inference; it passed at 0.007 seconds. A separate schema-free name comparison remains on RAG and failed expected-fact completeness after 23.6586 seconds despite correct source references. This model limitation remains unresolved.
- First-token time measures the first model fragment, potentially JSON syntax; the browser still receives a completed validated answer.

Results are in `docs/chat-quality-results-2026-10-17.jsonl`. They come from a tiny authored synthetic set and multiple prompt/grader revisions, not a held-out single-version benchmark. Broader documents, longer contexts, vector recall, prompt injection, repeatability and semantic completeness require continued evaluation.


Final regression check: 145 backend tests ran, 144 passed and one skipped. Evaluation artifacts contain results across multiple prompt/grader revisions; do not aggregate them into a production accuracy percentage. No customer data was used, no customer documents were changed, and no Git push occurred.
