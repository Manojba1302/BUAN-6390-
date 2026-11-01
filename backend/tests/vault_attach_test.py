"""Vault rules agreed in October 2026: every upload is read, fields are pulled out only when a
document is attached to an application, and only a document saved as Other can change type.

Needs the HomeFlow database (db/init applied):
    HOMEFLOW_DB_TEST=1 python -m unittest tests.vault_attach_test        (from backend/)
"""
import os
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import delete, text

from app.api.v1 import documents
from app.core.security import current_customer
from app.db.models import Application, AuditEvent, Customer, DocumentMarkdown, Extraction, File, FileClassification
from app.db.session import SessionLocal
from app.main import app


@unittest.skipUnless(os.getenv("HOMEFLOW_DB_TEST") == "1", "set HOMEFLOW_DB_TEST=1 with the database running")
class VaultAttachTests(unittest.TestCase):
    def setUp(self):
        self.db = SessionLocal()
        self.customer = Customer(customer_id=uuid.uuid4(), email=f"test-{uuid.uuid4()}@example.invalid")
        self.db.add(self.customer); self.db.flush()
        self.application = Application(customer_id=self.customer.customer_id, status="draft")
        self.db.add(self.application); self.db.commit()
        app.dependency_overrides[current_customer] = lambda: Customer(customer_id=self.customer.customer_id)
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.rollback()
        self.db.execute(delete(AuditEvent).where(AuditEvent.customer_id == self.customer.customer_id))
        self.db.execute(delete(File).where(File.customer_id == self.customer.customer_id))
        self.db.execute(delete(Application).where(Application.customer_id == self.customer.customer_id))
        self.db.execute(delete(Customer).where(Customer.customer_id == self.customer.customer_id))
        self.db.commit(); self.db.close()

    def _read_file(self, tag="w2", outcome="matched", detected="w2", selected=None, fields=()):
        """A vault file the worker has already read and identified."""
        row = File(file_id=uuid.uuid4(), customer_id=self.customer.customer_id, document_tag=tag,
                   original_name="doc.pdf", storage_key=f"{uuid.uuid4()}.pdf", status="completed",
                   logical_path="/Taxes", attempts=1)
        self.db.add(row); self.db.flush()
        self.db.add(FileClassification(file_id=row.file_id, selected_type=selected or tag, detected_type=detected,
                                       outcome=outcome, evidence=[], mixed_document=False))
        for name in fields:
            self.db.add(Extraction(file_id=row.file_id, field_name=name, value_raw="x"))
        self.db.commit()
        return str(row.file_id)

    def _link(self, file_id):
        with patch.object(documents.queue, "publish_extraction_job") as publish:
            sent = self.client.post(f"/api/v1/documents/{file_id}/link",
                                    json={"application_id": str(self.application.application_id)})
        return sent, publish

    def _doc(self, file_id):
        return self.client.get(f"/api/v1/documents/{file_id}").json()

    def test_unattached_loan_document_is_not_flagged_for_missing_fields(self):
        doc = self._doc(self._read_file())
        self.assertEqual((doc["missing_field_count"], doc["missing_fields"], doc["can_retry"]), (0, [], False))

    def test_attaching_a_read_loan_document_queues_field_extraction(self):
        file_id = self._read_file()
        sent, publish = self._link(file_id)
        self.assertEqual((sent.status_code, sent.json()["status"]), (200, "queued"))
        self.assertEqual(publish.call_args.kwargs["mode"], "extract")
        row = self.db.get(File, uuid.UUID(file_id)); self.db.refresh(row)
        self.assertEqual((row.status, row.attempts), ("queued", 0))

    def test_partial_fields_and_unknown_classification_do_not_skip_extraction(self):
        for file_id in (self._read_file(fields=("employee_name",)),
                        self._read_file(outcome="unknown", detected="unknown")):
            sent, publish = self._link(file_id)
            self.assertEqual(sent.json()["status"], "queued")
            self.assertEqual(publish.call_args.kwargs["mode"], "extract")

    def test_completed_extraction_is_reused(self):
        file_id = self._read_file(fields=("employee_name",))
        self.db.add(AuditEvent(customer_id=self.customer.customer_id, file_id=uuid.UUID(file_id),
                              action="document.fields_extracted", payload={"document_tag": "w2", "fields": 1}))
        self.db.commit()
        sent, publish = self._link(file_id)
        self.assertEqual(sent.json()["status"], "completed")
        publish.assert_not_called()

    def test_other_does_not_extract(self):
        sent, publish = self._link(self._read_file(tag="other", detected="unknown", outcome="unknown"))
        self.assertEqual(sent.json()["status"], "completed")
        publish.assert_not_called()

    def test_vault_preview_does_not_recover_fields(self):
        with patch("app.services.saved_document_evidence.pages") as read:
            self._doc(self._read_file())
        read.assert_not_called()

    def test_file_missing_part_of_its_search_index_is_usable_and_offered_a_retry(self):
        file_id = self._read_file()
        self.db.execute(text("INSERT INTO document_chunk (file_id, customer_id, chunk_index, page, content, embedding) "
                             "VALUES (:f, :c, 0, 1, 'Wage and Tax Statement', NULL)"),
                        {"f": file_id, "c": self.customer.customer_id})
        self.db.commit()
        doc = self._doc(file_id)
        self.assertEqual((doc["status"], doc["searchable"], doc["can_retry"]), ("completed", False, True))
        with patch.object(documents.queue, "publish_extraction_job") as publish:
            self.assertEqual(self.client.post(f"/api/v1/documents/{file_id}/retry").status_code, 204)
        self.assertEqual(publish.call_args.kwargs.get("mode", "read"), "read")   # a full read again

    def test_fully_indexed_file_is_searchable_and_not_offered_a_retry(self):
        doc = self._doc(self._read_file())
        self.assertEqual((doc["searchable"], doc["can_retry"]), (True, False))

    def test_empty_read_is_not_searchable_and_can_retry(self):
        file_id = self._read_file(tag="other", outcome="unreadable", detected="unknown")
        self.db.add(DocumentMarkdown(file_id=uuid.UUID(file_id), markdown_path="/tmp/no-content.md", char_count=0))
        self.db.commit()
        doc = self._doc(file_id)
        self.assertFalse(doc["searchable"])
        self.assertTrue(doc["can_retry"])

    def test_type_chosen_from_the_list_stays_fixed(self):
        sent = self.client.patch(f"/api/v1/documents/{self._read_file()}/type", json={"document_tag": "paystub"})
        self.assertEqual(sent.status_code, 409)

    def test_other_can_take_the_suggested_type_and_loses_its_label(self):
        file_id = self._read_file(tag="other", selected="paystub", outcome="mismatched")
        self.client.patch(f"/api/v1/documents/{file_id}/type", json={"document_tag": "other", "label": "Tax letter"})
        self.assertEqual(self._doc(file_id)["label"], "Tax letter")
        sent = self.client.patch(f"/api/v1/documents/{file_id}/type", json={"document_tag": "w2"})
        self.assertEqual((sent.status_code, sent.json()["document_tag"], sent.json()["label"]), (200, "w2", None))
        self.assertEqual(self.client.patch(f"/api/v1/documents/{file_id}/type", json={"document_tag": "other"}).status_code, 409)

    def test_bad_type_or_label_is_refused(self):
        file_id = self._read_file(tag="other", detected="unknown", outcome="unknown")
        self.assertEqual(self.client.patch(f"/api/v1/documents/{file_id}/type", json={"document_tag": "nope"}).status_code, 400)
        self.assertEqual(self.client.patch(f"/api/v1/documents/{file_id}/type",
                                           json={"document_tag": "other", "label": "<b>"}).status_code, 400)

    def test_retyping_an_attached_other_file_extracts_it(self):
        file_id = self._read_file(tag="other", selected="paystub", outcome="mismatched")
        self._link(file_id)
        with patch.object(documents.queue, "publish_extraction_job") as publish:
            sent = self.client.patch(f"/api/v1/documents/{file_id}/type", json={"document_tag": "w2"})
        self.assertEqual(sent.json()["status"], "queued")
        self.assertEqual(publish.call_args.kwargs["mode"], "extract")

    def test_another_customer_cannot_change_my_document_type(self):
        file_id = self._read_file(tag="other", detected="unknown", outcome="unknown")
        stranger = Customer(customer_id=uuid.uuid4(), email=f"test-{uuid.uuid4()}@example.invalid")
        self.db.add(stranger); self.db.commit()
        try:
            app.dependency_overrides[current_customer] = lambda: Customer(customer_id=stranger.customer_id)
            self.assertEqual(self.client.patch(f"/api/v1/documents/{file_id}/type", json={"document_tag": "w2"}).status_code, 404)
        finally:
            self.db.execute(delete(Customer).where(Customer.customer_id == stranger.customer_id)); self.db.commit()


if __name__ == "__main__":
    unittest.main()
