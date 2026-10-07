# Database Fixes and Verification

## Overview

These changes improve the reliability of the HomeFlow PostgreSQL database.

They keep customer records linked correctly, prevent invalid file metadata,
preserve application information when a source file is deleted, and provide
consistent login-table rules.

This document explains each change, how to apply it, and what has been verified.

## 1. Changes Included

| Script | Location | Purpose |
|---|---|---|
| `003_file_application_ownership.sql` | `db/init` | Ensures a file and its linked application belong to the same customer. |
| `004_document_chunk_ownership.sql` | `db/init` | Ensures document chunks belong to the customer who owns the source file. |
| `005_file_metadata_checks.sql` | `db/init` | Prevents negative file sizes, page counts, and processing-attempt counts. |
| `006_source_file_relationships.sql` | `db/init` | Links application fields, employment records, and asset records to existing source files. |
| `007_source_file_customer_ownership.sql` | `db/init` | Ensures application details and their source files belong to the same customer. |
| `008_auth.sql` | `db/init` | Creates the login account, session, and password-reset tables when they are missing. |
| `009_auth_existing_tables.sql` | `db/migrations` | Updates existing login tables with the expected defaults, checks, and deletion rules. |

The base database structure is defined in `db/init/001_schema.sql`.

## 2. Customer Ownership and Relationships

### Files and applications

A file can be linked to an application only when both belong to the same customer.

Deleting an application clears the file's application link and preserves
the file record in the customer's vault.

### Document chunks

Document chunks are smaller sections of document text used for search.

Each chunk must belong to the same customer as its source file.
Deleting a file record also deletes its related chunks.

### Application details and source files

Application fields, employment records, and asset records can reference
the documents that supplied their information.

The database checks that:

- The source file exists.
- The detail record belongs to the customer who owns its application.
- The source file belongs to that same customer.

Deleting a source file clears the source-file link while preserving
the application detail record.

Deleting an application removes its related detail records.

These rules protect database relationships. They do not replace
application-level permission checks.

## 3. File Metadata

The database rejects negative values in:

- `size_bytes`: the file size.
- `page_count`: the number of pages.
- `attempts`: the number of processing attempts.

Zero is allowed. File size and page count may be unknown (`NULL`).
Processing attempts must have a value.

## 4. Login Tables

The login-related tables are:

| Table | Purpose |
|---|---|
| `auth_account` | Stores the customer's login email, password hash, failed-attempt count, and lock information. |
| `auth_session` | Stores login-session token hashes and expiry times. |
| `password_reset` | Stores password-reset token hashes, expiry times, and whether a token has been used. |

The database rules ensure that:

- Each customer has at most one login account.
- Login email addresses are unique.
- Failed login attempts default to `0` and cannot be negative.
- Password-reset records default to unused (`false`).
- Deleting a customer also deletes their related login account,
  sessions, and password-reset records.

The application is responsible for enforcing session expiry,
reset-token validity, and account-lockout behaviour.

## 5. Applying the Changes

### New databases

With the project's Docker configuration, SQL files in `db/init`
run in filename order when PostgreSQL initializes an empty data volume.

Script `008_auth.sql` supplies the login-table rules for a new database.
Script `009_auth_existing_tables.sql` is intended to update older,
existing login tables.

### Existing databases

Downloading updated code or restarting Docker does not automatically
apply SQL changes to an existing database.

Before applying changes:

1. Check which scripts and database rules are already installed.
2. Apply only the missing changes, following their dependencies.
3. Run each complete script, including its transaction statements.
4. Stop and investigate if a script reports an error.

For login tables:

- If any login tables are missing, run `008_auth.sql` first.
- Apply `009_auth_existing_tables.sql` to align existing table rules.

Script `008_auth.sql` does not change the definitions of tables that
already exist. Scripts in `db/migrations` require a separate execution step.

Do not rerun scripts blindly or delete database records or Docker
data volumes to make a migration succeed.

## 6. Verification Completed

### Database setup and relationship checks

The following checks passed locally on October 5–6, 2026:

- Correct file/application ownership was accepted.
- Incorrect file/application ownership was blocked.
- Files remained in the customer vault after application deletion.
- Correct chunk ownership was accepted.
- Incorrect chunk ownership was blocked.
- Deleting a file removed its document chunks.
- Allowed metadata values were accepted and negative values were blocked.
- Source-file links rejected nonexistent files.
- Source-file ownership checks blocked another customer's files.
- Application details were preserved after source-file deletion.
- Application deletion removed its related detail records.

A fresh database initialized successfully using `001_schema.sql`
and scripts `003` through `007`.

### Backend model checks

On October 7, 2026:

- The updated application-field, employment, and asset models loaded.
- All three tables were queried successfully.
- Test records were saved with the expected customer ownership.
- Temporary changes were rolled back.

### Sample document workflow

On October 7, 2026, the reusable document workflow test completed
with 24 passed checks and no failed checks.

The test used one fictional bank statement and confirmed:

- The file was linked to the expected customer and application.
- Processing completed and file metadata was saved.
- Nine expected fields were stored with page-one evidence.
- A reviewed correction was saved separately from the original value.
- Document text and 768-dimensional embeddings were stored.
- Retrieval returned the sample document and its source page.
- An unused customer ID retrieved no documents, with or without
  an application filter.

The test did not change database records.

### Login-table changes

On October 7, 2026:

- Script `008` created the three login tables in the test database.
- Script `009` completed in both the test and local HomeFlow databases.
- Expected defaults and constraints were confirmed in the test database.
- No negative failed-attempt values existed in the local HomeFlow
  database before applying `009`.
- An existing user successfully logged in after the update.

## 7. Test Files

The following files are stored in `db/tests`:

| File | Coverage |
|---|---|
| `test_file_application_ownership.sql` | File/application ownership and vault preservation. |
| `test_document_chunk_ownership.sql` | Chunk ownership and deletion with its source file. |
| `test_file_metadata_checks.sql` | Allowed and rejected metadata values. |
| `test_source_file_relationships.sql` | Source-file references and preservation of detail records. |
| `test_source_file_customer_ownership.sql` | Customer ownership across applications, details, and source files. |
| `test_document_workflow.py` | Stored results and direct retrieval for the fictional bank-statement fixture. |
| `Document_Workflow_Test.md` | Instructions for running the document workflow test. |

Run tests against a separate test database where possible.

The SQL tests use temporary fictional records and end with `ROLLBACK`.
If a test stops before reaching `ROLLBACK` in pgAdmin, run `ROLLBACK`
in the same Query Tool connection.

## 8. W-2 Checklist

The current database requires two W-2 documents, with guidance requesting
the two most recent tax years.

`db/migrations/002_w2_two_years.sql` remains available for older databases.
The base schema already includes this requirement for new databases.

A file count of two does not prove that the documents cover two different
tax years. Date-coverage validation is a separate requirement.

## 9. Remaining Verification

The completed checks do not establish that every application workflow
is fully tested.

Remaining work includes:

- Confirming fresh database initialization through script `008`.
- Checking that the authentication models match the updated SQL rules.
- Testing password reset, session expiry, and account lockout.
- Testing customer access restrictions through authenticated API requests.
- Validating AI-generated answers and extraction accuracy across
  additional document types.
- Investigating the observed classification error and upload-screen feedback.
- Confirming physical-file deletion behaviour in MinIO.

Database relationship tests verify PostgreSQL records. They do not
verify deletion of physical documents, complete API authorization,
or overall AI accuracy.
