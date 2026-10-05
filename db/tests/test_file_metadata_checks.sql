
-- Test metadata rules without keeping any test records.
BEGIN;

DO $$
DECLARE
    test_customer_id UUID;
    test_file_id UUID;
    field_to_test TEXT;
    blocked_constraint TEXT;
BEGIN
    -- Create a fictional customer.
    INSERT INTO public.customer (email)
    VALUES ('metadata-test@example.invalid')
    RETURNING customer_id INTO test_customer_id;

    -- Test 1: unknown size and page count are allowed.
    INSERT INTO public.file (
        customer_id, document_tag, original_name, storage_key,
        size_bytes, page_count, attempts
    )
    VALUES (
        test_customer_id, 'bank_statement',
        'metadata_test.pdf', 'metadata_test.pdf',
        NULL, NULL, 0
    )
    RETURNING file_id INTO test_file_id;

    RAISE NOTICE 'PASS 1: unknown metadata accepted.';

    -- Test 2: zero values are allowed.
    UPDATE public.file
    SET size_bytes = 0, page_count = 0, attempts = 0
    WHERE file_id = test_file_id;

    RAISE NOTICE 'PASS 2: zero values accepted.';

    -- Test 3: positive values are allowed.
    UPDATE public.file
    SET size_bytes = 1024, page_count = 1, attempts = 1
    WHERE file_id = test_file_id;

    RAISE NOTICE 'PASS 3: positive values accepted.';

    -- Test each negative value separately.
    FOREACH field_to_test IN ARRAY
        ARRAY['size_bytes', 'page_count', 'attempts']
    LOOP
        BEGIN
            EXECUTE format(
                'UPDATE public.file SET %I = -1 WHERE file_id = $1',
                field_to_test
            ) USING test_file_id;

            RAISE EXCEPTION 'FAIL: negative % accepted.', field_to_test;
        EXCEPTION
            WHEN check_violation THEN
                GET STACKED DIAGNOSTICS
                    blocked_constraint = CONSTRAINT_NAME;

                IF blocked_constraint <>
                    'file_' || field_to_test || '_nonnegative' THEN
                    RAISE;
                END IF;

                RAISE NOTICE 'PASS: negative % blocked.', field_to_test;
        END;
    END LOOP;
END $$;

-- Remove all temporary test records.
ROLLBACK;