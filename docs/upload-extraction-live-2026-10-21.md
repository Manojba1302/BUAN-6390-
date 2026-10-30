# Fresh-account upload and extraction verification - October 21, 2026

## Method

Created isolated local accounts through the real registration API, created draft applications, and uploaded the two user-supplied PDFs through authenticated classification and upload endpoints. Used the normal storage, queue, worker, extraction, markdown and embedding stages. Compared final API field values against rendered source pages. Existing customer application fields and corrections were not manually edited. Reprocessing flags were reset only on the explicitly isolated test files; actual field values were regenerated from the original PDFs.

Files: SSPUSADV.pdf (one native-text page) and eStmt_2026-09-25_20260930_102345.pdf (four native-text pages). Personal names, addresses, account numbers, account credentials and session tokens are excluded from this report and the sanitized result artifact.

## Failures reproduced

- First-pass classification took 99.3 seconds for the pay slip and 131.8 seconds for the statement despite readable native text.
- The local 4B extraction trial still timed out at 180 seconds. The 8B workload also created severe memory pressure in earlier attempts.
- The 3B trial completed, but produced unsupported zero overtime/bonus, a YTD tax amount in current deductions, YTD regular earnings in total YTD gross, inferred first/last name parts, and the illustrative account suffix from the prompt.
- Reuploading an existing file returned a successful duplicate response while leaving the file staged, making Submit appear ineffective.

## Changes

- Clear native-text type signals take a text-first classification path; ambiguous/image documents retain model classification. This uses document signals, not filenames or the selected category.
- Local EXTRACTOR_MODEL is now llama3.2:3b. The shared default remains llama3.1:8b; no model was deleted or downloaded.
- Stop extracting additional pages once all configured fields are available; all document pages are still retained for search.
- Read payroll current/YTD summary columns using PDF geometry. Native payroll categories require explicit labelled evidence. Missing overtime/bonus remain unknown, and full names are not silently split into name parts.
- Derive masked bank-account suffix from labelled source text; remove illustrative digits from the field prompt.
- Ignore duplicate queue delivery for completed documents.
- Duplicate upload response includes its application reference. Uploader shows Already saved and Review stored file, with current-application/other-application/Vault context. It does not move files automatically.

## Final results

- Both files: classification matched; upload HTTP 201; worker completed; markdown and searchable chunks saved.
- Pay slip: 19 saved fields, 22/22 source checks passed. Checked holder/employer, address, period, pay date, rate/basis/title, current gross/net/regular pay, deductions, withholding, YTD gross, and absence of invented optional/name-part values.
- Bank statement: 13 saved fields, 14/14 source checks passed. Checked holder/address, institution, account suffix, period, opening/closing balance, deposits/withdrawals and balance reconciliation.
- Both files appeared in the new account Vault. Repeat upload reused the same IDs and kept the Vault count at two. Anonymous file access returned 401.
- Six live conversation checks passed: inventory, pay rate/title, net-pay follow-up, closing balance, payroll summary and masked account lookup. Every result had owned source references. Observed local API response times were 0.04-0.09 seconds; these were deterministic field paths, not general LLM reasoning benchmarks.
- Final warm classification measurements were 0.11 and 0.09 seconds. Observed extraction runs were about 25-27 seconds for the pay slip and 70-91 seconds for the statement; CPU/memory load affects these timings.
- Backend discovery: 164 tests, 100 passed and 64 skipped (database-dependent opt-in checks not enabled). Worker: 42 tests passed. Frontend build passed.

## Limits

This validates these two supplied files and the measured operations, not all document layouts or arbitrary LLM questions. Missing optional earnings are unknown, not zero. Name parts require user confirmation when not labelled. General image extraction and LLM generation remain resource-sensitive. The account/upload/extraction/chat round used authenticated HTTP and the real queue worker; it is not a claim that a full browser signup was tested. No Git push performed.
