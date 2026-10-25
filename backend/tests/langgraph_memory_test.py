import unittest
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import Mock, patch
from app.agent import graph

class GraphMemoryTests(unittest.TestCase):
    def setUp(self):
        self.customer=SimpleNamespace(customer_id=uuid4())
        self.conversation=SimpleNamespace(application_id=uuid4(),conversation_id=uuid4())
        self.db=Mock()
        self.file=SimpleNamespace(file_id=uuid4(),original_name="license.pdf")
        self.db.scalars.return_value.all.return_value=[self.file]

    def tearDown(self):
        graph.end(self.customer,self.conversation)

    def test_followup_retains_only_document_references(self):
        answer=Mock(return_value={"answer":"private answer text","citations":[{"file_id":str(self.file.file_id),"page":1}]})
        graph.run(self.db,self.customer,self.conversation,"When does my license expire?",answer)
        graph.run(self.db,self.customer,self.conversation,"What is its address?",answer)
        self.assertIn("license.pdf",answer.call_args.args[0])
        state=graph.GRAPH.get_state({"configurable":{"thread_id":graph.key(self.customer,self.conversation)}}).values
        self.assertEqual(set(state),{"source_ids","turns","pending_turn_id"})
        self.assertNotIn("private",str(state))

    def test_end_clears_followup_context(self):
        answer=Mock(return_value={"answer":"found","citations":[{"file_id":str(self.file.file_id),"page":1}]})
        graph.run(self.db,self.customer,self.conversation,"When does my license expire?",answer)
        graph.end(self.customer,self.conversation)
        reply=graph.run(self.db,self.customer,self.conversation,"What is its address?",answer)
        self.assertIn("Which document",reply["answer"])
        self.assertEqual(answer.call_count,1)

    def test_customer_isolation(self):
        other=SimpleNamespace(customer_id=uuid4())
        answer=Mock(return_value={"answer":"found","citations":[{"file_id":str(self.file.file_id),"page":1}]})
        graph.run(self.db,self.customer,self.conversation,"When does my license expire?",answer)
        reply=graph.run(self.db,other,self.conversation,"What is its address?",answer)
        self.assertIn("Which document",reply["answer"])
        graph.end(other,self.conversation)

    def test_explicit_resume_restores_document_focus(self):
        row=SimpleNamespace(status="completed",source_versions={str(self.file.file_id):"old-version"})
        with patch.object(graph.chat_history,"turns",return_value=[row]):
            graph.resume(self.db,self.customer,self.conversation)
        answer=Mock(return_value={"answer":"current value","citations":[]})
        graph.run(self.db,self.customer,self.conversation,"When does it expire?",answer)
        self.assertIn("license.pdf",answer.call_args.args[0])

    def test_document_selection_completes_pending_expiry_question(self):
        identity=uuid4()
        self.db.scalar.return_value=identity
        self.db.get.return_value=SimpleNamespace(conversation_id=self.conversation.conversation_id,question="When does it expire?")
        answer=Mock(return_value={"answer":"expiry date","citations":[]})
        graph.run(self.db,self.customer,self.conversation,"When does it expire?",answer)
        graph.run(self.db,self.customer,self.conversation,"license",answer)
        self.assertEqual(answer.call_count,1)
        self.assertEqual(answer.call_args.args[0],"When does it expire? in license")
