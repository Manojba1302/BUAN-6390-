"""Vijay's borrower chat scenarios, the part HomeFlow can answer before a loan file exists (November 2026).

    python -m unittest tests.borrower_questions_test                          (intent tests, no database)
    HOMEFLOW_DB_TEST=1 python -m unittest tests.borrower_questions_test       (from backend/, all)
"""
import os
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import delete

from app.api.v1 import chat
from app.db.models import Application, ApplicationField, ChatConversation, Customer
from app.services import application_chat, borrower_questions
from tests import postgres_test

SCENARIOS = {
    "Where is my loan right now and what's the next step?": "progress",
    "What documents do you still need from me?": "documents",
    "When will I get my Closing Disclosure?": "closing_disclosure",
    "How much cash do I need to bring to closing?": "cash_to_close",
    "Why did my Loan Estimate change?": "loan_estimate_change",
    "What's my monthly payment with taxes and insurance?": "monthly_payment",
    "Can I upload my paystub here?": "upload",
    "Who is my loan officer and processor, and how do I reach them?": "contacts",
}
SAME_MEANING = {
    "When do I receive my CD?": "closing_disclosure",
    "What are my closing costs?": "cash_to_close",
    "Why did my LE go up?": "loan_estimate_change",
    "Why is my revised loan estimate different?": "loan_estimate_change",
    "What will my mortgage payment be?": "monthly_payment",
    "How do I upload my W-2?": "upload",
    "Where can I send my bank statement?": "upload",
    "How can I contact my lender?": "contacts",
}
NOT_THESE = [  # document questions and off-topic questions must keep their own route
    "What is the expiry date on my license?", "How many documents did I upload?", "Did I upload my W-2?",
    "What is the ending balance on my bank statement?", "What is my CD balance?", "Who is my employer?",
    "What is my gross pay?", "Tell me a joke",
]


class IntentTests(unittest.TestCase):
    def test_vijays_eight_questions(self):
        for question, kind in SCENARIOS.items():
            self.assertEqual(application_chat.intent(question), kind, question)

    def test_the_same_questions_in_other_words(self):
        for question, kind in SAME_MEANING.items():
            self.assertEqual(application_chat.intent(question), kind, question)

    def test_document_and_unrelated_questions_are_not_taken(self):
        for question in NOT_THESE:
            self.assertIsNone(application_chat.intent(question), question)

    def test_no_amount_is_ever_stated_or_estimated(self):
        for kind in ("cash_to_close", "monthly_payment", "closing_disclosure", "loan_estimate_change", "contacts"):
            text = borrower_questions.answer(kind, None)["answer"]
            self.assertNotIn("$", text)
        self.assertIn("won't guess", borrower_questions.answer("cash_to_close", None)["answer"])

    def test_disclosure_rules(self):
        cd = borrower_questions.answer("closing_disclosure", None)["answer"]
        self.assertIn("at least 3 business days before your closing date", cd)
        self.assertIn("except Sundays and federal public holidays", cd)
        self.assertIn("within 3 business days", borrower_questions.answer("loan_estimate_change", None)["answer"])

    def test_upload_offers_the_upload_button(self):
        for application in (None, uuid.uuid4()):
            reply = borrower_questions.answer("upload", application)
            self.assertEqual(reply["actions"], [{"kind": "upload", "label": "Upload a document"}])
        self.assertIn("Documents step", borrower_questions.answer("upload", uuid.uuid4())["answer"])
        self.assertIn("leave the type as Other", borrower_questions.answer("upload", None)["answer"])


@unittest.skipUnless(os.getenv("HOMEFLOW_DB_TEST") == "1", "requires PostgreSQL")
class BorrowerChatTests(unittest.TestCase):
    setUp = postgres_test.DatabaseTests.setUp

    def tearDown(self):
        self.db.rollback()
        self.db.execute(delete(ChatConversation).where(ChatConversation.customer_id == self.customer.customer_id))
        self.db.commit()
        postgres_test.DatabaseTests.tearDown(self)

    def ask(self, question, application_id=None):
        with patch.object(chat.ollama, "embed", side_effect=AssertionError("No model needed")):
            return chat.ask(chat.Ask(question=question, application_id=application_id), self.db, self.customer)

    def _second_application(self, purpose):
        second = Application(customer_id=self.customer.customer_id, status="draft",
                             created_at=datetime.now(timezone.utc) + timedelta(minutes=1))
        self.db.add(second); self.db.flush()
        self.db.add(ApplicationField(application_id=second.application_id, field_name="loanPurpose", value=purpose))
        self.db.commit()
        return second

    def test_every_scenario_is_answered_in_an_application_and_on_the_vault(self):
        for question in SCENARIOS:
            for application in (self.app_row.application_id, None):
                answer = self.ask(question, application)["answer"]
                self.assertNotIn("I don't know about that", answer, question)
                self.assertNotIn("could not find anything", answer, question)

    def test_vault_progress_covers_each_application_newest_first(self):
        refinance = self._second_application("NoCash-Out Refinance")
        answer = self.ask("Where is my loan right now and what's the next step?")["answer"]
        first, older = application_chat.name(self.db, refinance), application_chat.name(self.db, self.app_row)
        self.assertIn("You have 2 applications.", answer)
        self.assertLess(answer.index(first), answer.index(older))
        self.assertTrue(first.startswith("Refinance HF-"))
        self.assertEqual(answer.count("not lender approval"), 1)

    def test_vault_with_no_application(self):
        self.db.execute(delete(Application).where(Application.customer_id == self.customer.customer_id)); self.db.commit()
        self.assertIn("haven't started an application", self.ask("What documents do you still need from me?")["answer"])

    def test_vault_progress_never_lists_someone_elses_application(self):
        other = Customer(customer_id=uuid.uuid4(), email=f"other-{uuid.uuid4()}@example.invalid")
        self.db.add(other); self.db.flush()
        theirs = Application(customer_id=other.customer_id, status="draft"); self.db.add(theirs); self.db.commit()
        try:
            answer = self.ask("Where is my loan right now?")["answer"]
            self.assertNotIn(theirs.application_id.hex[:8].upper(), answer)
            self.assertIn(self.app_row.application_id.hex[:8].upper(), answer)
        finally:
            self.db.execute(delete(Application).where(Application.customer_id == other.customer_id))
            self.db.execute(delete(Customer).where(Customer.customer_id == other.customer_id)); self.db.commit()

    def test_unrelated_questions_are_still_refused(self):
        self.assertIn("I don't know about that", self.ask("Tell me a joke")["answer"])

    def test_approval_questions_are_still_refused(self):
        self.assertIn("can't tell", self.ask("Am I approved for this loan?")["answer"])

    def test_the_upload_button_is_kept_in_history(self):
        made = self.client.post("/api/v1/chat/conversations", json={}).json()["conversation_id"]
        sent = self.client.post(f"/api/v1/chat/conversations/{made}/messages", json={"question": "Can I upload my paystub here?"})
        self.assertEqual(sent.status_code, 200)
        self.assertEqual(sent.json()["reply"]["actions"], [{"kind": "upload", "label": "Upload a document"}])
        again = self.client.get(f"/api/v1/chat/conversations/{made}").json()["turns"][0]["reply"]
        self.assertEqual(again["actions"], [{"kind": "upload", "label": "Upload a document"}])


if __name__ == "__main__":
    unittest.main()
