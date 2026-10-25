# License evidence validation - October 24, 2026

## Finding
The image path accepted vision-model strings without requiring source support. OCR included usable numbered name/address lines, but the compact response omitted surname and changed street spelling. An earlier check for the correct identifier used substring matching: its presence inside a longer OCR token did not establish the exact identifier.

## Change
Added shared/license_evidence.py and a worker recovery step specific to drivers_license. Unambiguous numbered surname/given-name and address lines recover source spelling and retain OCR quotes/page references. Conflicting recovered values across pages are omitted. A license identifier is retained only when its exact token is supported after an explicit license-number label in OCR; ambiguous or unsupported identifiers remain missing for user review. User-saved corrections remain protected by the existing persistence layer. Other document types do not use this recovery.

## Verification
Fresh read-only extraction on the supplied stored photo completed in 83.34 seconds with 10 fields. Full name, surname, complete street address, birth date, issue date, and expiry date checks passed. Unsupported license number was omitted. This run did not overwrite stored document data.

60 worker tests passed, including changed digits, identifier substrings, unrelated number labels, missing OCR, conflicting owners and other-document isolation. Backend: 170 tests, 64 skipped, 106 passed. Git whitespace checks passed.

## Limits
This is conservative numbered-license recovery, not arbitrary identity-document coverage or independent verification that OCR is correct. Missing/unclear labels leave fields for manual review. Photo inference remains slow; concurrent request coordination and model-lifetime changes are not implemented in this change. Existing extracted records are not automatically rewritten. No Git push or main merge.
