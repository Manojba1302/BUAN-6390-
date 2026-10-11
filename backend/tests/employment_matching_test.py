import os
import tempfile
from pathlib import Path
import unittest
from decimal import Decimal
from sqlalchemy import select
from app.db.models import Employment, DocumentMarkdown
from app.services import prefill
from tests import postgres_test


@unittest.skipUnless(os.getenv("HOMEFLOW_DB_TEST") == "1", "requires isolated PostgreSQL")
class EmploymentMatchingTests(unittest.TestCase):
    setUp = postgres_test.DatabaseTests.setUp
    tearDown = postgres_test.DatabaseTests.tearDown
    _file = postgres_test.DatabaseTests._file

    def test_case_and_spacing_match_confirmed_job_without_duplicate(self):
        self.db.add(Employment(application_id=self.app_row.application_id,
                              employer_name=" UNIVERSITY  OF TEXAS AT DALLAS ",
                              position="student worker", base=0))
        self.db.commit()
        file = self._file("paystub", employer_name="University of Texas at Dallas",
                          employee_name="Example Employee", gross_pay="961.88", pay_frequency="semimonthly", pay_rate="617.50", pay_rate_basis="semimonthly")
        prefill.apply_file(self.db, file=file)
        rows = self.db.scalars(select(Employment).where(Employment.application_id == self.app_row.application_id)).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].position, "student worker")
        self.assertEqual(rows[0].base, Decimal("0"))
        state = self.client.get(f"/api/v1/applications/{self.app_row.application_id}").json()
        self.assertEqual(state["employment_suggestions"][0]["base"], "1235.00")
        self.assertEqual(state["employment_suggestions"][0]["employee_name"], "Example Employee")

    def test_two_real_jobs_are_not_merged_or_overwritten(self):
        for position in ("Job one", "Job two"):
            self.db.add(Employment(application_id=self.app_row.application_id,
                                  employer_name="Same Employer", position=position, base=123))
        self.db.commit()
        prefill.apply_file(self.db, file=self._file("paystub", employer_name="SAME EMPLOYER",
                                                   gross_pay="1000", pay_frequency="monthly"))
        rows = self.db.scalars(select(Employment).where(Employment.application_id == self.app_row.application_id)).all()
        self.assertEqual(len(rows), 2)
        self.assertEqual({row.position for row in rows}, {"Job one", "Job two"})
        self.assertTrue(all(row.base == 123 for row in rows))

    def test_save_combined_entry_does_not_recreate_duplicate_on_load(self):
        self._file("paystub", employer_name="SAME EMPLOYER", gross_pay="1000", pay_frequency="monthly")
        route = f"/api/v1/applications/{self.app_row.application_id}"
        self.client.patch(route, json={"employment": [{"employer_name": "Same Employer", "position": "Kept job", "base": "1000"}]})
        for _ in range(2):
            state = self.client.get(route).json()
            self.assertEqual(len(state["employment"]), 1)
            self.assertEqual(state["employment"][0]["position"], "Kept job")

    def test_gross_pay_never_becomes_base_salary(self):
        self._file("paystub", employer_name="Example", gross_pay="961.88", pay_frequency="semimonthly")
        state = self.client.get(f"/api/v1/applications/{self.app_row.application_id}").json()
        self.assertEqual(state["employment_suggestions"][0]["base"], None)
        self.assertEqual(state["employment"], [])

    def test_hourly_rate_without_standard_hours_needs_review(self):
        self._file("paystub", employer_name="Example", gross_pay="1200", pay_rate="20", pay_rate_basis="hourly", pay_frequency="biweekly")
        state = self.client.get(f"/api/v1/applications/{self.app_row.application_id}").json()
        self.assertIsNone(state["employment_suggestions"][0]["base"])

    def test_legacy_document_text_supplies_rate_and_job_title(self):
        file = self._file("paystub", employer_name="Example", gross_pay="961.88", pay_frequency="semimonthly")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "document.md"
            path.write_text("# Pay stub\n## Document text\n### Page 1\nJob Title: Student Assistant\nPay Rate: $617.50 Semimonthly\nGross Pay: $961.88", encoding="utf-8")
            self.db.add(DocumentMarkdown(file_id=file.file_id, markdown_path=str(path)))
            self.db.commit()
            state = self.client.get(f"/api/v1/applications/{self.app_row.application_id}").json()
            candidate = state["employment_suggestions"][0]
            self.assertEqual(candidate["base"], "1235.00")
            self.assertEqual(candidate["position"], "Student Assistant")
            self.assertEqual(candidate["gross_pay"], "961.88")

    def test_invalid_income_does_not_partially_save_application_fields(self):
        route = f"/api/v1/applications/{self.app_row.application_id}"
        response = self.client.patch(route, json={"fields": {"firstName": "Should not save"}, "employment": [{"employer_name": "Example", "base": "-10"}]})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("firstName", self.client.get(route).json()["fields"])

    def test_blank_dates_currency_and_previous_job_save_consistently(self):
        route = f"/api/v1/applications/{self.app_row.application_id}"
        response = self.client.patch(route, json={"fields": {"employmentStatus": "Employed"}, "employment": [
            {"employer_name": "Current", "base": "$1,235.00", "start_date": "", "is_current": True},
            {"employer_name": "Previous", "base": "", "start_date": "", "is_current": False}]})
        self.assertEqual(response.status_code, 200)
        rows = response.json()["employment"]
        self.assertEqual(len(rows), 2)
        self.assertTrue(any(row["is_current"] is False for row in rows))
        progress = self.client.get(route + "/progress").json()
        money = next(step for step in progress["steps"] if step["id"] == "money")
        self.assertNotIn("Base monthly employment income", money["missing"])

    def test_document_review_then_save_one_job_survives_reload(self):
        for tag in ("paystub", "w2", "paystub"):
            self._file(tag, employer_name="University of Texas at Dallas", pay_rate="617.50", pay_rate_basis="semimonthly")
        route = f"/api/v1/applications/{self.app_row.application_id}"
        before = self.client.get(route).json()
        self.assertEqual(before["employment"], [])
        self.assertEqual(len(before["employment_suggestions"]), 3)
        self.client.patch(route, json={"fields": {"employmentStatus": "Employed"}, "employment": [{"employer_name": "University of Texas at Dallas", "base": "1235.00", "position": "Student Assistant"}]})
        for _ in range(3):
            state = self.client.get(route).json()
            self.assertEqual(len(state["employment"]), 1)
            self.assertEqual(str(state["employment"][0]["base"]), "1235.00")
        missing = next(step for step in self.client.get(route + "/progress").json()["steps"] if step["id"] == "money")["missing"]
        self.assertNotIn("Base monthly employment income", missing)

    def test_blank_current_income_remains_incomplete_after_reload(self):
        route = f"/api/v1/applications/{self.app_row.application_id}"
        self.client.patch(route, json={"fields": {"employmentStatus": "Employed"}, "employment": [{"employer_name": "UTD", "base": ""}]})
        money = next(step for step in self.client.get(route + "/progress").json()["steps"] if step["id"] == "money")
        self.assertFalse(money["complete"])
        self.assertIn("Base monthly employment income", money["missing"])
