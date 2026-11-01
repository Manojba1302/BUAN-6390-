"""The vault folders: built-in checklist folders, the customer's own folders, and moving files.

The first class needs nothing. The second needs the HomeFlow database (db/init applied):
    HOMEFLOW_DB_TEST=1 python -m unittest tests.vault_folders_test        (from backend/)
"""
import os
import unittest
import uuid
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.api.v1 import documents
from app.core.security import current_customer
from app.db.models import AuditEvent, Customer, File
from app.db.session import SessionLocal
from app.main import app
from app.services import vault_folders


class FolderRuleTests(unittest.TestCase):
    def test_default_folders_follow_the_household_checklist(self):
        self.assertEqual(vault_folders.DEFAULT_FOLDERS, ("Legal", "Identification & Licenses", "People & Places",
                                                         "Finances", "Taxes", "Insurance & Property", "Other"))

    def test_each_document_type_has_a_usual_folder(self):
        expected = {"drivers_license": "Identification & Licenses", "ssn_card": "Identification & Licenses",
                    "paystub": "Finances", "bank_statement": "Finances", "w2": "Taxes", "other": "Other"}
        for tag, folder in expected.items():
            self.assertEqual(vault_folders.default_for(tag), folder)

    def test_files_saved_before_folders_show_in_their_usual_folder(self):
        self.assertEqual(vault_folders.folder_of("/", "w2"), "Taxes")
        self.assertEqual(vault_folders.folder_of(None, "paystub"), "Finances")
        self.assertEqual(vault_folders.folder_of("/Legal", "w2"), "Legal")

    def test_upload_without_a_folder_needs_no_lookup(self):
        self.assertEqual(vault_folders.path_for_upload(None, uuid.uuid4(), "/", "ssn_card"),
                         "/Identification & Licenses")

    def test_bad_folder_names_are_refused(self):
        for name in ("", "   ", "a/b", "x" * 41, "<script>"):
            with self.assertRaises(HTTPException) as caught:
                vault_folders.create(None, uuid.uuid4(), name)
            self.assertEqual(caught.exception.status_code, 400)


@unittest.skipUnless(os.getenv("HOMEFLOW_DB_TEST") == "1", "set HOMEFLOW_DB_TEST=1 with the database running")
class FolderApiTests(unittest.TestCase):
    def setUp(self):
        self.db = SessionLocal()
        self.customer = Customer(customer_id=uuid.uuid4(), email=f"test-{uuid.uuid4()}@example.invalid")
        self.db.add(self.customer); self.db.commit()
        app.dependency_overrides[current_customer] = lambda: Customer(customer_id=self.customer.customer_id)
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.rollback()
        self.db.execute(delete(AuditEvent).where(AuditEvent.customer_id == self.customer.customer_id))
        self.db.execute(delete(Customer).where(Customer.customer_id == self.customer.customer_id))
        self.db.commit(); self.db.close()

    def _upload(self, tag, folder=None, body=None, label=None):
        data = {"document_tag": tag, **({"logical_path": folder} if folder is not None else {}),
                **({"document_label": label} if label is not None else {})}
        files = {"file": ("doc.pdf", body or f"%PDF-{uuid.uuid4()}".encode(), "application/pdf")}
        with patch.object(documents.storage, "put_object"), patch.object(documents.queue, "publish_extraction_job"):
            return self.client.post("/api/v1/documents", data=data, files=files)

    def _folders(self):
        return {f["name"]: f for f in self.client.get("/api/v1/documents/folders").json()}

    def test_new_customer_sees_the_seven_empty_default_folders(self):
        folders = self.client.get("/api/v1/documents/folders").json()
        self.assertEqual([f["name"] for f in folders], list(vault_folders.DEFAULT_FOLDERS))
        self.assertTrue(all(f["default"] and f["count"] == 0 for f in folders))

    def test_vault_upload_needs_no_application_and_lands_in_the_usual_folder(self):
        sent = self._upload("w2")
        self.assertEqual(sent.status_code, 201, sent.text)
        row = self.client.get(f"/api/v1/documents/{sent.json()['file_id']}").json()
        self.assertEqual((row["folder"], row["application_id"]), ("Taxes", None))
        self.assertEqual(self._folders()["Taxes"]["count"], 1)

    def test_upload_into_a_chosen_folder_matches_case_insensitively(self):
        sent = self._upload("other", folder="legal")
        self.assertEqual(self.client.get(f"/api/v1/documents/{sent.json()['file_id']}").json()["folder"], "Legal")
        self.assertEqual(self._upload("other", folder="Nowhere").status_code, 400)

    def test_customer_folder_can_be_made_used_and_removed(self):
        made = self.client.post("/api/v1/documents/folders", json={"name": "  Kids   school "})
        self.assertEqual((made.status_code, made.json()["name"]), (201, "Kids school"))
        self.assertEqual(self.client.post("/api/v1/documents/folders", json={"name": "kids SCHOOL"}).status_code, 409)
        file_id = self._upload("paystub").json()["file_id"]
        moved = self.client.patch(f"/api/v1/documents/{file_id}/folder", json={"folder": "kids school"})
        self.assertEqual(moved.json()["folder"], "Kids school")
        self.assertEqual(self._folders()["Kids school"]["count"], 1)
        self.assertEqual(self.client.delete("/api/v1/documents/folders/Kids school").status_code, 204)
        self.assertNotIn("Kids school", self._folders())
        self.assertEqual(self.client.get(f"/api/v1/documents/{file_id}").json()["folder"], "Finances")

    def test_built_in_folders_cannot_be_deleted_and_unknown_moves_fail(self):
        self.assertEqual(self.client.delete("/api/v1/documents/folders/Taxes").status_code, 409)
        self.assertEqual(self.client.delete("/api/v1/documents/folders/Nope").status_code, 404)
        file_id = self._upload("w2").json()["file_id"]
        self.assertEqual(self.client.patch(f"/api/v1/documents/{file_id}/folder", json={"folder": "Nope"}).status_code, 404)

    def test_other_customers_cannot_move_my_files_or_see_my_folders(self):
        file_id = self._upload("w2").json()["file_id"]
        self.client.post("/api/v1/documents/folders", json={"name": "Private"})
        stranger = Customer(customer_id=uuid.uuid4(), email=f"test-{uuid.uuid4()}@example.invalid")
        self.db.add(stranger); self.db.commit()
        try:
            app.dependency_overrides[current_customer] = lambda: Customer(customer_id=stranger.customer_id)
            self.assertEqual(self.client.patch(f"/api/v1/documents/{file_id}/folder", json={"folder": "Legal"}).status_code, 404)
            self.assertNotIn("Private", self._folders())
        finally:
            self.db.execute(delete(Customer).where(Customer.customer_id == stranger.customer_id)); self.db.commit()

    def test_stored_only_documents_keep_their_label(self):
        sent = self._upload("other", folder="Legal", label="  Last   Will ")
        row = self.client.get(f"/api/v1/documents/{sent.json()['file_id']}").json()
        self.assertEqual((row["label"], row["folder"], row["document_tag"]), ("Last Will", "Legal", "other"))
        self.assertIsNone(self.client.get(f"/api/v1/documents/{self._upload('w2').json()['file_id']}").json()["label"])
        self.assertEqual(self._upload("other", label="<b>").status_code, 400)

    def test_existing_root_files_count_in_their_usual_folder(self):
        self.db.add(File(file_id=uuid.uuid4(), customer_id=self.customer.customer_id, document_tag="drivers_license",
                         original_name="dl.jpg", storage_key=f"{uuid.uuid4()}.jpg", status="completed", logical_path="/"))
        self.db.commit()
        self.assertEqual(self._folders()["Identification & Licenses"]["count"], 1)


if __name__ == "__main__":
    unittest.main()
