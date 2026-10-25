"""Schema coverage and natural-language regression questions; synthetic data only."""
import unittest
import doc_types
from app.services.document_answers import intent, _value
from app.db.models import Extraction
import uuid
from unittest.mock import Mock
from app.api.v1.chat import DECISION
from app.agent import scope
from app.db.models import File
from app.services import document_answers

CASES = [
    ("What is my SSN number?", "employee_ssn"),
    ("Show my social security number", "ssn"),
    ("What is my DL number?", "license_number"),
    ("Which bank is on my statement? institution name", "institution"),
    ("What is the account number?", "account_mask"),
    ("What is the employer EIN?", "employer_ein"),
    ("What are my year-to-date earnings?", "ytd_gross"),
    ("When is the expiry date in my driving license?", "expiry_date"),
    ("What job title is printed on my payslip?", "position"),
    ("How much is my take home pay?", "net_pay"),
    ("What is my postal code?", "zip"),
    ("What is the rate of pay?", "pay_rate"),
    ("What is the name of my bank?", "institution"),
    ("Which bank is my account with?", "institution"),
    ("What is my salary?", "gross_pay"),
    ("How much did I earn?", "gross_pay"),
]

class RoutingRegressionTests(unittest.TestCase):
    def test_bank_name_does_not_return_account_holder(self):
        fields = intent("What is the name of my bank?")[0]
        self.assertNotIn("account_holder", fields)

    def test_employer_address_is_not_answered_with_holder_address(self):
        for question in ("What is my employer's address?", "What is my employeer address?", "Where is my company address?", "What is the address of my employer?", "where is my company located"):
            self.assertTrue(scope.allowed(question))
            with self.subTest(question=question):
                fields, tags = intent(question)
                self.assertIn("employer_address", fields)
                self.assertNotIn("address", fields)
                self.assertEqual(tags, ["w2", "paystub"])

    def test_date_of_birth_is_masked_to_year(self):
        row = Extraction(field_name="date_of_birth", value_raw="1996-04-21")
        self.assertEqual(_value(row), "••/••/1996 (full date hidden; open the document to view)")


class ChatRedactionTests(unittest.TestCase):
    def test_phone_and_birth_date_are_masked(self):
        from app.agent.privacy import redact
        text = redact("Call (214) 555-0100 or 214.555.0199. DOB 04/21/1996. Date of birth: April 21, 1996. File 1cb8f64c-6d88-477a-a247-837a5379bf8a")
        self.assertNotIn("555-0100", text); self.assertIn("[PHONE ending 0100]", text); self.assertIn("[PHONE ending 0199]", text)
        self.assertNotIn("04/21/1996", text); self.assertNotIn("April 21, 1996", text)
        self.assertIn("1cb8f64c-6d88-477a-a247-837a5379bf8a", text)

    def test_amounts_dates_and_zip_codes_are_not_mistaken_for_phones(self):
        from app.agent.privacy import redact
        text = "Gross pay 961.88 on 2026-09-15, ZIP 75080-1207, EIN 75-1305556"
        self.assertEqual(redact(text), text)

class QuestionMatrixTests(unittest.TestCase):
    def test_natural_language_questions(self):
        for question, expected in CASES:
            with self.subTest(question=question):
                self.assertIn(expected, intent(question)[0])

    def test_every_catalogue_field_with_four_question_forms(self):
        import json
        from pathlib import Path
        cases = json.loads((Path(__file__).parent / "fixtures/chat_questions.json").read_text(encoding="utf-8"))
        for case in cases:
            with self.subTest(document=case["document_type"], question=case["question"]):
                self.assertIn(case["expected_field"], intent(case["question"])[0])

    def test_identifiers_are_masked_in_answers_and_corrections(self):
        row = Extraction(field_name="employee_ssn", value_raw="123-45-6789")
        self.assertEqual(_value(row), "••••6789")
        row.corrected_value = "987-65-4321"
        self.assertEqual(_value(row), "••••4321")
        row.corrected_value = ""
        self.assertEqual(_value(row), "")

class DecisionQuestionTests(unittest.TestCase):
    def test_eligibility_questions_get_decision_reply(self):
        for q in ("Am I eligible for a mortgage?", "Will I get approved?", "Do I qualify for this loan?", "What are my chances of getting approved?"):
            with self.subTest(q=q):
                self.assertTrue(DECISION.search(q))

    def test_ordinary_questions_are_not_decisions(self):
        for q in ("What is my gross pay?", "Is my license approved for driving?", "When was the loan statement issued?"):
            with self.subTest(q=q):
                self.assertFalse(DECISION.search(q))


class ScopeAndIntentTests(unittest.TestCase):
    def test_paid_questions_are_in_scope(self):
        self.assertTrue(scope.allowed("when was i paid"))
        self.assertEqual(document_answers.intent("when was i paid")[0], ("pay_date",))

    def test_take_home_without_pay_maps_to_net_pay(self):
        self.assertIn("net_pay", document_answers.intent("What is my monthly take-home?")[0])


class MonthlyNoteTests(unittest.TestCase):
    def _paystub(self, **values):
        f = File(file_id=uuid.uuid4(), document_tag="paystub", status="completed", original_name="pay.pdf")
        rows = [Extraction(file_id=f.file_id, field_name=k, value_raw=v, page=1) for k, v in values.items()]
        db = Mock(); db.scalars.return_value.all.return_value = rows
        return db, [f]

    def test_monthly_conversion_uses_printed_frequency(self):
        db, files = self._paystub(pay_rate="617.50", pay_rate_basis="semimonthly", net_pay="932.78", pay_frequency="semimonthly")
        note = document_answers.monthly_note(db, files, "How much do I make per month?")
        self.assertIn("1,235.00", note)
        self.assertIn("1,865.56", note)

    def test_no_conversion_without_frequency_or_month_question(self):
        db, files = self._paystub(pay_rate="20.00", pay_rate_basis="hourly")
        self.assertEqual(document_answers.monthly_note(db, files, "How much do I make per month?"), "")
        db, files = self._paystub(pay_rate="617.50", pay_rate_basis="semimonthly")
        self.assertEqual(document_answers.monthly_note(db, files, "What is my pay rate?"), "")


class OtherDocumentRoutingTests(unittest.TestCase):
    def _needs_general(self, question, names=("lease_doc.png",)):
        from app.services import chat_evidence
        db = Mock(); db.scalars.return_value.all.return_value = list(names)
        return chat_evidence.needs_general(db, Mock(customer_id=uuid.uuid4()), uuid.uuid4(), question)

    def test_field_questions_keep_instant_answers_with_other_document_attached(self):
        for q in ("Who is my employer?", "What is my SSN?", "What's my salary?", "Compare the names on my documents"):
            with self.subTest(q=q):
                self.assertFalse(self._needs_general(q))

    def test_other_document_questions_use_document_search(self):
        for q in ("When does my lease expire?", "Who is the landlord?", "What does the lease_doc say about pets?"):
            with self.subTest(q=q):
                self.assertTrue(self._needs_general(q))
        self.assertFalse(self._needs_general("When does my lease expire?", names=()))

    def test_decision_questions_are_answered_before_scope_check(self):
        from app.api.v1.chat import _policy_reply
        self.assertIn("loan team", _policy_reply("Will I get approved?")["answer"])
        self.assertTrue(scope.allowed("Who is the landlord?"))
