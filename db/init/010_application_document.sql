-- One vault document can be attached to several applications (October 2026).
-- file.application_id keeps the latest attachment for the worker and older code.
-- The API also creates this table and copies existing links on start, for older databases.
CREATE TABLE IF NOT EXISTS application_document (
    application_id UUID NOT NULL REFERENCES application(application_id) ON DELETE CASCADE,
    file_id        UUID NOT NULL REFERENCES file(file_id) ON DELETE CASCADE,
    attached_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (application_id, file_id)
);
CREATE INDEX IF NOT EXISTS application_document_file_idx ON application_document (file_id);

-- Code that sets file.application_id directly (older code, the team's tests) keeps the links in step:
-- setting it adds that link; changing or clearing it removes the link to the application it pointed at.
CREATE OR REPLACE FUNCTION link_file_application() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    -- Changing file.application_id directly means "moved" (older code) unless the attach step
    -- has said in this transaction that the other applications keep the document.
    IF TG_OP = 'UPDATE' AND OLD.application_id IS NOT NULL
       AND OLD.application_id IS DISTINCT FROM NEW.application_id
       AND coalesce(current_setting('homeflow.keep_links', true), '') <> 'on' THEN
        DELETE FROM application_document
         WHERE application_id = OLD.application_id AND file_id = NEW.file_id;
    END IF;
    IF NEW.application_id IS NOT NULL THEN
        INSERT INTO application_document (application_id, file_id)
        VALUES (NEW.application_id, NEW.file_id) ON CONFLICT DO NOTHING;
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS file_application_link ON file;
CREATE TRIGGER file_application_link AFTER INSERT OR UPDATE OF application_id ON file
    FOR EACH ROW EXECUTE FUNCTION link_file_application();

INSERT INTO application_document (application_id, file_id)
SELECT application_id, file_id FROM file WHERE application_id IS NOT NULL
ON CONFLICT DO NOTHING;
