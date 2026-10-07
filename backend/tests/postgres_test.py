"""Database-backed tests for pre-fill, progress, upload, delete and chat.

Opt-in: they need the HomeFlow PostgreSQL database (db/init applied).
Each test creates its own synthetic customer and removes it afterwards.
    HOMEFLOW_DB_TEST=1 python -m unittest tests.postgres_test        (from backend/)
Object storage, the queue and Ollama are replaced with fakes.
"""
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text

from app.api.v1 import chat, documents
from app.core.config import settings
from app.core.security import current_customer
from app.db.models import (Application, ApplicationField, Asset, AuditEvent, Customer, DocumentMarkdown,
                           Employment, Extraction, File)
from app.db.session import SessionLocal
from app.main import app
from app.services import prefill


@unittest.skipUnless(os.getenv("HOMEFLOW_DB_TEST") == "1", "set HOMEFLOW_DB_TEST=1 with the database running")
class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.db = SessionLocal()
        self.customer = Customer(customer_id=uuid.uuid4(), email=f"test-{uuid.uuid4()}@example.invalid")
        self.app_row = Application(application_id=uuid.uuid4(), customer_id=self.customer.customer_id)
        self.db.add(self.customer); self.db.flush(); self.db.add(self.app_row); self.db.commit()
        app.dependency_overrides[current_customer] = lambda: Customer(customer_id=self.customer.customer_id)
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.rollback()
        self.db.execute(delete(AuditEvent).where(AuditEvent.customer_id == self.customer.customer_id))
        self.db.execute(delete(Customer).where(Customer.customer_id == self.customer.customer_id))
        self.db.commit(); self.db.close()

    # ---------------------------------------------------------------- helpers
    def _file(self, tag, **extractions):
        row = File(file_id=uuid.uuid4(), customer_id=self.customer.customer_id,
                   application_id=self.app_row.application_id, document_tag=tag,
                   original_name=f"{tag}.pdf", storage_key=f"{uuid.uuid4()}.pdf", status="completed")
        self.db.add(row); self.db.flush()
        for name, value in extractions.items():
            self.db.add(Extraction(file_id=row.file_id, field_name=name, value_raw=value, page=1,
                                   evidence_quote=f"{name}: {value}", method="native_text"))
        self.db.commit()
        return row

    def _field(self, name):
        self.db.expire_all()
        return self.db.get(ApplicationField, (self.app_row.application_id, name))

    # ---------------------------------------------------------------- pre-fill
    def test_prefill_proposes_values_with_evidence(self):
        self._file("drivers_license", full_name="Alex Morgan", city="Dallas")
        self.assertEqual(prefill.apply_file(self.db, file=self.db.scalar(select(File).where(
            File.application_id == self.app_row.application_id))), {"applied": 2, "skipped": 0})
        field = self._field("legalName")
        self.assertEqual((field.value, field.review_state, field.page), ("Alex Morgan", "proposed", 1))

    def test_prefill_never_overwrites_a_confirmed_value(self):
        self.db.add(ApplicationField(application_id=self.app_row.application_id, field_name="city",
                                     value="Austin", source="user", review_state="confirmed"))
        self.db.commit()
        result = prefill.apply_file(self.db, file=self._file("drivers_license", city="Dallas"))
        self.assertEqual(result, {"applied": 0, "skipped": 1})
        self.assertEqual(self._field("city").value, "Austin")

    def test_paystub_creates_employment_with_monthly_income(self):
        prefill.apply_file(self.db, file=self._file("paystub", employer_name="Northwind", gross_pay="3000",
                                                    pay_frequency="biweekly", position="Analyst"))
        job = self.db.scalar(select(Employment).where(Employment.application_id == self.app_row.application_id))
        self.assertEqual((job.employer_name, str(job.base), job.pay_frequency, job.position),
                         ("Northwind", "6500.00", "biweekly", "Analyst"))

    def test_paystub_without_frequency_leaves_income_blank(self):
        prefill.apply_file(self.db, file=self._file("paystub", employer_name="Northwind", gross_pay="3000"))
        job = self.db.scalar(select(Employment).where(Employment.application_id == self.app_row.application_id))
        self.assertEqual((float(job.base or 0), job.pay_frequency), (0.0, None))

    def test_two_statements_for_one_account_are_one_asset_with_latest_balance(self):
        for end, bal in (("2026-08-31", "1000"), ("2026-09-30", "2500"), ("2026-07-31", "50")):
            prefill.apply_file(self.db, file=self._file("bank_statement", institution="First Bank",
                                                        account_mask="****1234", ending_balance=bal, period_end=end))
        assets = self.db.scalars(select(Asset).where(Asset.application_id == self.app_row.application_id)).all()
        self.assertEqual(len(assets), 1)
        self.assertEqual((str(assets[0].balance), str(assets[0].as_of)), ("2500.00", "2026-09-30"))

    # ---------------------------------------------------------------- application API
    def test_get_application_serialises_fields_and_lists(self):
        self._file("drivers_license", city="Dallas")
        body = self.client.get(f"/api/v1/applications/{self.app_row.application_id}").json()
        self.assertEqual(body["fields"]["city"]["value"], "Dallas")
        self.assertEqual(body["fields"]["city"]["review_state"], "proposed")
        self.assertEqual((body["employment"], body["asset"], body["liability"]), ([], [], []))

    def test_progress_lists_what_is_missing(self):
        body = self.client.get(f"/api/v1/applications/{self.app_row.application_id}/progress").json()
        steps = {s["id"]: s for s in body["steps"]}
        self.assertEqual(list(steps), ["start", "documents", "about", "property", "money", "review"])
        self.assertIn("Pay stub", steps["documents"]["missing"])
        self.assertIn("Choose your employment situation in Get started", steps["money"]["missing"])
        self.assertFalse(body["complete"])
        self.assertEqual(body["percent"], 0)

    # ---------------------------------------------------------------- documents API
    def test_upload_stores_queues_and_detects_duplicates(self):
        with patch.object(documents.storage, "put_object") as put, \
             patch.object(documents.queue, "publish_extraction_job") as publish:
            send = lambda: self.client.post("/api/v1/documents", data={
                "document_tag": "w2", "application_id": str(self.app_row.application_id)},
                files={"file": ("w2.pdf", b"%PDF-1.4 synthetic", "application/pdf")})
            first, second = send().json(), send().json()
        self.assertEqual((first["status"], first["document_tag"]), ("queued", "w2"))
        self.assertEqual(second["duplicate_of"], first["file_id"])
        put.assert_called_once(); publish.assert_called_once()

    def test_upload_rejects_another_customers_application_and_bad_types(self):
        other = uuid.uuid4()
        bad_app = self.client.post("/api/v1/documents", data={"document_tag": "w2", "application_id": str(other)},
                                   files={"file": ("w2.pdf", b"%PDF", "application/pdf")})
        bad_tag = self.client.post("/api/v1/documents", data={"document_tag": "passport"},
                                   files={"file": ("x.pdf", b"%PDF", "application/pdf")})
        bad_type = self.client.post("/api/v1/documents", data={"document_tag": "w2"},
                                    files={"file": ("x.exe", b"MZ", "application/x-msdownload")})
        self.assertEqual((bad_app.status_code, bad_tag.status_code, bad_type.status_code), (404, 400, 415))

    def test_upload_still_succeeds_when_queue_is_down(self):
        with patch.object(documents.storage, "put_object"), \
             patch.object(documents.queue, "publish_extraction_job", side_effect=RuntimeError("down")):
            response = self.client.post("/api/v1/documents", data={"document_tag": "w2"},
                                        files={"file": ("w2.pdf", b"%PDF unique", "application/pdf")})
        self.assertEqual(response.status_code, 201)

    def test_delete_permanently_removes_file_markdown_and_evidence(self):
        row = self._file("drivers_license", city="Dallas")
        file_id, key = row.file_id, row.storage_key
        prefill.apply_file(self.db, file=row)
        self.db.add(ApplicationField(application_id=self.app_row.application_id, field_name="state", value="TX",
                                     source="user", review_state="confirmed", file_id=row.file_id, page=1))
        with tempfile.TemporaryDirectory() as folder, patch.object(settings, "markdown_dir", folder), \
             patch.object(documents.storage, "delete_object") as remove:
            md = Path(folder) / f"{row.file_id}.md"
            md.write_text("synthetic")
            self.db.add(DocumentMarkdown(file_id=row.file_id, markdown_path=str(md))); self.db.commit()
            response = self.client.delete(f"/api/v1/documents/{row.file_id}/permanent")
            self.assertEqual(response.status_code, 204)
            self.assertFalse(md.exists())
        remove.assert_called_once_with(key)
        self.db.expire_all()
        self.assertIsNone(self.db.get(File, file_id))
        self.assertIsNone(self._field("city"))
        kept = self._field("state")
        self.assertEqual((kept.value, kept.file_id, kept.page), ("TX", None, None))

    def test_delete_permanently_waits_for_processing(self):
        row = self._file("w2")
        row.status = "processing"; self.db.commit()
        self.assertEqual(self.client.delete(f"/api/v1/documents/{row.file_id}/permanent").status_code, 409)

    # ---------------------------------------------------------------- chat
    def _chunk(self, row, content, vector):
        self.db.execute(text("INSERT INTO document_chunk (file_id, customer_id, chunk_index, page, content, embedding) "
                             "VALUES (:f, :c, 0, 1, :t, CAST(:v AS vector))"),
                        {"f": row.file_id, "c": self.customer.customer_id, "t": content,
                         "v": "[" + ",".join(["0.1"] * 767 + [str(vector)]) + "]"})
        self.db.commit()

    def test_chat_answers_from_own_documents_with_evidence(self):
        self._chunk(self._file("bank_statement"), "Ending balance $2,500.00", 0.9)
        answer = {"answer": "Your balance is $2,500.00 [bank_statement.pdf, page 1]", "citations": [{"page": 1}]}
        with patch.object(chat.ollama, "embed", return_value=[0.1] * 768), \
             patch.object(chat.ollama, "generate_json", return_value=answer) as model:
            body = self.client.post("/api/v1/chat", json={"question": "What is my balance?"}).json()
        self.assertEqual(body["answer"], answer["answer"])
        self.assertEqual(body["evidence"][0]["content"], "Ending balance $2,500.00")
        self.assertIn("Ending balance $2,500.00", model.call_args.kwargs["prompt"])

    def test_chat_without_documents_and_with_index_down(self):
        with patch.object(chat.ollama, "embed", return_value=[0.1] * 768):
            body = self.client.post("/api/v1/chat", json={"question": "What is my balance?"}).json()
        self.assertEqual(body["citations"], [])
        with patch.object(chat.ollama, "embed", side_effect=chat.ollama.OllamaError("down")):
            self.assertEqual(self.client.post("/api/v1/chat", json={"question": "hi"}).status_code, 503)
        self.assertEqual(self.client.post("/api/v1/chat", json={"question": "  "}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
