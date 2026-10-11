import unittest
from unittest.mock import patch
import address_evidence
from worker import pipeline

QUOTE = "BHARAT SAI GANTA 905 W PRESIDENT GEORGE BUSH HWY APT 1 RICHARDSON TX 75080-1206"

class AddressEvidenceTests(unittest.TestCase):
    def fields(self):
        return {"employee_name": {"value": "BHARAT SAI GANTA", "quote": QUOTE, "page": 1}}

    def test_owner_address_recovers_all_parts_and_source(self):
        result = address_evidence.recover("w2", self.fields())
        self.assertEqual(result["address"]["value"], "905 W PRESIDENT GEORGE BUSH HWY APT 1")
        self.assertEqual(result["city"]["value"], "RICHARDSON")
        self.assertEqual(result["zip"]["value"], "75080-1206")
        self.assertEqual(result["city"]["quote"], QUOTE)

    def test_employer_and_ambiguous_quotes_do_not_supply_address(self):
        self.assertEqual(address_evidence.recover("w2", {"employer_name": self.fields()["employee_name"]}), {})
        fields = self.fields(); fields["employee_name"]["quote"] += " 1 OTHER ROAD DALLAS TX 75201"
        self.assertEqual(address_evidence.recover("w2", fields), {})

    def test_existing_parts_and_intentional_blanks_are_not_replaced(self):
        fields = self.fields(); fields["address"] = {"value": "Different address"}
        self.assertEqual(address_evidence.recover("w2", fields), {})
        fields = self.fields(); fields["city"] = {"value": ""}
        self.assertNotIn("city", address_evidence.recover("w2", fields))

    def test_initial_upload_extracts_missing_parts_without_second_model_call(self):
        with patch.object(pipeline.ollama, "generate_json", return_value={"fields": self.fields()}) as model:
            result = pipeline.extract({"pages": [{"text": QUOTE}]}, "w2")
        self.assertEqual(model.call_count, 1)
        self.assertEqual(result["city"]["value"], "RICHARDSON")

    def test_owner_block_recovers_when_name_quote_omits_address(self):
        fields = {"account_holder": {"value": "EXAMPLE PERSON", "quote": "EXAMPLE PERSON"}}
        page = {"page": 1, "text": "Bank address\n100 BANK ROAD\nTAMPA FL 33622\nEXAMPLE PERSON\n905 EXAMPLE HWY\nAPT 12\nRICHARDSON, TX 75080-1207\nAccount summary"}
        result = address_evidence.recover_pages("bank_statement", [page], fields)
        self.assertEqual(result["address"]["value"], "905 EXAMPLE HWY APT 12")
        self.assertEqual(result["city"]["value"], "RICHARDSON")
        self.assertNotIn("BANK ROAD", result["address"]["value"])

    def test_conflicting_owner_blocks_are_left_unresolved(self):
        fields = {"account_holder": {"value": "EXAMPLE PERSON"}}
        pages = [{"text": "EXAMPLE PERSON\n1 FIRST ROAD\nDALLAS TX 75201"}, {"text": "EXAMPLE PERSON\n2 SECOND ROAD\nAUSTIN TX 78701"}]
        self.assertEqual(address_evidence.recover_pages("bank_statement", pages, fields), {})
