-- Keep all test records temporary.
BEGIN;

DO $$
DECLARE
    customer_a UUID;
    customer_b UUID;
    application_a UUID;
    application_b UUID;
    file_a UUID;
    file_b UUID;
    missing_file UUID := uuid_generate_v4();
    detail RECORD;
    actual_customer UUID;
    record_count INTEGER;
    failed_constraint TEXT;
BEGIN
    -- Create two separate customers.
    INSERT INTO public.customer (email)
    VALUES ('owner-a-' || uuid_generate_v4()::text || '@example.test')
    RETURNING customer_id INTO customer_a;

    INSERT INTO public.customer (email)
    VALUES ('owner-b-' || uuid_generate_v4()::text || '@example.test')
    RETURNING customer_id INTO customer_b;

    -- Create one application for each customer.
    INSERT INTO public.application (customer_id)
    VALUES (customer_a)
    RETURNING application_id INTO application_a;

    INSERT INTO public.application (customer_id)
    VALUES (customer_b)
    RETURNING application_id INTO application_b;

    -- Create vault files without application links.
    INSERT INTO public.file (
        customer_id, document_tag, original_name, storage_key
    )
    VALUES (
        customer_a, 'bank_statement', 'owner_a.pdf',
        'tests/' || uuid_generate_v4()::text
    )
    RETURNING file_id INTO file_a;

    INSERT INTO public.file (
        customer_id, document_tag, original_name, storage_key
    )
    VALUES (
        customer_b, 'bank_statement', 'owner_b.pdf',
        'tests/' || uuid_generate_v4()::text
    )
    RETURNING file_id INTO file_b;

    -- Insert details without supplying customer_id, as the backend does.
    INSERT INTO public.application_field (
        application_id, field_name, value, file_id
    )
    VALUES (application_a, 'ownership_test', 'Test value', file_a);

    INSERT INTO public.employment (
        application_id, employer_name, source_file_id
    )
    VALUES (application_a, 'Fictional Employer', file_a);

    INSERT INTO public.asset (
        application_id, institution, source_file_id
    )
    VALUES (application_a, 'Fictional Bank', file_a);

    -- Run the same checks for all three detail tables.
    FOR detail IN
        SELECT *
        FROM (
            VALUES
                ('application_field', 'file_id'),
                ('employment', 'source_file_id'),
                ('asset', 'source_file_id')
        ) AS test_tables(table_name, source_column)
    LOOP
        -- Confirm the trigger filled in the application's customer.
        EXECUTE format(
            'SELECT customer_id FROM public.%I
             WHERE application_id = $1',
            detail.table_name
        )
        INTO actual_customer
        USING application_a;

        IF actual_customer IS DISTINCT FROM customer_a THEN
            RAISE EXCEPTION 'FAIL: % automatic ownership',
                detail.table_name;
        END IF;
        RAISE NOTICE 'PASS: % automatic ownership',
            detail.table_name;

        -- Reject a source file owned by another customer.
        BEGIN
            EXECUTE format(
                'UPDATE public.%I SET %I = $1
                 WHERE application_id = $2',
                detail.table_name, detail.source_column
            )
            USING file_b, application_a;

            RAISE EXCEPTION 'FAIL: % accepted another customer file',
                detail.table_name;
        EXCEPTION
            WHEN foreign_key_violation THEN
                GET STACKED DIAGNOSTICS
                    failed_constraint = CONSTRAINT_NAME;
                IF failed_constraint <>
                    detail.table_name || '_source_file_customer_fkey'
                THEN
                    RAISE;
                END IF;
                RAISE NOTICE 'PASS: % blocked another customer file',
                    detail.table_name;
        END;

        -- Confirm nonexistent source files are still rejected.
        BEGIN
            EXECUTE format(
                'UPDATE public.%I SET %I = $1
                 WHERE application_id = $2',
                detail.table_name, detail.source_column
            )
            USING missing_file, application_a;

            RAISE EXCEPTION 'FAIL: % accepted a nonexistent file',
                detail.table_name;
        EXCEPTION
            WHEN foreign_key_violation THEN
                GET STACKED DIAGNOSTICS
                    failed_constraint = CONSTRAINT_NAME;
                IF failed_constraint <>
                    detail.table_name || '_source_file_customer_fkey'
                THEN
                    RAISE;
                END IF;
                RAISE NOTICE 'PASS: % blocked a nonexistent file',
                    detail.table_name;
        END;

        -- Moving the detail to another customer's application must fail
        -- while its original source file remains linked.
        BEGIN
            EXECUTE format(
                'UPDATE public.%I SET application_id = $1
                 WHERE application_id = $2',
                detail.table_name
            )
            USING application_b, application_a;

            RAISE EXCEPTION 'FAIL: % allowed an incompatible application',
                detail.table_name;
        EXCEPTION
            WHEN foreign_key_violation THEN
                GET STACKED DIAGNOSTICS
                    failed_constraint = CONSTRAINT_NAME;
                IF failed_constraint <>
                    detail.table_name || '_source_file_customer_fkey'
                THEN
                    RAISE;
                END IF;
                RAISE NOTICE 'PASS: % blocked an incompatible application',
                    detail.table_name;
        END;
    END LOOP;

    -- Changing the source file's owner must also be blocked.
    BEGIN
        UPDATE public.file
        SET customer_id = customer_b
        WHERE file_id = file_a;

        RAISE EXCEPTION 'FAIL: referenced file owner was changed';
    EXCEPTION
        WHEN foreign_key_violation THEN
            RAISE NOTICE 'PASS: referenced file owner change blocked';
    END;

    -- Changing the application's owner must also be blocked.
    BEGIN
        UPDATE public.application
        SET customer_id = customer_b
        WHERE application_id = application_a;

        RAISE EXCEPTION 'FAIL: referenced application owner was changed';
    EXCEPTION
        WHEN foreign_key_violation THEN
            RAISE NOTICE 'PASS: referenced application owner change blocked';
    END;

    -- Delete the source file; retain all three detail records.
    DELETE FROM public.file WHERE file_id = file_a;

    FOR detail IN
        SELECT *
        FROM (
            VALUES
                ('application_field', 'file_id'),
                ('employment', 'source_file_id'),
                ('asset', 'source_file_id')
        ) AS test_tables(table_name, source_column)
    LOOP
        EXECUTE format(
            'SELECT COUNT(*) FROM public.%I
             WHERE application_id = $1
               AND customer_id = $2
               AND %I IS NULL',
            detail.table_name, detail.source_column
        )
        INTO record_count
        USING application_a, customer_a;

        IF record_count <> 1 THEN
            RAISE EXCEPTION 'FAIL: % was not preserved after file deletion',
                detail.table_name;
        END IF;
        RAISE NOTICE 'PASS: % preserved after file deletion',
            detail.table_name;
    END LOOP;

    -- Confirm the original application-delete cascade still works.
    DELETE FROM public.application
    WHERE application_id = application_a;

    SELECT COUNT(*) INTO record_count
    FROM (
        SELECT application_id FROM public.application_field
        UNION ALL
        SELECT application_id FROM public.employment
        UNION ALL
        SELECT application_id FROM public.asset
    ) AS remaining_details
    WHERE application_id = application_a;

    IF record_count <> 0 THEN
        RAISE EXCEPTION 'FAIL: application deletion left detail records';
    END IF;
    RAISE NOTICE 'PASS: application deletion removed its detail records';
END;
$$;

-- Remove all fictional test records.
ROLLBACK;