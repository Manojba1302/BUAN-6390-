import unittest
from employer_evidence import reconcile


class EmployerEvidenceTests(unittest.TestCase):
    def fields(self):
        return {"employer_name": {"value": "Example University"}, "employer_address": {"value": "905 Wrong Road"}}

    def page(self, text):
        return {"text": text, "method": "native_text", "page": 1}

    def test_employer_block_replaces_employee_address(self):
        page = self.page("Example University\n800 College Rd, SP2 26\nDallas TX 75080\nAlex Rivera\n905 Wrong Road\nDallas TX 75081")
        for tag in ("w2", "paystub"):
            result = reconcile(tag, [page, page], self.fields())
            self.assertEqual(result["employer_address"]["value"], "800 College Rd, SP2 26, Dallas TX 75080")
            self.assertEqual(result["employer_address"]["page"], 1)

    def test_employee_only_address_is_not_employer_evidence(self):
        page = self.page("Example University\nAlex Rivera\n905 Wrong Road\nDallas TX 75081")
        self.assertNotIn("employer_address", reconcile("w2", [page], self.fields()))

    def test_conflicting_employer_blocks_are_not_chosen(self):
        pages = [self.page("Example University\n" + street + "\nDallas TX 75080") for street in ("800 College Rd", "900 College Rd")]
        self.assertNotIn("employer_address", reconcile("w2", pages, self.fields()))

    def test_low_confidence_ocr_is_not_used(self):
        page = {**self.page("Example University\n800 College Rd\nDallas TX 75080"), "method": "ocr", "ocr_confidence": 50}
        self.assertNotIn("employer_address", reconcile("w2", [page], self.fields()))

    def test_other_types_unchanged(self):
        fields = self.fields()
        self.assertIs(reconcile("bank_statement", [], fields), fields)
