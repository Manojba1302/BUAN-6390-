"""Opt-in integration test. Creates and cleans only its own synthetic records."""
import os
import unittest
import uuid
from pathlib import Path
from sqlalchemy import select, text
from fastapi.testclient import TestClient
from app.main import app
from app.core.security import current_customer
from app.db.session import SessionLocal
from app.db.models import Customer, Application, File, ApplicationField, Extraction, DocumentMarkdown, Asset, AuditEvent
from app.core.config import settings
from app.services import storage

@unittest.skipUnless(os.getenv("HOMEFLOW_INTEGRATION_TEST") == "1", "requires local integration stack")
class DocumentLifecycleTests(unittest.TestCase):
    def test_remove_reuse_and_permanent_delete(self):
        owner, outsider, application_id, file_id = [uuid.uuid4() for _ in range(4)]
        key = storage.storage_key(file_id, "synthetic.txt")
        md = Path(settings.markdown_dir) / f"{file_id}.md"
        customer = Customer(customer_id=owner, email=f"test-{owner}@example.invalid")
        try:
            with SessionLocal() as db:
                db.add_all([customer, Customer(customer_id=outsider, email=f"test-{outsider}@example.invalid")]); db.flush()
                db.add(Application(application_id=application_id, customer_id=owner, status="draft")); db.flush()
                db.add(File(file_id=file_id, customer_id=owner, application_id=application_id, document_tag="drivers_license", original_name="synthetic.txt", storage_key=key, status="completed")); db.flush()
                db.add_all([ApplicationField(application_id=application_id, field_name="city", value="Test City", source="extracted", file_id=file_id, review_state="proposed"), ApplicationField(application_id=application_id, field_name="state", value="TX", source="user", file_id=file_id, review_state="confirmed"), Extraction(file_id=file_id, field_name="city", value_raw="Test City"), Asset(application_id=application_id, institution="Test", source_file_id=file_id), DocumentMarkdown(file_id=file_id, markdown_path=str(md))]); db.commit()
            storage.put_object(key, b"synthetic test document", "text/plain")
            md.write_text("Synthetic test", encoding="utf-8")
            app.dependency_overrides[current_customer] = lambda: Customer(customer_id=outsider)
            client = TestClient(app)
            self.assertEqual(client.delete(f"/api/v1/documents/{file_id}").status_code, 404)
            self.assertEqual(client.post(f"/api/v1/documents/{file_id}/link", json={"application_id":str(application_id)}).status_code, 404)
            self.assertEqual(client.delete(f"/api/v1/documents/{file_id}/permanent").status_code, 404)
            app.dependency_overrides[current_customer] = lambda: Customer(customer_id=owner)
            self.assertEqual(client.delete(f"/api/v1/documents/{file_id}").status_code, 204)
            with SessionLocal() as db:
                self.assertIsNone(db.get(File, file_id).application_id)
                self.assertIsNone(db.get(ApplicationField, (application_id, "city")))
                self.assertEqual(db.get(ApplicationField, (application_id, "state")).value, "TX")
                self.assertIsNone(db.scalar(select(Asset).where(Asset.source_file_id==file_id)))
            self.assertEqual(storage.get_object(key), b"synthetic test document")
            self.assertTrue(md.exists())
            self.assertEqual(client.post(f"/api/v1/documents/{file_id}/link", json={"application_id":str(application_id)}).status_code, 200)
            with SessionLocal() as db:
                self.assertEqual(db.get(ApplicationField,(application_id,"city")).value,"Test City")
                db.get(Application,application_id).status="submitted"; db.commit()
            self.assertEqual(client.delete(f"/api/v1/documents/{file_id}").status_code,409)
            self.assertEqual(client.delete(f"/api/v1/documents/{file_id}/permanent").status_code,409)
            with SessionLocal() as db:
                db.get(Application,application_id).status="draft"
                db.get(File,file_id).status="processing"; db.commit()
            self.assertEqual(client.delete(f"/api/v1/documents/{file_id}/permanent").status_code,409)
            with SessionLocal() as db:
                db.get(File,file_id).status="completed"; db.commit()
            self.assertEqual(client.delete(f"/api/v1/documents/{file_id}/permanent").status_code,204)
            with SessionLocal() as db:
                self.assertIsNone(db.get(File,file_id))
                self.assertIsNone(db.scalar(select(Extraction).where(Extraction.file_id==file_id)))
                self.assertIsNone(db.get(DocumentMarkdown,file_id))
                self.assertIsNone(db.get(ApplicationField,(application_id,"city")))
                field=db.get(ApplicationField,(application_id,"state"))
                self.assertEqual(field.value,"TX"); self.assertIsNone(field.file_id)
            self.assertFalse(md.exists())
            with self.assertRaises(Exception): storage.get_object(key)
        finally:
            app.dependency_overrides.pop(current_customer,None)
            storage.delete_object(key); md.unlink(missing_ok=True)
            with SessionLocal() as db:
                db.execute(text("DELETE FROM audit_event WHERE customer_id IN (:a,:b)"),{"a":owner,"b":outsider})
                db.execute(text("DELETE FROM file WHERE file_id=:id"),{"id":file_id})
                db.execute(text("DELETE FROM customer WHERE customer_id IN (:a,:b)"),{"a":owner,"b":outsider})
                db.commit()

if __name__ == "__main__": unittest.main()
