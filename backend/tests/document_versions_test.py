"""Replacing a vault document keeps both versions; each application sees only the version attached now.

Needs the HomeFlow database (db/init applied):
    HOMEFLOW_DB_TEST=1 python -m unittest tests.document_versions_test        (from backend/)
"""
import os
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.api.v1 import documents
from app.core.security import current_customer
from app.db.models import Application, ApplicationField, AuditEvent, Customer, File
from app.db.session import SessionLocal
from app.main import app


@unittest.skipUnless(os.getenv("HOMEFLOW_DB_TEST") == "1", "set HOMEFLOW_DB_TEST=1 with the database running")
class DocumentVersionTests(unittest.TestCase):
    def setUp(self):
        self.db = SessionLocal()
        self.customer = Customer(customer_id=uuid.uuid4(), email=f"test-{uuid.uuid4()}@example.invalid")
        self.db.add(self.customer); self.db.flush()
        self.draft, self.sent = (Application(customer_id=self.customer.customer_id, status=s) for s in ("draft", "draft"))
        self.db.add_all([self.draft, self.sent]); self.db.commit()
        app.dependency_overrides[current_customer] = lambda: Customer(customer_id=self.customer.customer_id)
        self.client = TestClient(app)
        self.blobs = {}
        for name, fake in (("put_object", lambda key, body, ct: self.blobs.__setitem__(key, body)),
                           ("get_object", lambda key: self.blobs[key]), ("delete_object", lambda key: self.blobs.pop(key, None))):
            stub = patch.object(documents.storage, name, side_effect=fake); stub.start(); self.addCleanup(stub.stop)
        self.queue = patch.object(documents.queue, "publish_extraction_job"); self.published = self.queue.start(); self.addCleanup(self.queue.stop)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.rollback()
        for model in (AuditEvent, File, Application):
            self.db.execute(delete(model).where(model.customer_id == self.customer.customer_id))
        self.db.execute(delete(Customer).where(Customer.customer_id == self.customer.customer_id))
        self.db.commit(); self.db.close()

    def _pdf(self, text="v1"):
        return ("w2.pdf", f"%PDF-{text}-{uuid.uuid4()}".encode(), "application/pdf")

    def _upload(self):
        file_id = self.client.post("/api/v1/documents", data={"document_tag": "w2", "logical_path": "/Taxes"},
                                   files={"file": self._pdf()}).json()["file_id"]
        self._read(file_id)
        return file_id

    def _read(self, file_id):
        with SessionLocal() as s:
            s.get(File, uuid.UUID(file_id)).status = "completed"; s.commit()

    def _replace(self, file_id, body=None):
        return self.client.post(f"/api/v1/documents/{file_id}/replace", files={"file": body or self._pdf("v2")})

    def _vault(self):
        return [d["file_id"] for d in self.client.get("/api/v1/documents").json()]

    def test_replacing_keeps_the_old_version_and_shows_the_new_one(self):
        old = self._upload()
        sent = self._replace(old)
        self.assertEqual(sent.status_code, 201, sent.text)
        new = sent.json()
        self.assertEqual((new["version"], new["document_tag"], new["folder"], new["status"]), (2, "w2", "Taxes", "queued"))
        self.assertEqual(self._vault(), [new["file_id"]])                       # the vault shows the newest only
        history = self.client.get(f"/api/v1/documents/{new['file_id']}/versions").json()
        self.assertEqual([(v["file_id"], v["version"], v["current"]) for v in history],
                         [(old, 1, False), (new["file_id"], 2, True)])
        self.assertEqual(self.client.get(f"/api/v1/documents/{old}/content").status_code, 200)   # still viewable by the owner
        self.assertEqual(self.client.get(f"/api/v1/documents/{old}").json()["version"], 1)

    def test_every_application_moves_to_the_new_version_and_drops_old_proposals(self):
        old = self._upload()
        for application in (self.draft, self.sent):
            self.client.post(f"/api/v1/documents/{old}/link", json={"application_id": str(application.application_id)})
        self._read(old)                                                    # attaching started field extraction
        with SessionLocal() as s:
            s.add(ApplicationField(application_id=self.draft.application_id, field_name="base_income", value="1",
                                   file_id=uuid.UUID(old), review_state="proposed"))
            s.add(ApplicationField(application_id=self.draft.application_id, field_name="dob", value="1990-01-01",
                                   file_id=uuid.UUID(old), review_state="confirmed"))
            s.get(Application, self.sent.application_id).status = "submitted"; s.commit()
        new = self._replace(old).json()["file_id"]
        for application in (self.draft, self.sent):
            listed = [d["file_id"] for d in self.client.get(f"/api/v1/documents?application_id={application.application_id}").json()]
            self.assertEqual(listed, [new])
        with SessionLocal() as s:
            self.assertIsNone(s.get(ApplicationField, (self.draft.application_id, "base_income")))   # proposal from v1 gone
            self.assertEqual(s.get(ApplicationField, (self.draft.application_id, "dob")).value, "1990-01-01")  # customer's own stays
        self.assertEqual(self.published.call_args.kwargs["file_id"], uuid.UUID(new))
        events = self.db.query(AuditEvent).filter_by(action="document.replaced", file_id=uuid.UUID(new)).all()
        self.assertEqual(set(events[0].payload["applications"]), {str(self.draft.application_id), str(self.sent.application_id)})

    def test_only_the_newest_version_can_be_replaced_and_not_while_reading(self):
        old = self._upload()
        new = self._replace(old).json()["file_id"]
        self.assertEqual(self._replace(old).status_code, 409)              # an earlier version
        self.assertEqual(self._replace(new).status_code, 409)              # still being read
        self._read(new)
        self.assertEqual(self._replace(new).json()["version"], 3)

    def test_the_same_bytes_are_not_a_new_version(self):
        old = self._upload()
        body = self._pdf("same")
        self.assertEqual(self._replace(old, body).status_code, 201)
        self._read(self._vault()[0])
        self.assertEqual(self._replace(self._vault()[0], body).status_code, 409)

    def test_uploading_an_earlier_version_again_is_explained_not_reused(self):
        body = self._pdf("first")
        old = self.client.post("/api/v1/documents", data={"document_tag": "w2"}, files={"file": body}).json()["file_id"]
        self._read(old); self._replace(old)
        again = self.client.post("/api/v1/documents", data={"document_tag": "w2"}, files={"file": body})
        self.assertEqual(again.status_code, 409)
        self.assertIn("earlier version", again.json()["detail"])

    def test_delete_removes_every_version(self):
        old = self._upload()
        new = self._replace(old).json()["file_id"]; self._read(new)
        self.assertEqual(self.client.delete(f"/api/v1/documents/{new}/permanent").status_code, 204)
        with SessionLocal() as s:
            self.assertEqual((s.get(File, uuid.UUID(old)), s.get(File, uuid.UUID(new))), (None, None))
        self.assertEqual(self.blobs, {})

    def test_another_customer_cannot_replace_or_list_versions(self):
        old = self._upload()
        stranger = uuid.uuid4()
        self.db.add(Customer(customer_id=stranger, email=f"test-{uuid.uuid4()}@example.invalid")); self.db.commit()
        try:
            app.dependency_overrides[current_customer] = lambda: Customer(customer_id=stranger)
            self.assertEqual(self._replace(old).status_code, 404)
            self.assertEqual(self.client.get(f"/api/v1/documents/{old}/versions").status_code, 404)
        finally:
            self.db.execute(delete(Customer).where(Customer.customer_id == stranger)); self.db.commit()


if __name__ == "__main__":
    unittest.main()
