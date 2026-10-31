-- Replacing a vault document keeps the earlier version (October 2026). Each row says which file a
-- file replaced; the vault lists only the newest version. The API also creates this table on start.
CREATE TABLE IF NOT EXISTS document_version (
    file_id          UUID PRIMARY KEY REFERENCES file(file_id) ON DELETE CASCADE,
    previous_file_id UUID UNIQUE REFERENCES file(file_id) ON DELETE SET NULL,
    replaced_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
