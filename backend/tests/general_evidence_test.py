import os
import unittest
from uuid import uuid4
from sqlalchemy import text,select
from app.db.models import Customer,Application,Extraction
from app.services import chat_evidence,chat_tools
from app.api.v1.chat import _supported_answer
from tests import postgres_test

class EvidenceUnitTests(unittest.TestCase):
    def test_exact_money_and_dates(self):
        self.assertIn("29.10", chat_tools.calculate("961.88","932.78","difference"))
        self.assertIn("0.30",chat_tools.calculate("0.10","0.20","sum"))
        self.assertIn("2 days",chat_tools.calculate("2024-02-28","2024-03-01","days between"))
        self.assertIn("numeric",chat_tools.calculate("NaN","2","difference"))
        self.assertIn("numeric",chat_tools.calculate("","2","difference"))

    def test_quote_required_and_forged_quotes_rejected(self):
        p=[{"file_id":"one","page":2,"original_name":"lease.pdf","content":"Lease ends June 30.","saved_fields":[]}]
        answer={"answer":"Lease ends June 30", "citations":[{"file_id":"one","page":2}]}
        self.assertFalse(_supported_answer(answer,p)["citations"])
        answer["support"]=[{"file_id":"one","page":2,"quote":"Lease ends June 30."}]
        self.assertEqual(len(_supported_answer(answer,p)["citations"]),1)
        answer["support"][0]["quote"]="Lease ends July 31."
        self.assertFalse(_supported_answer(answer,p)["citations"])

    def test_quote_formatting_differences_are_accepted_but_values_are_not(self):
        p=[{"file_id":"one","page":1,"original_name":"pay.pdf","content":"Gross Pay:   $13,748.14\nNet Pay: 932.78","saved_fields":[]}]
        answer={"answer":"YTD 13748.14","citations":[{"file_id":"one","page":1}],"support":[{"file_id":"one","page":1,"quote":"gross pay: $13748.14"}]}
        self.assertEqual(len(_supported_answer(answer,p)["citations"]),1)
        answer["support"][0]["quote"]="Gross Pay: $13,748.15"
        self.assertFalse(_supported_answer(answer,p)["citations"])

@unittest.skipUnless(os.getenv("HOMEFLOW_DB_TEST")=="1","requires isolated database")
class GeneralEvidenceTests(unittest.TestCase):
    setUp=postgres_test.DatabaseTests.setUp
    tearDown=postgres_test.DatabaseTests.tearDown
    _file=postgres_test.DatabaseTests._file

    def chunk(self,f,content,page=2):
        self.db.execute(text("INSERT INTO document_chunk(file_id,customer_id,chunk_index,page,content) VALUES(:f,:c,0,:p,:text)"),{"f":f.file_id,"c":f.customer_id,"p":page,"text":content})
        self.db.commit()

    def test_unfamiliar_document_without_schema_or_embedding_is_searchable(self):
        f=self._file("other")
        self.chunk(f,"Lease contract terminates on June 30. Tenant must return keys.")
        found=chat_evidence.retrieve(self.db,self.customer,self.app_row.application_id,"When does the lease terminate?")
        self.assertEqual(len(found),1)
        self.assertEqual(found[0]["page"],2)
        self.assertEqual(found[0]["document_type"],"other")
        self.assertEqual(found[0]["saved_fields"],[])
        self.assertTrue(chat_evidence.needs_general(self.db,self.customer,self.app_row.application_id,"When does my lease expire?"))
        self.assertFalse(chat_evidence.needs_general(self.db,self.customer,self.app_row.application_id,"When does my driving license expire?"))
        self.assertTrue(chat_evidence.retrieve(self.db,self.customer,self.app_row.application_id,"Please summarize my lease"))

    def test_relevant_chunks_outrank_one_per_file_rotation(self):
        lease=self._file("other")
        for i,body in enumerate(("Lease rent is 1200 per month.","Lease deposit is 2400.","Lease ends June 30.")):
            self.db.execute(text("INSERT INTO document_chunk(file_id,customer_id,chunk_index,page,content) VALUES(:f,:c,:i,:p,:t)"),{"f":lease.file_id,"c":lease.customer_id,"i":i,"p":i+1,"t":body})
        other=self._file("other");self.chunk(other,"Unrelated insurance note about a lease clause",1)
        self.db.commit()
        found=chat_evidence.retrieve(self.db,self.customer,self.app_row.application_id,"lease rent per month")
        self.assertEqual(found[0]["content"],"Lease rent is 1200 per month.")

    def test_unattached_and_other_customer_documents_are_excluded(self):
        f=self._file("other");f.application_id=None;self.db.commit();self.chunk(f,"Confidential lease contract")
        other=Customer(customer_id=uuid4(),email=str(uuid4())+"@example.invalid")
        self.db.add(other);self.db.commit()
        try:
            self.assertEqual(chat_evidence.retrieve(self.db,other,None,"lease"),[])
            self.assertEqual(chat_evidence.retrieve(self.db,self.customer,self.app_row.application_id,"lease"),[])
        finally:
            self.db.delete(other);self.db.commit()

    def test_saved_correction_has_role_and_priority_metadata(self):
        f=self._file("w2",address="Old street",employer_name="Example Employer")
        r=self.db.scalar(select(Extraction).where(Extraction.file_id==f.file_id,Extraction.field_name=="address"))
        r.corrected_value="New street";self.db.commit();self.chunk(f,"Tax wages at Example Employer",1)
        found=chat_evidence.retrieve(self.db,self.customer,self.app_row.application_id,"Tax wages")
        address=next(x for x in found[0]["saved_fields"] if x["field"]=="address")
        self.assertEqual(address["value"],"New street")
        self.assertEqual(address["origin"],"customer_correction")
        self.assertEqual(address["role"],"document_holder")

    def test_unknown_document_question_uses_text_not_license_fast_path(self):
        from unittest.mock import patch
        from app.api.v1 import chat
        f=self._file("other")
        self._file("drivers_license",expiry_date="2030-01-01")
        self.chunk(f,"Lease ends June 30, 2027.")
        model={"answer":"Lease ends June 30, 2027.","citations":[{"file_id":str(f.file_id),"page":2}],"support":[{"file_id":str(f.file_id),"page":2,"quote":"Lease ends June 30, 2027."}]}
        with patch.object(chat.ollama,"embed",side_effect=chat.ollama.OllamaError("offline")),patch.object(chat.ollama,"generate_json",return_value=model):
            response=self.client.post("/api/v1/chat",json={"question":"When does my lease expire?","application_id":str(self.app_row.application_id)})
        self.assertEqual(response.status_code,200)
        self.assertIn("June 30, 2027",response.json()["answer"])
        self.assertNotIn("2030",response.json()["answer"])
        self.assertEqual(response.json()["citations"][0]["page"],2)

    def test_unreadable_unknown_document_does_not_invent_answer(self):
        from unittest.mock import patch
        from app.api.v1 import chat
        self._file("other")
        with patch.object(chat.ollama,"embed",side_effect=chat.ollama.OllamaError("offline")),patch.object(chat.ollama,"generate_json",side_effect=AssertionError("No evidence")):
            response=self.client.post("/api/v1/chat",json={"question":"Explain my lease","application_id":str(self.app_row.application_id)})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()["citations"],[])
