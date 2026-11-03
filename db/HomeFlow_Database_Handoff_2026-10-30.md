# HomeFlow database integration: review handoff

Prepared October 30, 2026. Owner: Annu Choudhary, Database and Data Engineer.

## Review status

Database integration has passing automated and sample-upload evidence. This is a review candidate, not a fully validated release. No changes were pushed or merged into GitHub during this work. Live results below come from Annu's supplied PowerShell output and screenshots, not direct access to her laptop.

Baseline: supplied BUAN-6390--main (3).zip plus HomeFlow_Database_Updates.zip. No exact Git commit SHA was established for the ZIP. Reconcile against the team's current branch before submission.

## Changes prepared

- backend/app/db/models.py: ownership, metadata and authentication model updates; newer chat models retained.
- db/init/008_auth.sql: fresh authentication schema.
- db/migrations/009_auth_existing_tables.sql: upgrade existing authentication rules.
- db/tests/test_auth_rules.sql: authentication defaults, validation and deletion checks.
- backend/tests/database_model_alignment_test.py: five model checks.
- db/tests/test_document_workflow.py and Document_Workflow_Test.md: updated fixture workflow test and instructions.
- scripts/test_database_review.ps1: isolated PostgreSQL verification runner.
- db/Database_Fixes.md and DATABASE_REVIEW_README.md: integration documentation.

This handoff supersedes earlier NOT RUN entries only for the specific checks documented below. Do not commit the local .env, backup files or downloaded duplicate models files.

## Verified results

| Check | Evidence and result |
|---|---|
| Fresh initialization and SQL rules | Isolated homeflow-db-combined-review initialized; all six SQL test scripts completed successfully. |
| Model checks | Five tests passed inside homeflow-backend-db-review. |
| Backend suite | 227 tests reported in 13.322 seconds; 226 passed, one skipped; no failures. Five model checks are included in this suite and should not be added to its total. |
| Simulated authentication upgrade | Cloned review to review_upgrade_test; removed defaults/check and cascade rules to simulate older login definitions. Subsequent authentication test output showed all five checks passing. Migration execution output itself was not supplied. This does not establish preservation of pre-existing populated account data. |
| Isolated app | Seven containers running; database, MinIO and RabbitMQ healthy. Separate homeflow_combined_test volumes used. |
| Browser connection | Missing frontend API/CORS settings corrected; login succeeded. |
| Models | gemma3:4b, llama3.1:8b and nomic-embed-text downloaded. |
| Document processing | Fictional Alex Morgan statement: one page, bank_statement matched, seven fields extracted, one chunk embedded; worker ended with done. Initial RabbitMQ refusal recovered after five seconds. |
| Chat and source navigation | Correct closing balance 5000.00 and bank Demo Learning Bank; page-one source card opened the matching PDF. |
| Database status and ownership | File completed; page_count=1; processed_at populated; file customer matched application customer. |
| Extraction storage | Seven rows, all proposed and page 1: account_holder, beginning_balance, ending_balance, institution, period_end, total_deposits, total_withdrawals. |
| Embedding storage | One page-one chunk; 768-dimensional embedding; chunk customer matched file customer. |

Sample identifiers in the isolated test app:

- File: ca2a3a05-2bb3-4e1f-a361-2a165e59db82
- Customer: 325f63bb-a653-49d9-9ba5-77cc88b24a85
- Application: 15e2e63f-0c59-424e-a669-0fdb9d9219e7

## Known extraction issue and fixture mismatch

The PDF prints Statement Period: September 1 - September 30, 2026. period_end was stored as 2026-09-30, but period_start was absent. Investigate extraction/normalization before attributing a root cause. The account field was also absent; the fixture uses Account Reference: DEMO-0001, which needs review against the intended account-field contract.

The UI listed address, city, state and ZIP as missing. These are not printed in this fixture; their absence is not evidence of an extraction failure.

The reusable workflow test still asserts exactly nine extracted fields and a saved institution correction. The live upload has seven extracted rows and no demonstrated correction. Do not report that script as passed or weaken its assertions merely to obtain a pass. Separate database integrity checks from extraction expectations and reconcile fixture requirements with the team.

## Pending checks

1. Saved correction persistence and whether subsequent chat uses that correction. Current database rows remain proposed.
2. Direct retrieval isolation for this uploaded fixture across customers and applications. Passing ownership equality checks do not prove isolation.
3. Document removal, reuse and permanent deletion: document_lifecycle_test was skipped because it requires the local integration stack.
4. Upgrade preservation using seeded existing authentication records, including failure/rollback behavior on invalid data.
5. Encryption configuration and stored-data coverage: no FIELD_ENCRYPTION_KEY was shown in the test settings; encryption must not be claimed verified by this run.
6. Final source reconciliation, exact commit identification and team review before merge.

## Recommended review sequence

- Rahul reviews the combined models and authentication migration against the team's current branch.
- Processing owner investigates the missing period_start and account-reference handling.
- Annu completes focused database/retrieval checks and records any failures without repeating setup.
- Nikhila aligns the ERD, dictionary and mappings with the agreed schema.
- Submit a separate review branch with the intended changes and this evidence; do not replace newer team code wholesale or merge directly to main.

## Review-branch validation
- Branch: annu/database-integration-review
- Base commit: fa7544b
- Backend Docker build succeeded.
- Five model-alignment checks passed.
- Full backend suite: 227 tests in 12.769 seconds; 226 passed, one skipped, no failures.
- Tests used the isolated homeflow-db-combined-review database.
- Document lifecycle integration test remains skipped.
- Earlier uploaded-document observations came from the combined ZIP environment.
