-- Verify login rules using fictional records; roll back all test data.
BEGIN;
DO $$
DECLARE
    owner_id uuid := gen_random_uuid();
    missing_id uuid := gen_random_uuid();
    attempts integer;
    reset_used boolean;
BEGIN
    INSERT INTO public.customer(customer_id, email)
    VALUES(owner_id, owner_id::text || '@example.invalid');
    INSERT INTO public.auth_account(customer_id, email, password_hash)
    VALUES(owner_id, owner_id::text || '@example.invalid', 'fictional-test-hash');
    SELECT failed_attempts INTO attempts FROM public.auth_account WHERE customer_id = owner_id;
    IF attempts IS DISTINCT FROM 0 THEN RAISE EXCEPTION 'FAIL: failed attempts default'; END IF;
    RAISE NOTICE 'PASS: failed attempts default to zero';

    BEGIN
        UPDATE public.auth_account SET failed_attempts = -1 WHERE customer_id = owner_id;
        RAISE EXCEPTION 'FAIL: negative attempts accepted';
    EXCEPTION WHEN check_violation THEN
        RAISE NOTICE 'PASS: negative failed attempts blocked';
    END;

    INSERT INTO public.auth_session(token_hash, customer_id, expires_at)
    VALUES('session-' || owner_id::text, owner_id, now() + interval '1 hour');
    INSERT INTO public.password_reset(token_hash, customer_id, expires_at)
    VALUES('reset-' || owner_id::text, owner_id, now() + interval '30 minutes');
    SELECT used INTO reset_used FROM public.password_reset WHERE customer_id = owner_id;
    IF reset_used IS DISTINCT FROM false THEN RAISE EXCEPTION 'FAIL: reset default'; END IF;
    RAISE NOTICE 'PASS: password reset defaults to unused';

    BEGIN
        INSERT INTO public.auth_session(token_hash, customer_id, expires_at)
        VALUES('missing-' || missing_id::text, missing_id, now());
        RAISE EXCEPTION 'FAIL: nonexistent session owner accepted';
    EXCEPTION WHEN foreign_key_violation THEN
        RAISE NOTICE 'PASS: nonexistent session owner blocked';
    END;

    DELETE FROM public.customer WHERE customer_id = owner_id;
    IF EXISTS (SELECT 1 FROM public.auth_account WHERE customer_id = owner_id)
       OR EXISTS (SELECT 1 FROM public.auth_session WHERE customer_id = owner_id)
       OR EXISTS (SELECT 1 FROM public.password_reset WHERE customer_id = owner_id) THEN
        RAISE EXCEPTION 'FAIL: customer deletion left login records';
    END IF;
    RAISE NOTICE 'PASS: customer deletion removes account, session and reset records';
END $$;
ROLLBACK;
