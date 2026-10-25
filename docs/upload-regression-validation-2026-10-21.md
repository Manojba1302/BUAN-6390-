# Upload regression validation - 2026-10-21

## Scope
Four customer-supplied originals were tested locally: native payroll PDF, native four-page bank statement, native W-2 PDF, and a photographed driver license. A separate test account/application was used. Personal values and test credentials are excluded from this report. No user application was edited or submitted and nothing was pushed.

## Reproduced problems
- Earlier W-2 extraction reported completion with only one field. The 8B extractor also timed out after 180 seconds.
- PDF content-stream order separated W-2 labels from their values. Globally sorted text helped model reading but interleaved payroll columns and broke address recovery.
- Bank extraction revisited continuation pages because deterministic summary recovery ran only after the page loop.
- A failed initial queue publication left a file queued indefinitely.
- Synchronous classification ran inside an async API handler.
- The 8B text, 4B image and embedding models remained resident together (approximately 8.3 GiB). Available Windows RAM fell to about 560 MiB. Image classification took 87 seconds; a later 8B payroll rerun timed out despite bounded output.

## Repairs
- Preserve original text for evidence/address recovery; provide separately layout-ordered, whitespace-normalized text to the model.
- Constrain extraction to the known field schema, compact values and bounded output. Native values require matching source text; printed date normalization is supported. Preserve existing payroll/bank source checks.
- Recover source-based fields before deciding whether another page needs extraction. Optional fields and unlabelled name parts no longer force continuation-page calls.
- Recognized native continuation categories still identify mixed documents; category-free native continuation pages do not invoke the classifier again.
- Release document models after inference; existing chat callers retain the server retention default.
- Run classification in a thread pool. Initial queue failure becomes visible and retryable.
- Retain the earlier required W-2-field completion guard. Old completed W-2s missing core identity/wage fields can now be retried from document review; unsaved edits must be saved first.
- Reprocessing does not insert competing proposals for a previously corrected field. Verified against PostgreSQL inside a rolled-back isolated test transaction.

## Live results
The first constrained 8B round saved W-2 (11 fields), payroll (18, missing address), bank (13) and license (11). Key payroll and bank financial values matched their sources. Its payroll rerun later timed out.

With final text/recovery changes and the installed llama3.2:3b extractor, isolated reprocessing saved:

| Document | Fields | Measured processing time |
| --- | ---: | ---: |
| Payroll | 19 | 57.85 seconds |
| Bank statement | 13 | 39.57 seconds |
| W-2 | 11 | 65.07 seconds |

The license completed through gemma3:4b with 11 fields; expiry date and separate holder were verified. Its final memory-release configuration has not been separately benchmarked.

33 live API assertions passed: source financial values, payroll position/rate/basis/address, no invented overtime/bonus, license expiry and different holder, name and four address suggestions, no automatic duplicate jobs, saved correction with raw evidence preserved, confirmed application name retained, account profile unchanged, wrong category warning, duplicate-upload handling, and incomplete-application submission rejection.

## Local configuration
Only ignored local .env EXTRACTOR_MODEL is set to llama3.2:3b based on this comparison. Vision/classifier remain gemma3:4b. Chat remains its existing llama3.1:8b configuration. The team .env.example defaults are unchanged. No model was downloaded or deleted.

## Limits
This is four-document acceptance coverage, not a guarantee for arbitrary layouts. Photos remain slower than native PDFs on CPU. The full browser/mobile upload interaction and successful submission of a fully completed loan application were not tested in this round. Existing previously incomplete user documents were not automatically reprocessed or overwritten.

## Regression checks
54 worker tests passed. The backend suite completed 167 tests with 64 environment-gated tests skipped (103 passed). Frontend production build passed. The 33 live acceptance assertions above exercise the actual local API/database separately from those skipped suites.
