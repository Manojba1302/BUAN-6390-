# Vijay chat requirements — implementation checkpoint 2026-10-17

## Implemented in this local pass
- Treasury typography inspected from rendered computed styles: Lexend body (300 on reference), Fraunces Hero headline (350 on reference). HomeFlow uses locally bundled open-source Lexend Variable and Fraunces Variable, with body weight 400 for forms. It is an inspired pairing, not an exact copy of Treasury's custom hero font.
- New active conversation on opening chat; closing/unmounting discards client context. Saved History is separate. Message context_after prevents older historical answers from supplying follow-up context in the new browser session. This is context isolation, not server-side conversation revocation or a retention/deletion policy.
- Domain scope gate before retrieval/tool routing. Unrelated questions receive an explicit project-only response. Conservative keyword policy can have false positives/negatives and needs continued semantic evaluation.
- Agent policies separated into backend/app/agent; existing service imports remain compatible. Full retrieval/generation orchestration is still in the API/service layer, so separation is incremental.
- Redaction of known scoped SSN/license/account/employee identifiers, formatted SSNs and email addresses at chat boundaries. New history stores document/page/name references instead of raw evidence passages. Existing history is sanitized on read, not rewritten in the database. Original documents/extractions remain unchanged. This is not comprehensive PII detection, encryption, tokenization, or a complete compliance guarantee.
- Backend first-token and total model-generation timing using Ollama streaming. The browser still receives only the validated completed answer. No claim that streaming telemetry solves CPU/memory latency. No prompt/response content is included in timing logs.

## Validation
- Full isolated PostgreSQL backend suite: 133 run, 132 passed, one skipped.
- After the final direct-response redaction change: 42 targeted backend tests passed.
- Worker suite: 35 passed. Frontend production build passed; local fonts emitted into build assets.
- Browser: confirmed Lexend/Fraunces loaded, inspected sign-in layout, authenticated using existing browser autofill, submitted unrelated joke request and observed project-only refusal; closed/reopened chat and observed a new empty conversation with History available.

## Outstanding
- Comprehensive names/addresses/phone/financial-value protection, tokenization strategy, historical storage remediation and agreed retention policy.
- Semantic scope evaluation and held-out RAG correctness tests; a human evaluation owner remains unassigned.
- Actual first-token benchmarks on local hardware, user-visible streaming design and broader answer accuracy/performance.
- Full agent harness separation and full mobile application review.
- PDF generation remains future work pending templates.

Changes are local, not pushed. Earlier integration PR remains separate.
