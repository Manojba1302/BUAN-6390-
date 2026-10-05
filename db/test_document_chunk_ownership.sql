
-- Test the chunk ownership rule using temporary records.
BEGIN;

DO $$
DECLARE
    alex_id UUID;
    priya_id UUID;
    test_file_id UUID;
    test_chunk_id UUID;
    blocked_constraint TEXT;
BEGIN
    -- Create two fictional customers.
    INSERT INTO public.customer (email)
    VALUES ('alex@example.invalid')
    RETURNING customer_id INTO alex_id;

    INSERT INTO public.customer (email)
    VALUES ('priya@example.invalid')
    RETURNING customer_id INTO priya_id;

    -- Create a file owned by Alex in his vault.
    INSERT INTO public.file (
        customer_id, document_tag, original_name, storage_key
    )
    VALUES (
        alex_id, 'bank_statement', 'test.pdf', 'chunk_test.pdf'
    )
    RETURNING file_id INTO test_file_id;

    -- Test 1: accept Alex's chunk from Alex's file.
    INSERT INTO public.document_chunk (
        file_id, customer_id, chunk_index, content
    )
    VALUES (
        test_file_id, alex_id, 0, 'Fictional test content.'
    )
    RETURNING chunk_id INTO test_chunk_id;

    RAISE NOTICE 'PASS 1: correct chunk ownership accepted.';

    -- Test 2: reject assigning the chunk to Priya.
    BEGIN
        UPDATE public.document_chunk
        SET customer_id = priya_id
        WHERE chunk_id = test_chunk_id;

        RAISE EXCEPTION 'FAIL: incorrect chunk ownership accepted.';
    EXCEPTION
        WHEN foreign_key_violation THEN
            GET STACKED DIAGNOSTICS
                blocked_constraint = CONSTRAINT_NAME;

            IF blocked_constraint <> 'document_chunk_file_customer_fkey' THEN
                RAISE;
            END IF;

            RAISE NOTICE 'PASS 2: incorrect chunk ownership blocked.';
    END;

    -- Test 3: deleting the file must remove its chunk.
    DELETE FROM public.file
    WHERE file_id = test_file_id;

    IF NOT EXISTS (
        SELECT 1
        FROM public.document_chunk
        WHERE chunk_id = test_chunk_id
    ) THEN
        RAISE NOTICE 'PASS 3: deleting the file removed its chunk.';
    ELSEare
        RAISE EXCEPTION 'FAIL: chunk remained after file deletion.';
    END IF;
END $$;

-- Remove all temporary test records.
ROLLBACK;