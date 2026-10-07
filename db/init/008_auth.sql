-- 008_auth.sql
-- Login tables. Until now the API created these at start-up (backend/app/main.py);
-- moving them here puts every table in db/init. Names and types match
-- backend/app/db/models.py exactly, so the API's start-up check finds them and does nothing.

BEGIN;

-- One login per customer. Password is a salted scrypt hash, never the password itself.
CREATE TABLE IF NOT EXISTS auth_account (
    customer_id     UUID PRIMARY KEY REFERENCES customer(customer_id) ON DELETE CASCADE,
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    failed_attempts INTEGER NOT NULL DEFAULT 0 CHECK (failed_attempts >= 0),
    locked_until    TIMESTAMPTZ                          -- set after too many failed logins
);

-- Signed-in sessions. Only a hash of the cookie token is stored.
CREATE TABLE IF NOT EXISTS auth_session (
    token_hash  TEXT PRIMARY KEY,
    customer_id UUID NOT NULL REFERENCES customer(customer_id) ON DELETE CASCADE,
    expires_at  TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_auth_session_customer_id ON auth_session (customer_id);

-- Password reset links: single use, expire after 30 minutes. Only a hash of the token is stored.
CREATE TABLE IF NOT EXISTS password_reset (
    token_hash  TEXT PRIMARY KEY,
    customer_id UUID NOT NULL REFERENCES customer(customer_id) ON DELETE CASCADE,
    expires_at  TIMESTAMPTZ NOT NULL,
    used        BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS ix_password_reset_customer_id ON password_reset (customer_id);

COMMIT;
