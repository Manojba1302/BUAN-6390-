-- Keep all test records inside a transaction.
BEGIN;

DO $$
DECLARE
    test_customer UUID;
    test_application UUID;
    test_file UUID;
    missing_file UUID := uuid_generate_v4();
    test_employment UUID;
    test_asset UUID;
    failed_constraint TEXT;
BEGIN
    -- Create a fictional customer and application.
    INSERT INTO public.customer (email)
    VALUES ('source-test-' || uuid_generate_v4()::text || '@example.test')
    RETURNING customer_id INTO test_customer;

    INSERT INTO public.application (customer_id)
    VALUES (test_customer)
    RETURNING application_id INTO test_application;

    -- Create a supporting document owned by that customer.
    INSERT INTO public.file (
        customer_id, application_id, document_tag,
        original_name, storage_key
    )
    VALUES (
        test_customer, test_application, 'bank_statement',
        'relationship_test.pdf',
        'tests/' || uuid_generate_v4()::text || '.pdf'
    )
    RETURNING file_id INTO test_file;

    -- Verify that all three tables accept an existing source file.
    INSERT INTO public.application_field (
        application_id, field_name, value, file_id
    )
    VALUES (
        test_application, 'relationship_test', 'Test value', test_file
    );

    INSERT INTO public.employment (
        application_id, employer_name, source_file_id
    )
    VALUES (
        test_application, 'Fictional Employer', test_file
    )
    RETURNING employment_id INTO test_employment;

    INSERT INTO public.asset (
        application_id, institution, source_file_id
    )
    VALUES (
        test_application, 'Fictional Bank', test_file
    )
    RETURNING asset_id INTO test_asset;

    RAISE NOTICE 'PASS 1: all three tables accepted an existing source file.';

    -- Verify that an application field rejects a nonexistent file.
    BEGIN
        UPDATE public.application_field
        SET file_id = missing_file
        WHERE application_id = test_application
          AND field_name = 'relationship_test';

        RAISE EXCEPTION 'FAIL: application field accepted a nonexistent file.';
    EXCEPTION
        WHEN foreign_key_violation THEN
            GET STACKED DIAGNOSTICS
                failed_constraint = CONSTRAINT_NAME;
            IF failed_constraint <> 'application_field_source_file_fkey' THEN
                RAISE;
            END IF;
            RAISE NOTICE 'PASS 2: application field rejected a nonexistent file.';
    END;

    -- Verify that employment rejects a nonexistent file.
    BEGIN
        UPDATE public.employment
        SET source_file_id = missing_file
        WHERE employment_id = test_employment;

        RAISE EXCEPTION 'FAIL: employment accepted a nonexistent file.';
    EXCEPTION
        WHEN foreign_key_violation THEN
            GET STACKED DIAGNOSTICS
                failed_constraint = CONSTRAINT_NAME;
            IF failed_constraint <> 'employment_source_file_fkey' THEN
                RAISE;
            END IF;
            RAISE NOTICE 'PASS 3: employment rejected a nonexistent file.';
    END;

    -- Verify that an asset rejects a nonexistent file.
    BEGIN
        UPDATE public.asset
        SET source_file_id = missing_file
        WHERE asset_id = test_asset;

        RAISE EXCEPTION 'FAIL: asset accepted a nonexistent file.';
    EXCEPTION
        WHEN foreign_key_violation THEN
            GET STACKED DIAGNOSTICS
                failed_constraint = CONSTRAINT_NAME;
            IF failed_constraint <> 'asset_source_file_fkey' THEN
                RAISE;
            END IF;
            RAISE NOTICE 'PASS 4: asset rejected a nonexistent file.';
    END;

    -- Delete the supporting file to check preservation of information.
    DELETE FROM public.file
    WHERE file_id = test_file;

    -- The application field must remain with its value and no file link.
    IF NOT EXISTS (
        SELECT 1
        FROM public.application_field
        WHERE application_id = test_application
          AND field_name = 'relationship_test'
          AND value = 'Test value'
          AND file_id IS NULL
    ) THEN
        RAISE EXCEPTION 'FAIL: application field was not preserved correctly.';
    END IF;
    RAISE NOTICE 'PASS 5: application field preserved; source link cleared.';

    -- Employment information must remain with no file link.
    IF NOT EXISTS (
        SELECT 1
        FROM public.employment
        WHERE employment_id = test_employment
          AND employer_name = 'Fictional Employer'
          AND source_file_id IS NULL
    ) THEN
        RAISE EXCEPTION 'FAIL: employment was not preserved correctly.';
    END IF;
    RAISE NOTICE 'PASS 6: employment preserved; source link cleared.';

    -- Asset information must remain with no file link.
    IF NOT EXISTS (
        SELECT 1
        FROM public.asset
        WHERE asset_id = test_asset
          AND institution = 'Fictional Bank'
          AND source_file_id IS NULL
    ) THEN
        RAISE EXCEPTION 'FAIL: asset was not preserved correctly.';
    END IF;
    RAISE NOTICE 'PASS 7: asset preserved; source link cleared.';
END;
$$;

-- Remove every temporary record created by this test.
ROLLBACK;