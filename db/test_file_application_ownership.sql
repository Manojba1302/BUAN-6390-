-- Test file ownership after applying migration 003.
-- Run this entire script together.
BEGIN;

DO $$
DECLARE
    alex_id UUID;
    priya_id UUID;
    app_id UUID;
    test_file_id UUID;
    blocked_constraint TEXT;
BEGIN
    -- Create two fictional customers.
    INSERT INTO public.customer (email)
    VALUES ('alex@example.invalid')
    RETURNING customer_id INTO alex_id;

    INSERT INTO public.customer (email)
    VALUES ('priya@example.invalid')
    RETURNING customer_id INTO priya_id;

    -- Create Alex's application.
    INSERT INTO public.application (customer_id)
    VALUES (alex_id)
    RETURNING application_id INTO app_id;

    -- Test 1: accept a file belonging to the application's owner.
    INSERT INTO public.file (
        customer_id, application_id,
        document_tag, original_name, storage_key
    )
    VALUES (
        alex_id, app_id,
        'bank_statement', 'test.pdf', 'ownership_test.pdf'
    )
    RETURNING file_id INTO test_file_id;

    RAISE NOTICE 'PASS 1: correct ownership accepted.';

    -- Test 2: reject changing the file to another customer.
    BEGIN
        UPDATE public.file
        SET customer_id = priya_id
        WHERE file_id = test_file_id;

        RAISE EXCEPTION 'FAIL: incorrect ownership was accepted.';
    EXCEPTION
        WHEN foreign_key_violation THEN
            GET STACKED DIAGNOSTICS
                blocked_constraint = CONSTRAINT_NAME;

            IF blocked_constraint <> 'file_application_customer_fkey' THEN
                RAISE;
            END IF;

            RAISE NOTICE 'PASS 2: incorrect ownership blocked.';
    END;

    -- Test 3: preserve the file when its application is deleted.
    DELETE FROM public.application
    WHERE application_id = app_id;

    IF EXISTS (
        SELECT 1
        FROM public.file
        WHERE file_id = test_file_id
          AND customer_id = alex_id
          AND application_id IS NULL
    ) THEN
        RAISE NOTICE 'PASS 3: file preserved in the customer vault.';
    ELSE
        RAISE EXCEPTION 'FAIL: file was not preserved correctly.';
    END IF;
END $$;

-- Remove all temporary test records.
ROLLBACK;