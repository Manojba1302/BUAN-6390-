import os
import unittest
from unittest.mock import patch
from uuid import uuid4
from fastapi import HTTPException
from app.api.v1 import chat, applications
from app.services import application_chat as service
from tests import postgres_test

class IntentTests(unittest.TestCase):
    def test_questions(self):
        for q in ("Where is my loan right now and what's the next step?", "What is my application progress?", "What is the next step?"):
            self.assertEqual(service.intent(q),"progress")
        for q in ("What documents do you still need from me?", "Which documents are outstanding?", "What documents are missing?"):
            self.assertEqual(service.intent(q),"documents")
        self.assertIsNone(service.intent("What is the expiry date on my license?"))

@unittest.skipUnless(os.getenv("HOMEFLOW_DB_TEST")=="1","requires PostgreSQL")
class ApplicationChatTests(unittest.TestCase):
    setUp=postgres_test.DatabaseTests.setUp
    tearDown=postgres_test.DatabaseTests.tearDown
    _file=postgres_test.DatabaseTests._file

    def ask(self,q,application_id=None):
        with patch.object(chat.ollama,"embed",side_effect=AssertionError("No model needed")):
            return chat.ask(chat.Ask(question=q,application_id=application_id or self.app_row.application_id),self.db,self.customer)

    def test_progress_matches_tracker(self):
        state=applications.progress(self.app_row.application_id,self.db,self.customer)
        result=self.ask("Where is my loan right now and what's the next step?")
        self.assertIn(str(state["percent"])+"%",result["answer"])
        self.assertIn("not lender approval",result["answer"])
        self.assertEqual(result["citations"],[])

    def test_missing_counts_update_after_upload(self):
        before=applications._missing_documents(self.db,self.app_row)
        self.assertTrue(before)
        item=before[0]
        for _ in range(item["need"]): self._file(item["document_tag"])
        result=self.ask("What documents do you still need from me?")
        self.assertNotIn("- "+item["display_name"]+":",result["answer"])
        self.assertIn("checklist",result["answer"])

    def test_failed_files_are_not_presented_as_accepted(self):
        file=self._file("paystub");file.status="failed";self.db.commit()
        self.assertIn("failed processing",self.ask("Which documents are outstanding?")["answer"])

    def test_submitted_does_not_claim_approval(self):
        self.app_row.status="submitted";self.db.commit()
        result=self.ask("What is my application status?")["answer"]
        self.assertIn("has been submitted",result)
        self.assertIn("not lender approval",result)

    def test_unknown_application_denied(self):
        with self.assertRaises(HTTPException) as caught:self.ask("What is my application status?",uuid4())
        self.assertEqual(caught.exception.status_code,404)

    def test_no_application_asks_for_selection(self):
        result=service.answer(self.db,self.customer,None,"What documents are missing?")
        self.assertIn("Open an application",result["answer"])

    def test_approval_guard_preserved(self):
        self.assertIn("can't tell",self.ask("Am I approved? What is my application status?")["answer"])

    def test_conversation_persists_application_answer(self):
        path="/api/v1/chat/conversations"
        created=self.client.post(path,json={"application_id":str(self.app_row.application_id)})
        route=path+"/"+created.json()["conversation_id"]
        result=self.client.post(route+"/messages",json={"question":"And what is my application progress?"})
        self.assertEqual(result.status_code,200)
        saved=self.client.get(route)
        self.assertIn("Application completion",saved.text)
