BEGIN;
CREATE TABLE IF NOT EXISTS chat_conversation (
 conversation_id UUID PRIMARY KEY,
 application_id UUID NOT NULL,
 customer_id UUID NOT NULL REFERENCES customer(customer_id) ON DELETE CASCADE,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 FOREIGN KEY(application_id, customer_id) REFERENCES application(application_id, customer_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS chat_conversation_owner ON chat_conversation(customer_id, application_id, updated_at DESC);
CREATE TABLE IF NOT EXISTS chat_turn (
 turn_id UUID PRIMARY KEY,
 conversation_id UUID NOT NULL REFERENCES chat_conversation(conversation_id) ON DELETE CASCADE,
 question TEXT NOT NULL CHECK(length(question) BETWEEN 1 AND 2000),
 reply JSONB,
 source_versions JSONB NOT NULL DEFAULT '{}',
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','completed','failed')),
 error TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS chat_turn_conversation ON chat_turn(conversation_id, created_at);
COMMIT;
