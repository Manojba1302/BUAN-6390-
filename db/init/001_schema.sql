-- =====================================================================
-- HomeFlow
-- Phase 1 schema, customer side.
--
-- Everything links through customer_id and application_id. loan_id is
-- added in phase 2 when the banker side arrives.
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ---------------------------------------------------------------------
-- People and applications
-- ---------------------------------------------------------------------
CREATE TABLE customer (
    customer_id   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    subject       TEXT UNIQUE,                    -- Keycloak subject, null in dev
    email         TEXT NOT NULL,
    first_name    TEXT,
    last_name     TEXT,
    phone         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE application (
    application_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    customer_id    UUID NOT NULL REFERENCES customer(customer_id) ON DELETE CASCADE,
    status         TEXT NOT NULL DEFAULT 'draft'
                   CHECK (status IN ('draft','submitted','in_review','changes_requested','review_complete')),
    current_step   SMALLINT NOT NULL DEFAULT 0,
    loan_purpose   TEXT,
    loan_type      TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    submitted_at   TIMESTAMPTZ
);
CREATE INDEX ON application (customer_id);

-- One row per field on the application. Keeping values here rather than
-- as columns is what lets every value carry its own provenance, and it
-- means a new field in the dictionary needs no migration.
CREATE TABLE application_field (
    application_id UUID NOT NULL REFERENCES application(application_id) ON DELETE CASCADE,
    field_name     TEXT NOT NULL,
    value          TEXT,
    source         TEXT NOT NULL DEFAULT 'user' CHECK (source IN ('user','extracted')),
    confidence     REAL,
    file_id        UUID,
    page           SMALLINT,
    evidence_quote TEXT,
    method         TEXT CHECK (method IN ('native_text','ocr','vision')),
    review_state   TEXT NOT NULL DEFAULT 'confirmed'
                   CHECK (review_state IN ('proposed','confirmed','corrected')),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (application_id, field_name)
);

-- Repeatable blocks. One table each, all keyed on the application.
CREATE TABLE employment (
    employment_id  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    application_id UUID NOT NULL REFERENCES application(application_id) ON DELETE CASCADE,
    belongs_to     TEXT NOT NULL DEFAULT 'borrower',
    employer_name  TEXT,
    position       TEXT,
    address        TEXT,
    start_date     DATE,
    end_date       DATE,
    is_current     BOOLEAN DEFAULT TRUE,
    self_employed  BOOLEAN DEFAULT FALSE,
    base           NUMERIC(12,2) DEFAULT 0,
    overtime       NUMERIC(12,2) DEFAULT 0,
    bonuses        NUMERIC(12,2) DEFAULT 0,
    commissions    NUMERIC(12,2) DEFAULT 0,
    pay_frequency  TEXT,
    source_file_id UUID,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON employment (application_id);

CREATE TABLE asset (
    asset_id       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    application_id UUID NOT NULL REFERENCES application(application_id) ON DELETE CASCADE,
    belongs_to     TEXT NOT NULL DEFAULT 'borrower',
    asset_type     TEXT,
    institution    TEXT,
    account_mask   TEXT,
    balance        NUMERIC(14,2) DEFAULT 0,
    as_of          DATE,
    source_file_id UUID,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Three statements for one account are ONE asset, never three.
    UNIQUE (application_id, institution, account_mask)
);
CREATE INDEX ON asset (application_id);

CREATE TABLE liability (
    liability_id   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    application_id UUID NOT NULL REFERENCES application(application_id) ON DELETE CASCADE,
    belongs_to     TEXT NOT NULL DEFAULT 'borrower',
    liability_type TEXT,
    creditor       TEXT,
    balance        NUMERIC(14,2) DEFAULT 0,
    monthly_payment NUMERIC(12,2) DEFAULT 0,
    months_left    INTEGER,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON liability (application_id);

CREATE TABLE declaration (
    application_id UUID NOT NULL REFERENCES application(application_id) ON DELETE CASCADE,
    code           TEXT NOT NULL,
    answer         TEXT CHECK (answer IN ('yes','no')),
    comment        TEXT,
    PRIMARY KEY (application_id, code)
);

-- ---------------------------------------------------------------------
-- Files. One flat physical store, a unique id per file. Any folder tree
-- the customer sees is logical_path in this table and nothing else.
-- ---------------------------------------------------------------------
CREATE TABLE file (
    file_id        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    customer_id    UUID NOT NULL REFERENCES customer(customer_id) ON DELETE CASCADE,
    application_id UUID REFERENCES application(application_id) ON DELETE SET NULL,
    document_tag   TEXT NOT NULL,           -- what the customer said it is
    original_name  TEXT NOT NULL,
    content_type   TEXT,
    size_bytes     BIGINT,
    checksum       TEXT,                    -- catches a duplicate upload
    storage_key    TEXT NOT NULL,           -- object key, flat
    logical_path   TEXT DEFAULT '/',        -- the vault tree, database only
    page_count     SMALLINT,
    status         TEXT NOT NULL DEFAULT 'uploaded'
                   CHECK (status IN ('uploaded','queued','processing','completed','failed')),
    error_detail   TEXT,
    attempts       SMALLINT NOT NULL DEFAULT 0,
    uploaded_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at   TIMESTAMPTZ
);
CREATE INDEX ON file (customer_id);
CREATE INDEX ON file (application_id);
CREATE INDEX ON file (checksum);

-- Stage 2 classification. Stage 1 is advisory and never persisted.
CREATE TABLE file_classification (
    file_id        UUID PRIMARY KEY REFERENCES file(file_id) ON DELETE CASCADE,
    selected_type  TEXT NOT NULL,           -- what the customer chose
    detected_type  TEXT NOT NULL,           -- what the model decided
    outcome        TEXT NOT NULL CHECK (outcome IN ('matched','mismatched','unknown','unreadable','failed')),
    evidence       JSONB NOT NULL DEFAULT '[]'::jsonb,
    mixed_document BOOLEAN NOT NULL DEFAULT FALSE,
    model_name     TEXT,
    user_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
    classified_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Every extracted value carries where it came from.
CREATE TABLE extraction (
    extraction_id  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    file_id        UUID NOT NULL REFERENCES file(file_id) ON DELETE CASCADE,
    field_name     TEXT NOT NULL,
    value_raw      TEXT,
    value_normalized TEXT,
    page           SMALLINT,
    evidence_quote TEXT,
    bbox           JSONB,
    method         TEXT CHECK (method IN ('native_text','ocr','vision')),
    review_state   TEXT NOT NULL DEFAULT 'proposed'
                   CHECK (review_state IN ('proposed','confirmed','corrected')),
    corrected_value TEXT,
    model_name     TEXT,
    extracted_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON extraction (file_id);

CREATE TABLE document_markdown (
    file_id      UUID PRIMARY KEY REFERENCES file(file_id) ON DELETE CASCADE,
    markdown_path TEXT NOT NULL,
    char_count   INTEGER,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- RAG store. 768 dimensions matches nomic-embed-text.
CREATE TABLE document_chunk (
    chunk_id     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    file_id      UUID NOT NULL REFERENCES file(file_id) ON DELETE CASCADE,
    customer_id  UUID NOT NULL REFERENCES customer(customer_id) ON DELETE CASCADE,
    chunk_index  INTEGER NOT NULL,
    page         SMALLINT,
    content      TEXT NOT NULL,
    embedding    vector(768),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON document_chunk (customer_id);
CREATE INDEX document_chunk_embedding_idx ON document_chunk
    USING hnsw (embedding vector_cosine_ops);

CREATE TABLE audit_event (
    event_id       BIGSERIAL PRIMARY KEY,
    customer_id    UUID,
    application_id UUID,
    file_id        UUID,
    actor          TEXT NOT NULL DEFAULT 'customer',
    action         TEXT NOT NULL,
    payload        JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON audit_event (application_id);
CREATE INDEX ON audit_event (occurred_at DESC);

-- Which document types an application must supply, and how many.
-- Configuration, not a number buried in the interface.
CREATE TABLE checklist_requirement (
    document_tag   TEXT PRIMARY KEY,
    display_name   TEXT NOT NULL,
    required_count SMALLINT NOT NULL DEFAULT 1,
    guidance       TEXT,
    sort_order     SMALLINT NOT NULL DEFAULT 0
);

INSERT INTO checklist_requirement (document_tag, display_name, required_count, guidance, sort_order) VALUES
 ('paystub',          'Pay stub',             2, 'Your two most recent pay stubs',          1),
 ('w2',               'W-2',                  2, 'W-2s for the two most recent tax years',          2),
 ('bank_statement',   'Bank statement',       2, 'Two months for each account you are using',3),
 ('drivers_license',  'Driver''s license',    1, 'Front of your current licence',           4),
 ('ssn_card',         'Social Security card', 1, 'A clear photo of the card',               5);

CREATE OR REPLACE FUNCTION touch_application() RETURNS trigger AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER application_touch BEFORE UPDATE ON application
FOR EACH ROW EXECUTE FUNCTION touch_application();

