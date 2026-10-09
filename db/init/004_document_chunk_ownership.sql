-- Require each document chunk to have the same owner as its source file.
BEGIN;

-- Allow the file and its customer to be referenced together.
ALTER TABLE public.file
ADD CONSTRAINT file_id_customer_id_unique
UNIQUE (file_id, customer_id);

-- Check chunk ownership and delete chunks when their file is deleted.
ALTER TABLE public.document_chunk
DROP CONSTRAINT document_chunk_file_id_fkey,
ADD CONSTRAINT document_chunk_file_customer_fkey
FOREIGN KEY (file_id, customer_id)
REFERENCES public.file (file_id, customer_id)
ON DELETE CASCADE;

COMMIT;