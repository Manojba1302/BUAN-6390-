BEGIN;
-- Folders a customer adds to their vault. The built-in folders (Legal, Identification & Licenses,
-- People & Places, Finances, Taxes, Insurance & Property, Other) live in code, not here.
-- A file's folder is its file.logical_path, e.g. '/Taxes'; '/' means the usual folder for its type.
CREATE TABLE IF NOT EXISTS vault_folder (
 customer_id UUID NOT NULL REFERENCES customer(customer_id) ON DELETE CASCADE,
 name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 40),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(customer_id, name)
);
-- What a stored-only document is, in the customer's words ("Last Will"). Nothing is extracted from these.
CREATE TABLE IF NOT EXISTS vault_document_label (
 file_id UUID PRIMARY KEY REFERENCES file(file_id) ON DELETE CASCADE,
 label TEXT NOT NULL CHECK(length(label) BETWEEN 1 AND 60)
);
COMMIT;
