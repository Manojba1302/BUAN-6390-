import os
import unittest
from unittest.mock import patch
from sqlalchemy import select
from app.db.models import Extraction, File, ChatTurn
from app.api.v1 import chat
from tests import postgres_test

@unittest.skipUnless(os.getenv("HOMEFLOW_DB_TEST") == "1", "requires isolated PostgreSQL")
class ChatHistoryTests(unittest.TestCase):
    setUp = postgres_test.DatabaseTests.setUp
    tearDown = postgres_test.DatabaseTests.tearDown
    _file = postgres_test.DatabaseTests._file

    def conversation(self):
        response = self.client.post("/api/v1/chat/conversations", json={"application_id": str(self.app_row.application_id)})
        self.assertEqual(response.status_code, 201)
        return "/api/v1/chat/conversations/" + response.json()["conversation_id"]

    def send(self, route, question):
        with patch.object(chat.ollama, "embed", side_effect=AssertionError("No model needed")):
            response = self.client.post(route + "/messages", json={"question": question})
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_history_survives_reopen_and_followup_reads_current_correction(self):
        file = self._file("drivers_license", full_name="Example Person", expiry_date="2027-01-01")
        route = self.conversation()
        first = self.send(route, "When does my driving license expire?")
        row = self.db.scalar(select(Extraction).where(Extraction.file_id == file.file_id, Extraction.field_name == "expiry_date"))
        row.corrected_value = "2029-01-01"; self.db.commit()
        second = self.send(route, "When does it expire?")
        self.assertIn("2029-01-01", second["reply"]["answer"])
        history = self.client.get(route).json()["turns"]
        self.assertEqual(len(history), 2)
        self.assertIn("2027-01-01", history[0]["reply"]["answer"])
        self.assertEqual(history[0]["source_status"][str(file.file_id)], "changed")
        self.assertEqual(history[1]["source_status"][str(file.file_id)], "current")

    def test_deleted_source_is_unavailable_and_history_keeps_answer(self):
        file = self._file("drivers_license", full_name="Example", expiry_date="2027-01-01")
        route = self.conversation(); self.send(route, "When does my license expire?")
        file_id = str(file.file_id)
        self.db.delete(file); self.db.commit()
        turn = self.client.get(route).json()["turns"][0]
        self.assertEqual(turn["source_status"][file_id], "unavailable")
        self.assertIn("2027-01-01", turn["reply"]["answer"])

    def test_new_conversation_is_empty_and_delete_keeps_documents(self):
        file = self._file("drivers_license", full_name="Example", expiry_date="2027-01-01")
        first = self.conversation(); self.send(first, "When does my license expire?")
        second = self.conversation()
        self.assertEqual(self.client.get(second).json()["turns"], [])
        self.assertEqual(self.client.delete(first).status_code, 204)
        self.assertEqual(self.client.get(first).status_code, 404)
        self.assertIsNotNone(self.db.get(File, file.file_id))

    def test_ambiguous_followup_asks_for_document(self):
        for name in ("Person One", "Person Two"):
            self._file("drivers_license", full_name=name, expiry_date="2027-01-01")
        route = self.conversation(); self.send(route, "When do my licenses expire?")
        reply = self.send(route, "What is its address?")["reply"]
        self.assertIn("Which document", reply["answer"])
        self.assertEqual(len(reply["document_links"]), 2)

    def test_failed_request_is_saved_and_does_not_block_retry(self):
        file = self._file("drivers_license", full_name="Example", expiry_date="2027-01-01")
        route = self.conversation()
        with patch.object(chat.chat_evidence, "retrieve", return_value=[{"file_id":str(file.file_id),"page":1,"content":"conditions","original_name":"license.pdf"}]), patch.object(chat.ollama, "embed", return_value=[0.1]*768), patch.object(chat.ollama, "generate_json", side_effect=chat.ollama.OllamaError("down")):
            response = self.client.post(route + "/messages", json={"question": "Explain the printed conditions"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.client.get(route).json()["turns"][0]["status"], "failed")
        self.send(route, "When does my license expire?")

    def test_other_customer_cannot_read_send_or_delete_history(self):
        from app.core.security import current_customer
        from app.main import app
        from app.db.models import Customer
        from uuid import uuid4
        route = self.conversation()
        app.dependency_overrides[current_customer] = lambda: Customer(customer_id=uuid4())
        self.assertEqual(self.client.get(route).status_code, 404)
        self.assertEqual(self.client.post(route + "/messages", json={"question":"hello"}).status_code, 404)
        self.assertEqual(self.client.delete(route).status_code, 404)

    def test_new_session_does_not_reuse_historical_followup(self):
        from datetime import datetime, timezone, timedelta
        self._file("drivers_license", full_name="Example", expiry_date="2027-01-01")
        route = self.conversation()
        self.send(route, "When does my license expire?")
        response = self.client.post(route+"/messages", json={"question":"What is its address?", "context_after":(datetime.now(timezone.utc)+timedelta(seconds=1)).isoformat()})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Which document", response.json()["reply"]["answer"])

    def test_question_identifier_is_redacted_in_database(self):
        route = self.conversation()
        self.send(route,"What is my SSN 123-45-6789?")
        row = self.db.scalar(select(ChatTurn).where(ChatTurn.conversation_id == route.rsplit("/",1)[1]))
        self.assertNotIn("123-45-6789", row.question)

    def _events(self, route, question):
        response = self.client.post(route + "/messages/stream", json={"question": question})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
        import json
        return [(block.split("\n")[0][7:], json.loads(block.split("\n")[1][6:])) for block in response.text.strip().split("\n\n")]

    def test_stream_sends_draft_text_then_the_verified_turn(self):
        from app.api.v1 import conversations
        from app.agent import streaming
        def fake(conversation, question, cutoff, db, customer):
            streaming.SINK.get()("Your lease ends")
            streaming.SINK.get()("Your lease ends June 30, 2027. SSN 123-45-6789")
            return {"answer": "Your lease ends June 30, 2027.", "citations": [], "evidence": []}
        with patch.object(conversations, "_generate", side_effect=fake):
            events = self._events(self.conversation(), "When does my lease end?")
        kinds = [kind for kind, _ in events]
        self.assertEqual(kinds, ["token", "token", "done"])
        self.assertNotIn("123-45-6789", events[1][1]["text"])
        self.assertEqual(events[-1][1]["reply"]["answer"], "Your lease ends June 30, 2027.")
        self.assertEqual(events[-1][1]["status"], "completed")

    def test_stream_instant_answer_has_no_draft_and_is_saved(self):
        self._file("drivers_license", full_name="Example Person", expiry_date="2027-01-01")
        route = self.conversation()
        with patch.object(chat.ollama, "embed", side_effect=AssertionError("No model needed")):
            events = self._events(route, "When does my driving license expire?")
        self.assertEqual([kind for kind, _ in events], ["done"])
        self.assertIn("2027-01-01", events[0][1]["reply"]["answer"])
        self.assertEqual(len(self.client.get(route).json()["turns"]), 1)


class PartialAnswerTests(unittest.TestCase):
    def test_draft_answer_is_read_from_incomplete_json(self):
        from app.agent.streaming import partial_answer
        self.assertEqual(partial_answer('{"ans'), "")
        self.assertEqual(partial_answer('{"answer": "Your lease ends Ju'), "Your lease ends Ju")
        self.assertEqual(partial_answer('{"answer": "Line \\"one\\"\\nnext", "citations": ['), 'Line "one"\nnext')
        self.assertEqual(partial_answer('{"answer": "ends with \\'), "ends with ")
