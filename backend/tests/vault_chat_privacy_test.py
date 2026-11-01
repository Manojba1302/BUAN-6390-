"""Vault chat privacy (October 2026): two customers, each with vault documents, an application and conversations.

What must hold now that a chat can run with no application:
  * a customer's vault chat never sees another customer's documents, text or fields;
  * another customer's conversations and applications cannot be opened, listed, used or deleted;
  * vault conversations and application conversations are listed apart;
  * an application chat still sees only that application's documents.

    HOMEFLOW_DB_TEST=1 python -m unittest tests.vault_chat_privacy_test        (from backend/)
"""
import os
import unittest
import uuid
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import delete, text

from app.api.v1 import chat
from app.core.security import current_customer
from app.db.models import Application, ChatConversation, ChatTurn, Customer, Extraction, File
from app.main import app
from app.services import attachments, chat_evidence, chat_history
from tests import postgres_test


@unittest.skipUnless(os.getenv("HOMEFLOW_DB_TEST") == "1", "requires PostgreSQL")
class VaultChatPrivacyTests(unittest.TestCase):
    _file = postgres_test.DatabaseTests._file

    def setUp(self):
        postgres_test.DatabaseTests.setUp(self)          # customer A, A's application, client signed in as A
        self.other = Customer(customer_id=uuid.uuid4(), email=f"other-{uuid.uuid4()}@example.invalid")
        self.db.add(self.other); self.db.flush()
        self.other_app = Application(application_id=uuid.uuid4(), customer_id=self.other.customer_id, status="draft")
        self.db.add(self.other_app); self.db.flush()
        self.secret = File(file_id=uuid.uuid4(), customer_id=self.other.customer_id, document_tag="w2",
                           original_name="bravo-secret-w2.pdf", storage_key=f"{uuid.uuid4()}.pdf",
                           status="completed", logical_path="/Taxes")
        self.db.add(self.secret); self.db.flush()
        self.db.add(Extraction(file_id=self.secret.file_id, field_name="employer_name", value_raw="Bravo Secret Corp",
                               value_normalized="Bravo Secret Corp", method="native_text"))
        self.db.execute(text("INSERT INTO document_chunk(file_id,customer_id,chunk_index,page,content) "
                             "VALUES(:f,:c,0,1,'Bravo Secret Corp pays a salary of 999999')"),
                        {"f": self.secret.file_id, "c": self.other.customer_id})
        self.other_chat = ChatConversation(application_id=None, customer_id=self.other.customer_id)
        self.db.add(self.other_chat); self.db.flush()
        self.db.add(ChatTurn(conversation_id=self.other_chat.conversation_id, question="What is my salary?", status="completed",
                             reply={"answer": "999999", "citations": [], "evidence": []}))
        self.db.commit()

    def tearDown(self):
        self.db.rollback()
        for owner in (self.customer.customer_id, self.other.customer_id):
            self.db.execute(delete(ChatConversation).where(ChatConversation.customer_id == owner))
        self.db.execute(text("DELETE FROM document_chunk WHERE customer_id = :c"), {"c": self.other.customer_id})
        self.db.execute(delete(File).where(File.customer_id == self.other.customer_id))
        self.db.execute(delete(Application).where(Application.customer_id == self.other.customer_id))
        self.db.execute(delete(Customer).where(Customer.customer_id == self.other.customer_id))
        self.db.commit()
        postgres_test.DatabaseTests.tearDown(self)

    # helpers
    def ask(self, question, application_id=None):
        with patch.object(chat.ollama, "embed", side_effect=AssertionError("No model needed")):
            return chat.ask(chat.Ask(question=question, application_id=application_id), self.db, self.customer)

    def _vault_file(self, tag, name):
        row = self._file(tag)
        attachments.detach(self.db, row, self.app_row.application_id)
        row.original_name = name
        self.db.commit()
        return row

    def _conversation(self, application_id, question):
        row = ChatConversation(application_id=application_id, customer_id=self.customer.customer_id)
        self.db.add(row); self.db.flush()
        self.db.add(ChatTurn(conversation_id=row.conversation_id, question=question, status="completed",
                             reply={"answer": "ok", "citations": [], "evidence": []}))
        self.db.commit()
        return str(row.conversation_id)

    # documents stay with their owner
    def test_vault_chat_never_lists_someone_elses_documents(self):
        self._vault_file("paystub", "my-paystub.pdf")
        answer = self.ask("How many documents do I have?")["answer"]
        self.assertIn("my-paystub.pdf", answer)
        self.assertNotIn("bravo-secret-w2.pdf", answer)

    def test_vault_chat_never_reads_someone_elses_fields(self):
        reply = self.ask("Who is the employer on my W-2?")
        self.assertNotIn("Bravo", str(reply))

    def test_vault_search_never_returns_someone_elses_text(self):
        found = chat_evidence.retrieve(self.db, self.customer, None, "Bravo Secret Corp salary 999999")
        self.assertFalse(any("Bravo" in str(p.get("content", "")) for p in found))
        theirs = chat_evidence.retrieve(self.db, self.other, None, "Bravo Secret Corp salary 999999")
        self.assertTrue(any("Bravo" in str(p.get("content", "")) for p in theirs))   # the search itself works

    def test_saved_sources_from_someone_else_show_unavailable(self):
        status = chat_history.source_status(self.db, self.customer, None, {str(self.secret.file_id): "anything"})
        self.assertEqual(status, {str(self.secret.file_id): "unavailable"})

    # conversations stay with their owner
    def test_someone_elses_vault_conversation_cannot_be_opened_used_or_deleted(self):
        other = str(self.other_chat.conversation_id)
        self.assertEqual(self.client.get(f"/api/v1/chat/conversations/{other}").status_code, 404)
        self.assertEqual(self.client.post(f"/api/v1/chat/conversations/{other}/messages", json={"question": "salary?"}).status_code, 404)
        self.assertEqual(self.client.post(f"/api/v1/chat/conversations/{other}/end", json={}).status_code, 404)
        self.assertEqual(self.client.post(f"/api/v1/chat/conversations/{other}/resume", json={}).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/v1/chat/conversations/{other}").status_code, 404)
        self.db.expire_all()
        self.assertIsNotNone(self.db.get(ChatConversation, self.other_chat.conversation_id))

    def test_vault_listing_shows_only_my_conversations(self):
        mine = self._conversation(None, "How many documents do I have?")
        listed = [c["conversation_id"] for c in self.client.get("/api/v1/chat/conversations").json()]
        self.assertEqual(listed, [mine])

    def test_someone_elses_application_cannot_be_used(self):
        other_app = str(self.other_app.application_id)
        self.assertEqual(self.client.post("/api/v1/chat/conversations", json={"application_id": other_app}).status_code, 404)
        self.assertEqual(self.client.get(f"/api/v1/chat/conversations?application_id={other_app}").status_code, 404)
        with self.assertRaises(HTTPException) as raised:
            self.ask("How many documents do I have?", self.other_app.application_id)
        self.assertEqual(raised.exception.status_code, 404)

    # vault and application chats stay apart
    def test_vault_and_application_conversations_are_listed_apart(self):
        vault = self._conversation(None, "Vault question")
        in_app = self._conversation(self.app_row.application_id, "Application question")
        vault_list = [c["conversation_id"] for c in self.client.get("/api/v1/chat/conversations").json()]
        app_list = [c["conversation_id"] for c in self.client.get(
            f"/api/v1/chat/conversations?application_id={self.app_row.application_id}").json()]
        self.assertEqual(vault_list, [vault])
        self.assertEqual(app_list, [in_app])

    def test_application_chat_sees_only_its_documents(self):
        self._vault_file("paystub", "vault-only.pdf")
        attached = self._file("w2"); attached.original_name = "in-the-application.pdf"; self.db.commit()
        in_app = self.ask("How many documents do I have?", self.app_row.application_id)["answer"]
        self.assertIn("in-the-application.pdf", in_app)
        self.assertNotIn("vault-only.pdf", in_app)
        whole = self.ask("How many documents do I have?")["answer"]
        self.assertIn("in-the-application.pdf", whole)
        self.assertIn("vault-only.pdf", whole)

    def test_a_vault_conversation_keeps_the_vault_scope(self):
        made = self.client.post("/api/v1/chat/conversations", json={}).json()["conversation_id"]
        self.assertIsNone(self.db.get(ChatConversation, uuid.UUID(made)).application_id)
        row = self.client.post("/api/v1/chat/conversations", json={"application_id": str(self.app_row.application_id)}).json()
        self.assertEqual(self.db.get(ChatConversation, uuid.UUID(row["conversation_id"])).application_id, self.app_row.application_id)


if __name__ == "__main__":
    unittest.main()
