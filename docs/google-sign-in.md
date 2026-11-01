# Google sign-in
Uses Google Identity Services popup and server-side ID-token verification. Only openid/email/profile identity is used, not Gmail or Drive access. No client secret is needed for this flow.

1. Create/select the team Google Cloud project; billing is not needed for sign-in.
2. Configure Google Auth Platform branding and audience. In testing, add intended test users.
3. Create a Web application OAuth client with authorized JavaScript origin http://localhost:5173 (and http://127.0.0.1:5173 only if used). Popup callback is JavaScript; no redirect URI is required for this integration.
4. Save GOOGLE_CLIENT_ID in the local ignored .env. It is a public client identifier. Never commit client secrets.
5. Rebuild backend after requirements change: docker compose up -d --build backend. For client-ID-only changes, recreate backend to reload env.
6. Production: add exact HTTPS frontend origin, set FRONTEND_URL/CORS_ORIGINS and COOKIE_SECURE=true; complete Google publishing/branding requirements.

The button is hidden when unconfigured. Existing passwords continue to work. Google-only accounts have no local password. An existing customer email is never automatically claimed: linking requires that account's HomeFlow password and honors its lockout. Email-only legacy records require support. Google subjects, not email changes, identify returning accounts.

Verification checks signature, expiry, audience, issuer, verified email and a one-use 5-minute browser-bound nonce. No Google access/refresh tokens are stored. Sessions use the existing revocable HttpOnly cookie. New tables are created idempotently at backend startup.

Run: python -m unittest tests.google_auth_test tests.auth_test tests.code_standards_test
Local live verification (2026-10-31): user completed real Google account sign-in; HomeFlow opened the Vault without creating an application, and the session survived a browser refresh. Existing-account linking and error paths are covered by automated tests; production-domain and additional-device sign-in remain to be checked.
