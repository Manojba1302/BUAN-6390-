import os
import unittest
import uuid
from app.db.models import ApplicationField, Extraction, File
from tests import postgres_test


@unittest.skipUnless(os.getenv("HOMEFLOW_DB_TEST") == "1", "requires isolated PostgreSQL")
class AddressSuggestionTests(unittest.TestCase):
    setUp = postgres_test.DatabaseTests.setUp
    tearDown = postgres_test.DatabaseTests.tearDown

    def add_address(self, street, city="Dallas", state="TX", zip_code="75201", linked=True):
        row = File(file_id=uuid.uuid4(), customer_id=self.customer.customer_id,
                   application_id=self.app_row.application_id if linked else None,
                   document_tag="drivers_license", original_name="license.pdf",
                   storage_key=str(uuid.uuid4()), status="completed")
        self.db.add(row); self.db.flush()
        for name, value in (("address", street), ("city", city), ("state", state), ("zip", zip_code)):
            if value:
                self.db.add(Extraction(file_id=row.file_id, field_name=name, value_raw=value, page=1))
        self.db.commit()

    def test_separate_addresses_are_not_automatically_applied(self):
        self.add_address("1 Example Street")
        self.add_address("2 Other Street", "Irving", "TX", "75060")
        self.db.add(ApplicationField(application_id=self.app_row.application_id, field_name="addr1",
                                     value="Old proposal", source="extracted", review_state="proposed"))
        self.db.commit()
        state = self.client.get(f"/api/v1/applications/{self.app_row.application_id}").json()
        self.assertNotIn("addr1", state["fields"])
        self.assertNotIn("city", state["fields"])
        self.assertEqual(len(state["address_suggestions"]), 2)
        self.assertEqual({c["address"] for c in state["address_suggestions"]}, {"1 Example Street", "2 Other Street"})

    def test_confirmed_residence_and_property_stay_separate(self):
        route = f"/api/v1/applications/{self.app_row.application_id}"
        self.client.patch(route, json={"fields": {"addr1": "My residence", "city": "Austin", "state": "TX", "zip": "78701", "propAddr1": "Property unchanged"}})
        self.add_address("Other residence")
        state = self.client.get(route).json()
        self.assertEqual(state["fields"]["addr1"]["value"], "My residence")
        self.assertEqual(state["fields"]["city"]["value"], "Austin")
        self.assertEqual(state["fields"]["propAddr1"]["value"], "Property unchanged")

    def test_incomplete_address_is_not_completed_with_guesses(self):
        self.add_address("1 Example Street", "", "", "")
        state = self.client.get(f"/api/v1/applications/{self.app_row.application_id}").json()
        candidate = state["address_suggestions"][0]
        self.assertEqual((candidate["city"], candidate["state"], candidate["zip"]), ("", "", ""))

    def test_unlinked_address_is_not_suggested(self):
        self.add_address("Vault address", linked=False)
        state = self.client.get(f"/api/v1/applications/{self.app_row.application_id}").json()
        self.assertEqual(state["address_suggestions"], [])

    def test_saved_w2_evidence_recovers_and_persists_address_once(self):
        row = postgres_test.DatabaseTests._file(self, "w2", employee_name="BHARAT SAI GANTA")
        ext = self.db.query(Extraction).filter_by(file_id=row.file_id, field_name="employee_name").one()
        ext.evidence_quote = "BHARAT SAI GANTA 905 W PRESIDENT GEORGE BUSH HWY APT 1 RICHARDSON TX 75080-1206"
        self.db.commit()
        route = f"/api/v1/applications/{self.app_row.application_id}"
        for _ in range(2):
            state = self.client.get(route).json()
            self.assertEqual(state["address_suggestions"][0]["city"], "RICHARDSON")
        rows = self.db.query(Extraction).filter_by(file_id=row.file_id, field_name="city").all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].method, "native_text")
        self.assertEqual(rows[0].evidence_quote, ext.evidence_quote)

    def test_manual_address_correction_survives_recovery(self):
        row = postgres_test.DatabaseTests._file(self, "w2", employee_name="BHARAT SAI GANTA", city="RICHARDSON")
        rows = self.db.query(Extraction).filter_by(file_id=row.file_id).all()
        for ext in rows:
            if ext.field_name == "employee_name":
                ext.evidence_quote = "BHARAT SAI GANTA 905 W PRESIDENT GEORGE BUSH HWY APT 1 RICHARDSON TX 75080-1206"
            else:
                ext.corrected_value = "Austin"
        self.db.commit()
        state = self.client.get(f"/api/v1/applications/{self.app_row.application_id}").json()
        self.assertEqual(state["address_suggestions"][0]["city"], "Austin")
        self.assertEqual(state["address_suggestions"][0]["address"], "")
