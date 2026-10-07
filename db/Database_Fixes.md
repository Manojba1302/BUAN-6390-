# Database Integrity and Ownership Checks

## Purpose

Keep customer, application and document records correctly connected.
These rules prevent incorrect ownership, invalid source-file links
and negative file metadata.

## Migrations

All migration files listed below are in `db/init`.

| Migration | What it does |
|---|---|
| `003_file_application_ownership.sql` | Requires a file and its linked application to belong to the same customer. Deleting the application preserves the file in the customer’s vault. |
| `004_document_chunk_ownership.sql` | Requires each document chunk to belong to the same customer as its source file. Deleting the file removes its chunks. |
| `005_file_metadata_checks.sql` | Prevents negative file sizes, page counts and processing attempts. |
| `006_source_file_relationships.sql` | Requires source-file references in application fields, employment and assets to point to an existing file. |
| `007_source_file_customer_ownership.sql` | Requires those source files to belong to the same customer as the application. Automatically sets the customer ID on the related detail records. |

Zero values are allowed for file metadata. File size and page count
may be unknown (`NULL`); processing attempts remain required.

Deleting a source file preserves the application field, employment
or asset record and clears its source-file reference.

## Applying the Changes

### New Databases

With the project’s Docker Compose configuration, scripts in `db/init`
run in filename order when PostgreSQL initializes an empty data volume.

### Existing Databases

Downloading updated code or restarting Docker does not automatically
apply migrations to an existing database.

1. Connect to the correct HomeFlow database.
2. Identify which migrations have already been applied.
3. Run only the missing migrations, in numerical order.
4. Run each complete migration once, including `BEGIN` and `COMMIT`.
5. If a migration fails, stop and investigate the error.

These migrations are not designed for repeated execution. Do not delete
records or the Docker data volume to force a migration to succeed.

Migration `007` depends on the earlier ownership and source-file changes.
It replaces the three source-file foreign keys introduced by `006`
with foreign keys that also check customer ownership.

### Checking Installed Constraints

The following constraint names help identify installed changes:

| Migration | Constraints |
|---|---|
| `003` | `file_application_customer_fkey` |
| `004` | `document_chunk_file_customer_fkey` |
| `005` | `file_size_bytes_nonnegative`, `file_page_count_nonnegative`, `file_attempts_nonnegative` |
| `006`, before `007` | `application_field_source_file_fkey`, `employment_source_file_fkey`, `asset_source_file_fkey` |
| `007` | `application_field_source_file_customer_fkey`, `employment_source_file_customer_fkey`, `asset_source_file_customer_fkey` |

After `007` is installed, the original `006` constraint names are
expected to be absent. Do not rerun `006` because those names are missing.

If changes appear partially installed, inspect the constraints, columns
and triggers before running another migration.

## Testing

After applying all migrations through `007`, run these complete scripts:

- `db/tests/test_file_application_ownership.sql`
- `db/tests/test_document_chunk_ownership.sql`
- `db/tests/test_file_metadata_checks.sql`
- `db/tests/test_source_file_relationships.sql`
- `db/tests/test_source_file_customer_ownership.sql`

Use the latest test files from the repository. The source-file
relationship test expects the constraint names introduced by `007`.

Each test uses fictional records and ends with `ROLLBACK` to remove
temporary changes. This does not undo previously committed migrations.

When using pgAdmin, if a test stops before reaching `ROLLBACK`, run
`ROLLBACK;` in the same Query Tool connection.

## Verified Results — October 6, 2026

The following checks passed on a local test database:

| Test area | Checks passed |
|---|---:|
| File and application ownership | 3 |
| Document-chunk ownership | 3 |
| File metadata | 6 |
| Source-file relationships, after migration `007` | 7 |
| Source-file customer ownership | 18 |

The tests confirmed that:

- Valid relationships are accepted.
- Incorrect customer ownership is blocked.
- Nonexistent source files are rejected.
- Negative metadata values are rejected.
- Deleting an application preserves its files in the customer vault.
- Deleting a file removes its document chunks.
- Deleting a source file preserves application fields, employment and assets.
- Deleting an application removes its related detail records.

Fresh database initialization was verified with `001`, `003`, `004`
and `005`. Migrations `006` and `007` were then applied and tested.
A fresh initialization including all migrations through `007`
remains to be verified.

## Scope

These tests verify database rules and relationships. They do not verify
API access controls, AI extraction accuracy, document-period coverage
or deletion of physical files from MinIO.

Fresh database initialization was verified on October 6, 2026.
All six scripts (`001`, `003`, `004`, `005`, `006` and `007`)
ran successfully in order on an empty database, with no initialization errors.

## Document workflow testing — October 7, 2026

Testing used the fictional file `alex_bank_statement_sample.pdf`
on a local Docker environment.

### Verified results

- The upload created one file record linked to the application.
  No duplicate was found for this filename and application.
- Processing completed: one page was read and nine fields were
  saved with source-page references and supporting text.
- The extracted name, dates and amounts matched the sample.
- One document chunk and a 768-dimensional embedding were saved.
  The chunk and source file had matching customer IDs.
- The document appeared in the application and My vault.
- An institution-name edit was saved separately from the original
  AI value, marked as corrected and retained after refreshing.
- A search for the closing balance retrieved page 1 of the sample,
  containing the $5,000 closing balance.
- A simulated different customer ID retrieved no documents,
  both with and without an application filter.

### Search query fix

The older local copy of `backend/app/api/v1/chat.py` failed because
PostgreSQL could not determine the application ID parameter type.

Adding an explicit UUID cast to the NULL check resolved the error.
The GitHub code reviewed already contained this fix.

### Limitations and follow-up

- These results cover one fictional bank statement.
- The customer-filter test called the retrieval function directly.
  It does not verify login or API access controls.
- Retrieval was tested; generated chat answers and their citations
  were not tested.
- An Ollama classification request returned an error, although
  background processing later completed successfully.
- The upload screen did not clearly show completion during testing.
  The saved document became visible after closing and refreshing.
- Other document types, date coverage and missing-page checks
  still require testing.


