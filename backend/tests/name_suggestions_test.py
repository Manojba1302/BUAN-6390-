"""Identity suggestions never silently choose a person or overwrite a confirmed name."""
import os
import unittest
import uuid
from app.db.models import ApplicationField, Extraction, File
from tests import postgres_test


@unittest.skipUnless(os.getenv("HOMEFLOW_DB_TEST") == "1", "requires isolated PostgreSQL")
class NameSuggestionTests(unittest.TestCase):
    setUp = postgres_test.DatabaseTests.setUp
    tearDown = postgres_test.DatabaseTests.tearDown

    def add_document(self, first, last, tag="w2", linked=True):
        file = File(file_id=uuid.uuid4(), customer_id=self.customer.customer_id,
                    application_id=self.app_row.application_id if linked else None,
                    document_tag=tag, original_name=f"{tag}.pdf", storage_key=f"{uuid.uuid4()}.pdf", status="completed")
        self.db.add(file); self.db.flush()
        for name, value in (("first_name", first), ("last_name", last)):
            if value:
                self.db.add(Extraction(file_id=file.file_id, field_name=name, value_raw=value, page=1))
        self.db.commit()
        return file

    def test_different_people_are_separate_suggestions_not_auto_names(self):
        self.add_document("Bharat", "Sai", "w2")
        self.add_document("Michael", "Jr", "drivers_license")
        self.db.add(ApplicationField(application_id=self.app_row.application_id, field_name="firstName",
                                     value="Michael", source="extracted", review_state="proposed"))
        self.db.commit()
        state = self.client.get(f"/api/v1/applications/{self.app_row.application_id}").json()
        self.assertNotIn("firstName", state["fields"])
        self.assertEqual({c["label"] for c in state["name_suggestions"]}, {"Bharat Sai", "Michael Jr"})
        self.assertTrue(all(c["page"] == 1 for c in state["name_suggestions"]))

    def test_confirmed_pair_survives_other_person_document(self):
        route = f"/api/v1/applications/{self.app_row.application_id}"
        self.client.patch(route, json={"fields": {"firstName": "Bharat", "lastName": "Sai"}})
        self.add_document("Michael", "Jr", "drivers_license")
        state = self.client.get(route).json()
        self.assertEqual(state["fields"]["firstName"]["value"], "Bharat")
        self.assertEqual(state["fields"]["lastName"]["value"], "Sai")

    def test_unlinked_vault_document_is_not_an_application_suggestion(self):
        self.add_document("Other", "Person", linked=False)
        state = self.client.get(f"/api/v1/applications/{self.app_row.application_id}").json()
        self.assertEqual(state["name_suggestions"], [])

    def test_full_name_is_not_split_into_guessed_parts(self):
        file = self.add_document("", "", "drivers_license")
        self.db.add(Extraction(file_id=file.file_id, field_name="full_name", value_raw="Example Multiple Names", page=2))
        self.db.commit()
        state = self.client.get(f"/api/v1/applications/{self.app_row.application_id}").json()
        candidate = state["name_suggestions"][0]
        self.assertEqual(candidate["label"], "Example Multiple Names")
        self.assertEqual((candidate["first_name"], candidate["last_name"]), ("", ""))
