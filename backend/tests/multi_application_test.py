"""One vault document used in several applications (Vijay, October 2026).

Needs the HomeFlow database (db/init applied):
    HOMEFLOW_DB_TEST=1 python -m unittest tests.multi_application_test        (from backend/)
"""
import os
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import delete, text

from app.api.v1 import documents
from app.core.security import current_customer
from app.db.models import (Application, ApplicationDocument, ApplicationField, AuditEvent, Customer, Extraction, File,
                           FileClassification)
from app.db.session import SessionLocal, engine
from app.main import app
from app.services import attachments


@unittest.skipUnless(os.getenv("HOMEFLOW_DB_TEST") == "1", "set HOMEFLOW_DB_TEST=1 with the database running")
class MultiApplicationTests(unittest.TestCase):
    def setUp(self):
        self.db = SessionLocal()
        self.customer = Customer(customer_id=uuid.uuid4(), email=f"test-{uuid.uuid4()}@example.invalid")
        self.db.add(self.customer); self.db.flush()
        self.a, self.b = (Application(customer_id=self.customer.customer_id, status="draft") for _ in range(2))
        self.db.add_all([self.a, self.b]); self.db.commit()
        self._as(self.customer.customer_id)
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.rollback()
        for model in (AuditEvent, File, Application):
            self.db.execute(delete(model).where(model.customer_id == self.customer.customer_id))
        self.db.execute(delete(Customer).where(Customer.customer_id == self.customer.customer_id))
        self.db.commit(); self.db.close()

    def _as(self, customer_id):
        app.dependency_overrides[current_customer] = lambda: Customer(customer_id=customer_id)

    def _license(self):
        """A driver's license already read and extracted, sitting in the vault."""
        row = File(file_id=uuid.uuid4(), customer_id=self.customer.customer_id, document_tag="drivers_license",
                   original_name="license.jpg", storage_key=f"{uuid.uuid4()}.jpg", status="completed", logical_path="/")
        self.db.add(row); self.db.flush()
        self.db.add(FileClassification(file_id=row.file_id, selected_type="drivers_license", detected_type="drivers_license",
                                       outcome="matched", evidence=[], mixed_document=False))
        self.db.add(Extraction(file_id=row.file_id, field_name="date_of_birth", value_raw="1990-02-03", value_normalized="1990-02-03"))
        self.db.add(AuditEvent(customer_id=self.customer.customer_id, file_id=row.file_id, action="document.fields_extracted",
                               payload={"document_tag": "drivers_license", "fields": 1}))
        self.db.commit()
        return str(row.file_id)

    def _attach(self, file_id, application):
        with patch.object(documents.queue, "publish_extraction_job") as publish:
            sent = self.client.post(f"/api/v1/documents/{file_id}/link", json={"application_id": str(application.application_id)})
        return sent, publish

    def _in(self, application):
        return [d["file_id"] for d in self.client.get(f"/api/v1/documents?application_id={application.application_id}").json()]

    def test_one_document_is_attached_to_two_applications(self):
        file_id = self._license()
        self.assertEqual(self._attach(file_id, self.a)[0].status_code, 200)
        sent, publish = self._attach(file_id, self.b)
        self.assertEqual(sent.status_code, 200)
        publish.assert_not_called()                                   # read once, reused
        self.assertEqual((self._in(self.a), self._in(self.b)), ([file_id], [file_id]))
        doc = self.client.get(f"/api/v1/documents/{file_id}").json()
        self.assertEqual({a["application_id"] for a in doc["applications"]}, {str(self.a.application_id), str(self.b.application_id)})

    def test_detaching_middle_link_after_reattaching_oldest(self):
        third = Application(customer_id=self.customer.customer_id, status="draft")
        self.db.add(third)
        self.db.commit()
        file_id = self._license()
        for application in (self.a, self.b, third, self.a):
            self.assertEqual(self._attach(file_id, application)[0].status_code, 200)
        response = self.client.delete(f"/api/v1/documents/{file_id}?application_id={self.b.application_id}")
        self.assertEqual(response.status_code, 204)
        self.assertEqual([self._in(a) for a in (self.a, self.b, third)], [[file_id], [], [file_id]])

    def test_each_application_gets_the_documents_values(self):
        file_id = self._license()
        self._attach(file_id, self.a); self._attach(file_id, self.b)
        for application in (self.a, self.b):
            self.client.get(f"/api/v1/applications/{application.application_id}")
            with SessionLocal() as s:
                field = s.get(ApplicationField, (application.application_id, "dob"))
                self.assertEqual((field.value, str(field.file_id)), ("1990-02-03", file_id))

    def test_removing_from_one_application_keeps_it_in_the_other(self):
        file_id = self._license()
        self._attach(file_id, self.a); self._attach(file_id, self.b)
        self.client.get(f"/api/v1/applications/{self.a.application_id}")
        self.assertEqual(self.client.delete(f"/api/v1/documents/{file_id}?application_id={self.a.application_id}").status_code, 204)
        self.assertEqual((self._in(self.a), self._in(self.b)), ([], [file_id]))
        with SessionLocal() as s:
            self.assertIsNone(s.get(ApplicationField, (self.a.application_id, "dob")))     # its proposal left with it
        self.assertEqual(self.client.get(f"/api/v1/documents/{file_id}").json()["application_id"], str(self.b.application_id))
        self.assertEqual(self.client.delete(f"/api/v1/documents/{file_id}?application_id={self.a.application_id}").status_code, 404)

    def test_submitted_application_keeps_its_copy_while_the_draft_can_let_go(self):
        file_id = self._license()
        self._attach(file_id, self.a); self._attach(file_id, self.b)
        with SessionLocal() as s:
            s.get(Application, self.a.application_id).status = "submitted"; s.commit()
        self.assertEqual(self.client.delete(f"/api/v1/documents/{file_id}?application_id={self.a.application_id}").status_code, 409)
        self.assertEqual(self.client.delete(f"/api/v1/documents/{file_id}?application_id={self.b.application_id}").status_code, 204)
        self.assertEqual(self._attach(file_id, self.a)[0].status_code, 409)    # nothing new joins a submitted one

    def test_delete_removes_it_from_every_application(self):
        file_id = self._license()
        self._attach(file_id, self.a); self._attach(file_id, self.b)
        with patch.object(documents.storage, "delete_object"):
            self.assertEqual(self.client.delete(f"/api/v1/documents/{file_id}/permanent").status_code, 204)
        self.assertEqual((self._in(self.a), self._in(self.b)), ([], []))
        with SessionLocal() as s:
            self.assertEqual(s.query(ApplicationDocument).filter_by(file_id=uuid.UUID(file_id)).count(), 0)

    def test_another_customer_cannot_attach_my_document_or_use_my_application(self):
        file_id = self._license()
        stranger = Customer(customer_id=uuid.uuid4(), email=f"test-{uuid.uuid4()}@example.invalid")
        theirs = Application(customer_id=stranger.customer_id, status="draft")
        self.db.add(stranger); self.db.flush(); self.db.add(theirs); self.db.commit()
        try:
            self.assertEqual(self._attach(file_id, theirs)[0].status_code, 404)        # my file, their application
            self._as(stranger.customer_id)
            self.assertEqual(self._attach(file_id, theirs)[0].status_code, 404)        # their session, my file
        finally:
            self.db.execute(delete(Application).where(Application.customer_id == stranger.customer_id))
            self.db.execute(delete(Customer).where(Customer.customer_id == stranger.customer_id)); self.db.commit()

    def test_older_code_that_sets_application_id_still_links_and_moves(self):
        file_id = uuid.UUID(self._license())
        with SessionLocal() as s:
            s.get(File, file_id).application_id = self.a.application_id; s.commit()
            self.assertTrue(attachments.is_attached(s, file_id, self.a.application_id))
            s.get(File, file_id).application_id = self.b.application_id; s.commit()      # a move, as before
            self.assertEqual((attachments.is_attached(s, file_id, self.a.application_id),
                              attachments.is_attached(s, file_id, self.b.application_id)), (False, True))
            s.get(File, file_id).application_id = None; s.commit()
            self.assertFalse(attachments.is_attached(s, file_id, self.b.application_id))

    def test_start_up_links_documents_from_before_this_change(self):
        file_id = uuid.UUID(self._license())
        with SessionLocal() as s:
            s.execute(text("ALTER TABLE file DISABLE TRIGGER file_application_link"))
            s.execute(text("UPDATE file SET application_id = :a WHERE file_id = :f"), {"a": self.a.application_id, "f": file_id})
            s.execute(text("ALTER TABLE file ENABLE TRIGGER file_application_link")); s.commit()
            self.assertFalse(attachments.is_attached(s, file_id, self.a.application_id))
        attachments.ensure(engine)
        with SessionLocal() as s:
            self.assertTrue(attachments.is_attached(s, file_id, self.a.application_id))


if __name__ == "__main__":
    unittest.main()
