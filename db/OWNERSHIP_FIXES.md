# Database Ownership Fixes

## Purpose

Prevent files and document chunks from being assigned to the wrong customer.

## Changes

- `003_file_application_ownership.sql`: requires a file and its linked
  application to belong to the same customer. Deleting the application
  preserves the file record in the customer's vault.
- `004_document_chunk_ownership.sql`: requires a document chunk and its
  source file to belong to the same customer. Deleting the file removes
  its chunks.

Both scripts are in `db/init`.

## Applying the changes

### New databases

With the project's Docker Compose configuration, scripts in `db/init`
run in filename order when PostgreSQL initializes an empty data volume.

### Existing databases

Downloading the updated code or restarting Docker does not apply these
scripts to an existing database automatically.

1. Connect pgAdmin to the project's HomeFlow database.
2. Check whether these constraints already exist:
   - `file_application_customer_fkey` on `public.file`
   - `document_chunk_file_customer_fkey` on `public.document_chunk`
3. If neither fix is installed, run the complete `003` script first,
   then the complete `004` script.
4. Run each migration only once. They are not designed for repeated runs.
5. If a script reports an error, stop and investigate. Do not delete
   records or the Docker data volume to force it to succeed.

If only one fix is installed, apply only the missing migration.
If constraints appear partially installed, inspect the database before
running either script.

## Testing

Run each complete script in pgAdmin:

- `db/tests/test_file_application_ownership.sql`
- `db/tests/test_document_chunk_ownership.sql`

Each script uses fictional records and ends with ROLLBACK to remove them.
If execution stops with an error before ROLLBACK, run ROLLBACK in that
same Query Tool connection.

## Results — October 5, 2026

All six checks passed on Annu's local HomeFlow PostgreSQL database:

1. Correct file/application ownership accepted.
2. Changing a file to another customer blocked.
3. File record preserved when its application was deleted.
4. Correct chunk/file ownership accepted.
5. Changing a chunk to another customer blocked.
6. Chunk removed when its source file was deleted.

These tests check database relationships. They do not verify API access
control, AI accuracy, or deletion of physical documents from MinIO.

## File metadata checks — migration 005

File: `db/init/005_file_metadata_checks.sql`

Prevents negative values in size_bytes, page_count, and attempts.
Zero remains allowed. size_bytes and page_count may still be NULL;
attempts remains required.

For an existing database, run the complete migration once if these
constraints are not already installed:
- file_size_bytes_nonnegative
- file_page_count_nonnegative
- file_attempts_nonnegative

Downloading the code or restarting Docker does not apply this change
to an existing database. Annu's local database already has this fix.

Test: `db/tests/test_file_metadata_checks.sql`

All six local checks passed on October 5, 2026:
- Unknown size and page count accepted.
- Zero values accepted.
- Positive values accepted.
- Negative size_bytes blocked.
- Negative page_count blocked.
- Negative attempts blocked.

The test ends with ROLLBACK to remove temporary records.
