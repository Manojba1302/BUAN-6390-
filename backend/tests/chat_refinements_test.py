import unittest
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import Mock
from app.services import structured_chat, missing_document_fields, chat_tools

class ChatRefinementTests(unittest.TestCase):
    def test_same_document_is_not_comparison(self):
        self.assertIsNone(structured_chat.intent("What address is printed on that same document?"))
        self.assertEqual(structured_chat.intent("Which documents show different names or addresses?"), "identity")

    def test_identity_explanation_covers_both(self):
        files=[SimpleNamespace(file_id=uuid4(),status="completed") for _ in range(2)]
        rows=[]
        for i,f in enumerate(files):
            for key,value in {"employee_name":str(i),"address":str(i),"city":"Dallas","state":"TX","zip":"75001"}.items():
                rows.append(SimpleNamespace(file_id=f.file_id,field_name=key,value_raw=value,value_normalized=value,evidence_quote="",corrected_value=None))
        result=structured_chat._explanation("identity",files,rows)
        self.assertIn("printed names differ",result)
        self.assertIn("values differ",result)

    def test_missing_fields_respects_blank_correction_and_zero(self):
        file=SimpleNamespace(file_id=uuid4(),status="completed",document_tag="paystub",original_name="pay.pdf")
        rows=[SimpleNamespace(file_id=file.file_id,field_name="pay_rate",value_raw="617.50",value_normalized="617.50",evidence_quote="",corrected_value=""),SimpleNamespace(file_id=file.file_id,field_name="overtime_pay",value_raw="0",value_normalized="0",evidence_quote="",corrected_value=None)]
        result=missing_document_fields.describe(file,rows)
        self.assertIn("pay rate",result)
        self.assertNotIn("overtime pay",result)

    def test_missing_question_uses_fields_without_model(self):
        db=Mock();file=SimpleNamespace(file_id=uuid4(),status="completed",document_tag="unknown",original_name="unfamiliar.pdf")
        db.scalars.return_value.all.side_effect=[[file],[]]
        reply=missing_document_fields.answer(db,SimpleNamespace(customer_id=uuid4()),uuid4(),"What information could you not find in my documents?")
        self.assertIn("no field schema",reply["answer"])
        self.assertEqual(reply["document_links"][0]["file_id"],str(file.file_id))

    def test_pay_difference_does_not_claim_extra_hours(self):
        self.assertEqual(chat_tools.calculate("961.88","617.50","difference"),"344.38 (same units as source; absolute difference)")
        self.assertIn("does not establish overtime",chat_tools._pay_note(["gross_pay","pay_rate"])[0])
