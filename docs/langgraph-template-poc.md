# LangGraph chat and document template POC

## Chat

`backend/app/agent/graph.py` wraps the existing evidence-based answer pipeline in resolve and answer nodes. Checkpoints contain only source file IDs and a turn count; document text, questions and answers are transient runtime context, not checkpoint state. Each thread is scoped by customer, application, conversation and session start time. Single-document follow-ups reuse the last source; ambiguous references ask for clarification. Ownership is checked again when loading sources.

Closing or switching chat calls the authenticated end-session endpoint. Saved conversation history remains in PostgreSQL. Inactive graph sessions expire after 30 minutes when subsequent requests run. Memory uses InMemorySaver in this POC: a backend restart clears it, and multiple backend workers do not share it. Production requires a shared checkpointer and explicit session lifecycle/concurrency handling. This is document-focus memory, not unrestricted semantic conversation memory. Existing model latency and answer-quality limitations remain.

## Template POC

Open the profile menu, choose Generate document (POC), preview Markdown and download a sample PDF. LangGraph is not used here; this is deterministic template filling. The allowlisted Markdown template lives in `backend/app/templates/application-summary.md` (version poc-2). It covers the applicant, current residence, loan and property, employment and monthly income, assets, debts, declarations and attached documents. Only customer-confirmed or customer-corrected answers populate it; unreviewed document proposals remain visibly marked MISSING. The Social Security number shows only its last four digits. Preview and download enforce application ownership. PDF generation uses ReportLab with a restricted plain-text/headings/bullets renderer (US Letter, DejaVu Sans for accented and non-Latin names, falling back to Helvetica when the font is not installed), not arbitrary HTML or executable templates. PyMuPDF renders the preview images from the same PDF that is downloaded.

The sample is not an approval, disclosure or signed agreement. Final business templates, richer formatting, template editing/version management, generated-document persistence and signing are outside this POC. No generated customer document is copied to the evaluation lake.

## Verification

- Backend suite: 152 tests, 151 passed, 1 skipped, against a disposable PostgreSQL database.
- Frontend production build passed.
- Browser: profile action opens the generator; populated Markdown preview and missing-field markers verified with the existing application.
- Synthetic one-page PDF rendered and visually inspected for margins, wrapping and footer placement.
- Treasury.sh UX work remains separate. No Git push performed.
