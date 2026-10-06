-- Apply the ownership fix as one transaction.
BEGIN;

-- Allow a file to reference an application and its customer together.
ALTER TABLE public.application
    ADD CONSTRAINT application_id_customer_id_unique
    UNIQUE (application_id, customer_id);

-- Remove the old relationship that checked only the application ID.
ALTER TABLE public.file
    DROP CONSTRAINT file_application_id_fkey;

-- Require the file and application to belong to the same customer.
-- When an application is deleted, keep the file in the customer vault.
ALTER TABLE public.file
    ADD CONSTRAINT file_application_customer_fkey
    FOREIGN KEY (application_id, customer_id)
    REFERENCES public.application (application_id, customer_id)
    ON DELETE SET NULL (application_id);

-- Save the changes.
COMMIT;