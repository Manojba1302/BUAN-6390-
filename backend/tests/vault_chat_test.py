"""Chat on the vault page with no application answers from every vault document (October 2026).

Needs the HomeFlow database (db/init applied, including 012):
    HOMEFLOW_DB_TEST=1 python -m unittest tests.vault_chat_test        (from backend/)
"""
import os
import unittest
import uuid
from unittest.mock import patch

from sqlalchemy import delete, select

from app.api.v1 import chat
from app.db.models import ChatConversation, Customer, File
from app.services import attachments
from tests import postgres_test


@unittest.skipUnless(os.getenv("HOMEFLOW_DB_TEST") == "1", "requires PostgreSQL")
class VaultChatTests(unittest.TestCase):
    setUp = postgres_test.DatabaseTests.setUp
    _file = postgres_test.DatabaseTests._file

    def tearDown(self):
        self.db.rollback()
        self.db.execute(delete(ChatConversation).where(ChatConversation.customer_id == self.customer.customer_id))
        self.db.commit()
        postgres_test.DatabaseTests.tearDown(self)

    def _vault_file(self, tag, name):
        row = self._file(tag)
        attachments.detach(self.db, row, self.app_row.application_id)
        row.original_name = name
        self.db.commit()
        return row

    def ask(self, question):
        with patch.object(chat.ollama, "embed", side_effect=AssertionError("No model needed")):
            return chat.ask(chat.Ask(question=question, application_id=None), self.db, self.customer)

    def test_no_application_lists_every_vault_document(self):
        self._vault_file("w2", "w2-2025.pdf")
        reply = self.ask("How many documents do I have?")
        self.assertIn("w2-2025.pdf", reply["answer"])
        self.assertIn("in your vault", reply["answer"])

    def test_no_application_reads_a_vault_only_document(self):
        self._vault_file("w2", "w2-2025.pdf")
        reply = self.ask("How many W-2s do I have?")
        self.assertIn("w2-2025.pdf", reply["answer"])

    def test_scope_is_the_whole_vault_but_only_this_customer(self):
        mine = self._vault_file("w2", "mine.pdf")
        other = Customer(customer_id=uuid.uuid4(), email=f"other-{uuid.uuid4()}@example.invalid")
        self.db.add(other); self.db.flush()
        theirs = File(file_id=uuid.uuid4(), customer_id=other.customer_id, document_tag="w2", original_name="theirs.pdf",
                      storage_key=f"{uuid.uuid4()}.pdf", status="completed", logical_path="/")
        self.db.add(theirs); self.db.commit()
        try:
            found = self.db.scalars(select(File.file_id).where(File.customer_id == self.customer.customer_id,
                                                                attachments.in_scope(None))).all()
            self.assertIn(mine.file_id, found)
            self.assertNotIn(theirs.file_id, found)
            self.assertNotIn(mine.file_id, self.db.scalars(select(File.file_id).where(
                attachments.in_scope(self.app_row.application_id))).all())
        finally:
            self.db.execute(delete(File).where(File.customer_id == other.customer_id))
            self.db.execute(delete(Customer).where(Customer.customer_id == other.customer_id)); self.db.commit()

    def test_a_vault_conversation_needs_no_application(self):
        made = self.client.post("/api/v1/chat/conversations", json={})
        self.assertEqual(made.status_code, 201)
        row = self.db.get(ChatConversation, uuid.UUID(made.json()["conversation_id"]))
        self.assertIsNone(row.application_id)
        self.assertEqual(self.client.get("/api/v1/chat/conversations").status_code, 200)

    def test_vault_and_application_histories_stay_apart(self):
        self.client.post("/api/v1/chat/conversations", json={})
        app_chat = self.client.post("/api/v1/chat/conversations", json={"application_id": str(self.app_row.application_id)})
        self.assertEqual(app_chat.status_code, 201)
        vault_rows = self.db.scalars(select(ChatConversation).where(ChatConversation.customer_id == self.customer.customer_id,
                                                                    ChatConversation.application_id.is_(None))).all()
        self.assertEqual(len(vault_rows), 1)

    def test_someone_elses_application_is_still_refused(self):
        reply = self.client.get(f"/api/v1/chat/conversations?application_id={uuid.uuid4()}")
        self.assertEqual(reply.status_code, 404)


if __name__ == "__main__":
    unittest.main()
