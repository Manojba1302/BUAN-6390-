# Application QA — 2026-10-24

## Result
Broad regression round completed; not a production-readiness sign-off. One live-model accuracy failure reproduced. Full fresh-upload and real-device coverage remain outstanding.

## Verified
- Backend suite with disposable PostgreSQL: 195 tests, 194 passed, one integration test skipped.
- Skipped document lifecycle test separately executed on the local stack with self-cleaning synthetic records: passed. Exercises correction saving, ownership restrictions, detach/reuse, storage retention, submitted/processing guards and permanent deletion of its own fixture.
- Worker suite: 60 passed.
- Frontend TypeScript and production build: passed, including after review-label fix.
- Structured chat evaluation: 9/9 passed (synthetic documents; no live generation).
- Live general chat: 3/4 passed; lease date 61.005s, policy exclusion 19.394s, missing fact 18.650s. These are observed request times, not performance guarantees.
- Browser: authenticated session, refresh persistence, all six section navigation, stored pay-stub review (19 fields displayed), and stored bank-statement listing (13 fields).
- Template: optional preview and direct download flow; two-page rendered preview visible; download from preview starts successfully. PDF generation/render tests passed. Missing fields visibly marked.
- Review page: replaced internal missing-field keys with dictionary labels; browser verified after refresh.

## Open findings
1. Live unfamiliar-document name comparison fails completeness. Both sources match, but repeat answer was only: "The names in the two documents are different." It omits both actual names. First attempt 29.213s; repeat 15.176s. Do not weaken grader to accept this incomplete comparison.
2. Local model latency remains high (roughly 19–61 seconds in successful general cases). Structured lookup speed does not represent model speed.
3. Embedded original PDF in document review appeared blank/dark in the in-app browser during this round; extracted fields loaded. Template preview uses rendered images and works. Check original document viewer compatibility separately.
4. Browser width was 592px. This is a narrow-window smoke check, not iPhone/Android/tablet/desktop certification.

## Not established by this round
- Fresh upload -> classifier -> OCR/model -> worker -> saved fields across every supported file type and the four supplied real files.
- End-to-end successful financial application submission in the browser; no real application was submitted or consent accepted.
- Complete password reset/email delivery, load/concurrency, keyboard/screen-reader and cross-browser tests.
- Field-by-field accuracy of all previously stored extraction data.

## Changes in this round
Template optional-preview/download implementation and PDF raster preview verification; readable review field labels. Existing unrelated working-tree changes preserved. No Git commit or push.

## Evidence
Local logs: homeflow-full-test-2026-10-24.log, homeflow-chat-test-2026-10-24.log, homeflow-live-chat-test-2026-10-24.log in the Mortgage workspace. Screenshot: .homeflow-proof/template-preview.png. Logs and screenshots are local artifacts, not added to Git.
