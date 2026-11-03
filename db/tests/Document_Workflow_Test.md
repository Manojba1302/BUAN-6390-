# Fictional bank-statement workflow check

This read-only test verifies an already-processed upload of the original Alex Morgan
fictional bank statement. It does not upload documents or validate every document type.

## Preparation

Use the isolated review app with this combined source, the nomic-embed-text model,
and the same FIELD_ENCRYPTION_KEY in backend and worker if encryption is enabled.
Do not share the key or commit .env. A key mismatch must be investigated, not ignored.

Upload the fictional September 2026 statement. It must show Alex Morgan, Demo Learning
Bank, account ending 0001, opening balance 4000, deposits 2000, withdrawals 1000 and
closing balance 5000. Wait for completion and save an institution correction in the UI.
Record the file, customer and application UUIDs from this new test environment.
IDs from the old HomeFlow database are not valid substitutes.

The assertions expect the original nine fields, one page and the fixture's exact values.
A failure may indicate extraction drift or an intentionally changed field contract;
compare the document and requirements before changing the expected results.

## Run from the isolated app's project folder

The running backend must use this combined project's source. Replace the placeholders
below with the new UUIDs and exact saved correction before executing.

```powershell
docker compose cp .\db\tests\test_document_workflow.py backend:/tmp/test_document_workflow.py
```

```powershell
docker compose exec -w /srv/app backend python -c "import runpy; runpy.run_path('/tmp/test_document_workflow.py', run_name='__main__')" --file-id FILE_UUID --customer-id CUSTOMER_UUID --application-id APPLICATION_UUID --expected-correction "EXACT SAVED CORRECTION"
```

The updated test calls app.services.chat_evidence.retrieve and prefixes embedding
queries with search_query. Raw extraction values are decrypted in memory for the
fixture comparison. It does not rewrite them or reveal them in its PASS/FAIL output.

## Interpretation

The test checks metadata, ownership, nine fields, evidence, correction preservation,
768-dimensional embeddings and direct customer-scoped retrieval. A random unused
customer ID must return no results with and without the application filter.

This is NOT an authenticated API permission test, an encryption coverage audit,
a MinIO deletion test or proof of AI accuracy. Hybrid retrieval can return a lexical
match, so a successful search alone does not prove semantic ranking quality.
The script checks stored embedding dimensions separately.

The old version passed 24 checks on October 7. This updated version has been syntax
checked but has not yet been run against an uploaded fixture in this combined app.
