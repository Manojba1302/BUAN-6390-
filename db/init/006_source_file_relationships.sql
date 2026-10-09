-- Add all three source-file relationships together.
BEGIN;

-- Connect an application field to its supporting document.
ALTER TABLE public.application_field
    ADD CONSTRAINT application_field_source_file_fkey
    FOREIGN KEY (file_id)
    REFERENCES public.file (file_id)
    ON DELETE SET NULL;

-- Connect employment information to its supporting document.
ALTER TABLE public.employment
    ADD CONSTRAINT employment_source_file_fkey
    FOREIGN KEY (source_file_id)
    REFERENCES public.file (file_id)
    ON DELETE SET NULL;

-- Connect asset information to its supporting document.
ALTER TABLE public.asset
    ADD CONSTRAINT asset_source_file_fkey
    FOREIGN KEY (source_file_id)
    REFERENCES public.file (file_id)
    ON DELETE SET NULL;

-- Save the relationship rules.
COMMIT;
