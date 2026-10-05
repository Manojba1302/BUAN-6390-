-- Prevent negative file sizes, page counts, and processing attempts.
BEGIN;

ALTER TABLE public.file
    -- File size cannot be negative.
    ADD CONSTRAINT file_size_bytes_nonnegative
        CHECK (size_bytes >= 0),

    -- Page count cannot be negative.
    ADD CONSTRAINT file_page_count_nonnegative
        CHECK (page_count >= 0),

    -- Processing attempts cannot be negative.
    ADD CONSTRAINT file_attempts_nonnegative
        CHECK (attempts >= 0);

-- Save the database rules.
COMMIT;