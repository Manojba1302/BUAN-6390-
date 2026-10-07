-- Align existing app-created login tables with db/init/008_auth.sql.
-- Run 008 first if any login tables are missing.
-- This changes database rules, not stored account, session or reset values.
BEGIN;

-- Stop rather than wait indefinitely if another transaction holds these tables.
SET LOCAL lock_timeout = '5s';

-- New rows receive defaults when these values are omitted.
ALTER TABLE public.auth_account
    ALTER COLUMN failed_attempts SET DEFAULT 0;
ALTER TABLE public.password_reset
    ALTER COLUMN used SET DEFAULT false;

-- Validate existing rows too. Any negative count aborts the transaction;
-- do not silently correct or remove existing data.
ALTER TABLE public.auth_account
    DROP CONSTRAINT IF EXISTS auth_account_failed_attempts_check,
    ADD CONSTRAINT auth_account_failed_attempts_check
        CHECK (failed_attempts >= 0);

-- Remove a customer's login records when that customer is deleted.
-- These constraint names match the existing database and 008_auth.sql.
ALTER TABLE public.auth_account
    DROP CONSTRAINT auth_account_customer_id_fkey,
    ADD CONSTRAINT auth_account_customer_id_fkey
        FOREIGN KEY (customer_id) REFERENCES public.customer(customer_id)
        ON DELETE CASCADE;

ALTER TABLE public.auth_session
    DROP CONSTRAINT auth_session_customer_id_fkey,
    ADD CONSTRAINT auth_session_customer_id_fkey
        FOREIGN KEY (customer_id) REFERENCES public.customer(customer_id)
        ON DELETE CASCADE;

ALTER TABLE public.password_reset
    DROP CONSTRAINT password_reset_customer_id_fkey,
    ADD CONSTRAINT password_reset_customer_id_fkey
        FOREIGN KEY (customer_id) REFERENCES public.customer(customer_id)
        ON DELETE CASCADE;

-- Match the customer lookup indexes defined by 008.
CREATE INDEX IF NOT EXISTS ix_auth_session_customer_id
    ON public.auth_session (customer_id);
CREATE INDEX IF NOT EXISTS ix_password_reset_customer_id
    ON public.password_reset (customer_id);

COMMIT;
