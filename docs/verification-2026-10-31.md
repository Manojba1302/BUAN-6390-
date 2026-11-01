# Vault and Google sign-in verification — 2026-10-31

## Included changes
- Vault-first entry, default/custom folders and document organization.
- Store/read/index uploads before a loan; extraction for supported loan documents on application association.
- Multi-application attachments, replacement/version handling, and deletion/access regression coverage.
- Application-scoped chat grounding fixes and sanitized completion metrics.
- Google Identity Services sign-in with server-verified ID tokens, browser-bound single-use challenges, existing-password proof for account linking, lockout, and revocable HomeFlow sessions.
- Google retry UI distinguishes account linking from provider/network failures. Password login remains available.

## Current verification
- Frontend TypeScript/Vite production build passed.
- Backend: 301 tests passed, including opt-in PostgreSQL and object-storage integration checks (synthetic records cleaned by tests).
- Worker: 117 tests passed.
- Google-specific tests cover new/returning identity, stable subject despite email changes, existing-account password proof, legacy profile refusal, lockout, bad signature/claims/nonce, expired/missing/replayed/cross-browser challenges, verification outage recovery, configured audience, secure-cookie configuration, authenticated profile/logout revocation, and password-login compatibility.
- Real Google account flow completed by the user: opened the Vault without creating a loan application. Browser refresh retained the signed-in session.
- Existing-account Google linking was tested automatically; it was not exercised interactively with the user's password.
- Chat tests now mock the generation boundary, so regression runs do not contact a live model or depend on the selected provider.

## Reproduce
```powershell
docker compose up -d --build backend worker frontend
docker compose exec -T -e HOMEFLOW_DB_TEST=1 -e HOMEFLOW_INTEGRATION_TEST=1 backend python -m unittest discover -s tests -p '*_test.py'
docker compose exec -T worker python -m unittest discover -s tests -p 'test_*.py'
docker compose exec -T frontend npm run build
```
Use a local development stack for integration tests. Existing volumes are retained; do not delete volumes to update. The API creates the new tables idempotently on existing installations; SQL initialization files support fresh databases.

Google setup: see [google-sign-in.md](google-sign-in.md). Set GOOGLE_CLIENT_ID in the ignored local .env and recreate the backend. The public client must authorize the exact frontend origin. No Google client secret is used by this flow. Local .env, API keys, user documents, and database data are not included in Git.

## Remaining limits
- OpenRouter free-tier 429 rate limiting remains an external reliability constraint. Passing deterministic tests is not proof that every live model answer is correct.
- Prior document tests covered synthetic general documents, images/EXIF/HEIC, replacement/deletion and cross-customer access. Physical camera capture was excluded at the user's request; diverse real-world blur/glare/handwriting still require broader validation.
- Vault search UI filters metadata; full-text evidence retrieval currently runs in application-scoped chat.
- Production Google origin/publishing, HTTPS/cookie configuration and additional device/browser tests remain deployment checks.
- No processor-side implementation or production-readiness guarantee is implied by this test round.

## Follow-up verification: Vault chat and sign-in layout
- Reviewed the pending Vault-wide chat scope, nullable conversation application, customer filters, separate history scopes, and revised Google button layout. Vault-wide chat expands the earlier application-only scope; this is a product-scope change for review.
- Full repeat run: 307 backend tests passed with PostgreSQL/storage integration enabled; 117 worker tests passed; frontend TypeScript/Vite build passed.
- Six new Vault-chat tests cover document inventory without an application, customer isolation, conversation creation, separate scope records, and rejection of an unowned application. These do not constitute broad live LLM accuracy testing.
- Fresh visual browser verification was unavailable because browser control returned an access error. The prior real Google sign-in and refresh checks remain recorded above; the revised layout has build validation only in this round.
- OpenRouter availability/rate limits, broad live-model accuracy, production Google setup and additional-device checks remain outstanding.
