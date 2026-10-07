# Document workflow test

This script repeats the database and retrieval checks used on October 7, 2026.
It reads an existing upload of `alex_bank_statement_sample.pdf`. It is specific
to that fictional fixture, not a generic accuracy test for arbitrary documents.

## Prepare the sample

1. Start the HomeFlow database, backend, storage, queue, worker and Ollama services.
2. Download the models configured for classification, extraction and embeddings.
3. Upload the fictional Alex Morgan statement through HomeFlow and wait for
   processing to finish. The statement must cover September 1–30, 2026, with
   opening balance 4000, deposits 2000, withdrawals 1000 and closing balance 5000.
4. In the extracted-field review screen, edit Institution to the full fictional
   institution wording. Refresh and confirm the correction remains.
5. Record the file UUID, expected customer UUID and expected application UUID.
   Use the IDs belonging to your own local test upload.

Do not use real mortgage documents or commit passwords, tokens or database dumps.

## Run from Windows PowerShell

Save `test_document_workflow.py` in `db/tests`. From the project root, copy it to
the running backend container. Copy it again whenever you change the script:

```powershell
docker compose -f docker-compose.yml -f compose.auth.yml cp .\db\tests\test_document_workflow.py backend:/tmp/test_document_workflow.py
```

Replace the example placeholders below with your upload IDs and the exact
institution correction you saved. This uses the backend's installed packages
and existing database connection. No extra pip installation is required.

```powershell
docker compose -f docker-compose.yml -f compose.auth.yml exec -w /srv/app backend python -c "import runpy; runpy.run_path('/tmp/test_document_workflow.py', run_name='__main__')" --file-id FILE_UUID --customer-id CUSTOMER_UUID --application-id APPLICATION_UUID --expected-correction "Demo Learning Bank (fictional institution)"
```

The runpy invocation makes the backend's `app` imports available while executing
the copied script. Each check prints PASS or FAIL. Any failed check or execution
error produces a nonzero exit code. In PowerShell, `$LASTEXITCODE` should be 0
after a successful run. A partial list of PASS messages is not a completed test.

## Checks and limits

- Expected file/application/customer relationship, completed state and metadata.
- One file with the same checksum for this customer and application.
- Nine expected original extracted values, page references and evidence presence.
- Exact user correction retained separately from the original institution value.
- Nonempty chunks with 768-dimensional embeddings and matching ownership.
- Actual backend retrieval with an application ID and with a NULL application ID.
- No results for a randomly generated unused customer ID in either search mode.

Database operations run in a read-only transaction and end with rollback.
The script requests a question embedding from Ollama but writes no database data.
It never marks proposed extraction fields as reviewed or uploads documents.

Retrieval uses the top six results. On a populated database, an expected sample
outside the top six causes a failure that needs investigation. This test does
not measure ranking quality across a representative document collection.

The unused-customer check verifies the retrieval filter directly. It does not
test authentication, HTTP authorization, or isolation between two signed-in
accounts. UI preview, vault display, refresh persistence and MinIO object access
must be checked separately. Generated answers, citation accuracy, multiple
document types, date coverage and missing pages are outside this script's scope.

## Known search-query prerequisite

Older copies of `backend/app/api/v1/chat.py` fail with AmbiguousParameter unless
both uses of the optional application ID are explicitly typed:

```sql
AND (CAST(:application_id AS uuid) IS NULL OR f.application_id = CAST(:application_id AS uuid))
```

The GitHub version inspected on October 7 already contained this fix. Preserve
newer team code when bringing a local checkout up to date.

## Validation status

The individual checks were exercised manually on October 7. The reusable script
has received a local Python syntax check; its full run against the Docker
database is still pending. Record that run's date and result before marking
this script as verified. Commit these files through a review branch and PR.
