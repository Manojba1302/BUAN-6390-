"""The vault page's loan card and its one Add document area (October 2026).

Needs the HomeFlow database (db/init applied):
    HOMEFLOW_DB_TEST=1 python -m unittest tests.vault_checklist_test        (from backend/)
"""
import os
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import delete, text, update

from app.api.v1 import documents
from app.core.security import current_customer
from app.db.models import Application, ApplicationField, AuditEvent, Customer, Extraction, File
from app.db.session import SessionLocal
from app.main import app
from app.services import attachments


@unittest.skipUnless(os.getenv("HOMEFLOW_DB_TEST") == "1", "set HOMEFLOW_DB_TEST=1 with the database running")
class VaultChecklistTests(unittest.TestCase):
    def setUp(self):
        self.db = SessionLocal()
        self.customer = Customer(customer_id=uuid.uuid4(), email=f"test-{uuid.uuid4()}@example.invalid")
        self.db.add(self.customer); self.db.flush()
        self.app = Application(customer_id=self.customer.customer_id, status="draft")
        self.db.add(self.app); self.db.commit()
        app.dependency_overrides[current_customer] = lambda: Customer(customer_id=self.customer.customer_id)
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.rollback()
        for model in (AuditEvent, File, Application):
            self.db.execute(delete(model).where(model.customer_id == self.customer.customer_id))
        self.db.execute(delete(Customer).where(Customer.customer_id == self.customer.customer_id))
        self.db.commit(); self.db.close()

    def _file(self, tag, name, read=True, status="completed"):
        row = File(file_id=uuid.uuid4(), customer_id=self.customer.customer_id, document_tag=tag, original_name=name,
                   storage_key=f"{uuid.uuid4()}.pdf", status=status, logical_path="/")
        self.db.add(row); self.db.flush()
        if read:
            self.db.add(Extraction(file_id=row.file_id, field_name="x", value_raw="1", value_normalized="1"))
        attachments.attach(self.db, row, self.app.application_id)
        self.db.commit()
        return row

    def _rows(self):
        reply = self.client.get(f"/api/v1/applications/{self.app.application_id}/checklist")
        self.assertEqual(reply.status_code, 200)
        return {r["document_tag"]: r for r in reply.json()}

    def test_each_loan_document_with_counts_and_files(self):
        self._file("w2", "w2-2025.pdf")
        self._file("paystub", "pay-oct.pdf", read=False, status="processing")
        rows = self._rows()
        self.assertEqual({"w2", "paystub", "bank_statement", "drivers_license", "ssn_card"}, set(rows))
        self.assertEqual((rows["w2"]["have"], rows["w2"]["need"] >= 1), (1, True))
        self.assertEqual([f["original_name"] for f in rows["w2"]["files"]], ["w2-2025.pdf"])
        self.assertEqual((rows["paystub"]["have"], rows["paystub"]["reading"]), (0, 1))
        self.assertEqual(rows["ssn_card"]["files"], [])

    def test_not_employed_drops_w2_and_pay_stub(self):
        self.db.add(ApplicationField(application_id=self.app.application_id, field_name="employmentStatus", value="Retired"))
        self.db.commit()
        self.assertNotIn("w2", self._rows())
        self.assertNotIn("paystub", self._rows())

    def test_someone_elses_application_is_not_found(self):
        other = Customer(customer_id=uuid.uuid4(), email=f"o-{uuid.uuid4()}@example.invalid")
        self.db.add(other); self.db.commit()
        app.dependency_overrides[current_customer] = lambda: Customer(customer_id=other.customer_id)
        self.assertEqual(self.client.get(f"/api/v1/applications/{self.app.application_id}/checklist").status_code, 404)
        self.db.execute(delete(Customer).where(Customer.customer_id == other.customer_id)); self.db.commit()

    def test_applications_list_says_what_the_loan_is_for(self):
        self.db.add(ApplicationField(application_id=self.app.application_id, field_name="loanPurpose", value="Purchase"))
        self.db.commit()
        listed = self.client.get("/api/v1/applications").json()
        self.assertEqual(listed[0]["purpose"], "Purchase")

    def test_a_draft_is_deleted_and_its_documents_stay(self):
        kept = self._file("w2", "w2-2025.pdf")
        second = Application(customer_id=self.customer.customer_id, status="draft")
        self.db.add(second); self.db.commit()
        shared = self._file("drivers_license", "license.jpg")
        attachments.attach(self.db, shared, second.application_id); self.db.commit()
        self.db.execute(text("SET LOCAL homeflow.keep_links = 'on'"))      # it points at the one being deleted
        self.db.execute(update(File).where(File.file_id == shared.file_id).values(application_id=self.app.application_id)
                        .execution_options(synchronize_session=False))
        self.db.commit()
        gone, kept_id, shared_id, other = self.app.application_id, kept.file_id, shared.file_id, second.application_id
        reply = self.client.delete(f"/api/v1/applications/{gone}")
        self.assertEqual(reply.status_code, 204)
        self.db.expire_all()
        self.assertIsNone(self.db.get(Application, gone))
        self.assertIsNotNone(self.db.get(File, kept_id))
        self.assertIsNone(self.db.get(File, kept_id).application_id)
        self.assertEqual(self.db.get(File, shared_id).application_id, other)
        self.assertEqual([a["application_id"] for a in self.client.get("/api/v1/applications").json()], [str(other)])
        self.assertEqual([d["file_id"] for d in self.client.get(f"/api/v1/documents?application_id={other}").json()], [str(shared_id)])

    def test_a_sent_application_is_not_deleted(self):
        self.app.status = "submitted"; self.db.commit()
        reply = self.client.delete(f"/api/v1/applications/{self.app.application_id}")
        self.assertEqual(reply.status_code, 409)
        self.assertIsNotNone(self.db.get(Application, self.app.application_id))

    def test_someone_else_cannot_delete_it(self):
        app.dependency_overrides[current_customer] = lambda: Customer(customer_id=uuid.uuid4())
        self.assertEqual(self.client.delete(f"/api/v1/applications/{self.app.application_id}").status_code, 404)

    def _upload(self, **form):
        with patch.object(documents.storage, "put_object"), patch.object(documents.queue, "publish_extraction_job") as publish:
            reply = self.client.post("/api/v1/documents", files={"file": ("scan.pdf", b"%PDF-1.4 " + uuid.uuid4().bytes, "application/pdf")},
                                     data={"document_tag": "other", "logical_path": "/", **form})
        return reply, publish

    def test_submit_reference_matches_the_one_shown_everywhere(self):
        from app.api.v1 import applications
        with patch.object(applications, "progress", return_value={"complete": True, "steps": []}):
            reply = self.client.post(f"/api/v1/applications/{self.app.application_id}/submit")
        self.assertEqual(reply.status_code, 200)
        self.assertEqual(reply.json()["reference"], "HF-" + self.app.application_id.hex[:8].upper())

    def test_the_step_alone_can_be_saved(self):
        reply = self.client.patch(f"/api/v1/applications/{self.app.application_id}", json={"current_step": 3})
        self.assertEqual(reply.status_code, 200)
        self.db.expire_all()
        self.assertEqual(self.db.get(Application, self.app.application_id).current_step, 3)

    def test_add_without_a_type_is_read_in_auto_mode(self):
        reply, publish = self._upload(auto_type="true")
        self.assertEqual(reply.status_code, 201)
        self.assertEqual(publish.call_args.kwargs["mode"], "auto")
        self.assertEqual(self.db.get(File, uuid.UUID(reply.json()["file_id"])).logical_path, "/Other")

    def test_ordinary_uploads_are_read_as_before(self):
        reply, publish = self._upload()
        self.assertEqual((reply.status_code, publish.call_args.kwargs["mode"]), (201, "read"))


if __name__ == "__main__":
    unittest.main()
