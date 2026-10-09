import unittest
from unittest.mock import Mock
import uuid
from app.db.models import File, Extraction, ApplicationField
from app.services import prefill

class NamePrefillTests(unittest.TestCase):
    def test_explicit_names_map_without_splitting_full_name(self):
        self.assertEqual(prefill.DIRECT_MAP[("drivers_license","first_name")],"firstName")
        self.assertEqual(prefill.DIRECT_MAP[("w2","last_name")],"lastName")
        self.assertEqual(prefill.DIRECT_MAP[("drivers_license","full_name")],"legalName")
        self.assertNotIn(("bank_statement","first_name"),prefill.DIRECT_MAP)

    def test_confirmed_name_survives(self):
        db=Mock()
        db.get.return_value=ApplicationField(value="Customer choice",review_state="confirmed")
        file=File(file_id=uuid.uuid4(),application_id=uuid.uuid4())
        row=Extraction(field_name="first_name",value_raw="Suggested",page=1)
        self.assertFalse(prefill._set_field(db,file,"firstName",row))
        self.assertEqual(db.get.return_value.value,"Customer choice")

    def test_proposed_name_keeps_document_evidence(self):
        db=Mock(); db.get.return_value=None
        file=File(file_id=uuid.uuid4(),application_id=uuid.uuid4())
        row=Extraction(field_name="last_name",value_raw="Example",page=1,evidence_quote="LN Example",method="vision")
        self.assertTrue(prefill._set_field(db,file,"lastName",row))
        field=db.add.call_args.args[0]
        self.assertEqual(field.file_id,file.file_id)
        self.assertEqual(field.review_state,"proposed")
        self.assertEqual(field.value,"Example")

if __name__ == "__main__": unittest.main()
