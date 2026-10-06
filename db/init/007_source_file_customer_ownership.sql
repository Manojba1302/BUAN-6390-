-- Apply the ownership rules together.
BEGIN;

-- Prevent records changing while existing ownership is populated.
LOCK TABLE
    public.application,
    public.file,
    public.application_field,
    public.employment,
    public.asset
IN ACCESS EXCLUSIVE MODE;

-- Automatically derive the customer from the parent application.
CREATE FUNCTION public.set_application_detail_customer()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    application_customer UUID;
BEGIN
    SELECT customer_id
    INTO application_customer
    FROM public.application
    WHERE application_id = NEW.application_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'The parent application does not exist.'
            USING ERRCODE = '23503';
    END IF;

    NEW.customer_id := application_customer;
    RETURN NEW;
END;
$$;

-- Apply the same ownership structure to each detail table.
DO $$
DECLARE
    detail RECORD;
BEGIN
    FOR detail IN
        SELECT *
        FROM (
            VALUES
                ('application_field', 'file_id'),
                ('employment', 'source_file_id'),
                ('asset', 'source_file_id')
        ) AS tables_to_update(table_name, source_column)
    LOOP
        -- Add a customer column for composite foreign keys.
        EXECUTE format(
            'ALTER TABLE public.%I ADD COLUMN customer_id UUID',
            detail.table_name
        );

        -- Populate existing records using their application owner.
        EXECUTE format(
            'UPDATE public.%I AS detail
             SET customer_id = app.customer_id
             FROM public.application AS app
             WHERE detail.application_id = app.application_id',
            detail.table_name
        );

        -- Every detail record must have a customer.
        EXECUTE format(
            'ALTER TABLE public.%I
             ALTER COLUMN customer_id SET NOT NULL',
            detail.table_name
        );

        -- Keep customer ownership automatic for backend writes.
        EXECUTE format(
            'CREATE TRIGGER set_detail_customer
             BEFORE INSERT OR UPDATE ON public.%I
             FOR EACH ROW
             EXECUTE FUNCTION public.set_application_detail_customer()',
            detail.table_name
        );

        -- Require the detail and application to have the same customer.
        EXECUTE format(
            'ALTER TABLE public.%I
             ADD CONSTRAINT %I
             FOREIGN KEY (application_id, customer_id)
             REFERENCES public.application (application_id, customer_id)',
            detail.table_name,
            detail.table_name || '_application_customer_fkey'
        );

        -- Replace the existence-only source-file rule from migration 006.
        EXECUTE format(
            'ALTER TABLE public.%I DROP CONSTRAINT %I',
            detail.table_name,
            detail.table_name || '_source_file_fkey'
        );

        -- Require the source file to belong to the application's customer.
        -- Deleting a file clears only its reference, preserving the detail.
        EXECUTE format(
            'ALTER TABLE public.%I
             ADD CONSTRAINT %I
             FOREIGN KEY (%I, customer_id)
             REFERENCES public.file (file_id, customer_id)
             ON DELETE SET NULL (%I)',
            detail.table_name,
            detail.table_name || '_source_file_customer_fkey',
            detail.source_column,
            detail.source_column
        );
    END LOOP;
END;
$$;

-- Save all changes.
COMMIT;