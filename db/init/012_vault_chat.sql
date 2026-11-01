-- A chat on the vault page with no application asks about every document in the vault (October 2026).
BEGIN;
ALTER TABLE chat_conversation ALTER COLUMN application_id DROP NOT NULL;
COMMIT;
