import os
import unittest
from uuid import uuid4
from app.services import document_templates as templates,template_pdf

class TemplateUnitTests(unittest.TestCase):
    def test_missing_fields_are_explicit_and_html_is_not_executed(self):
        result=templates.fill("application-summary","# Example\nFirst name: {{ first_name }}\nEmail: {{ email }}",{"first_name":"<b>Alex</b>"})
        self.assertEqual(result["missing_fields"],["email"])
        import fitz
        with fitz.open(stream=template_pdf.render(result["markdown"]),filetype="pdf") as pdf:
            self.assertIn("<b>Alex</b>",pdf[0].get_text())
            self.assertIn("MISSING",pdf[0].get_text())

    def test_unknown_template_fields_are_rejected(self):
        with self.assertRaises(ValueError):
            templates.fill("application-summary","{{ ssn }}",{"ssn":"secret"})

    def test_letter_page_and_unicode_names(self):
        import fitz
        pdf=template_pdf.render("# Summary\nLast name: Łukasz Ζωή Gudiseva\n- Bullet line")
        with fitz.open(stream=pdf,filetype="pdf") as document:
            self.assertEqual((round(document[0].rect.width),round(document[0].rect.height)),(612,792))
            if template_pdf.fonts()[0]=="HFSans":
                self.assertIn("Łukasz Ζωή",document[0].get_text())

    def test_full_number_never_printed_and_loan_amount_calculated(self):
        values=templates.scalar_values({"ssn":"123-45-6789","propertyValue":"350000","downPayment":"35,000","addr1":"1 Main St","city":"Dallas","state":"TX"})
        self.assertEqual(values["ssn_last_four"],"***-**-6789")
        self.assertEqual(values["loan_amount"],"$315,000.00")
        self.assertEqual(values["current_address"],"1 Main St, Dallas, TX")

    def test_optional_lists_are_not_missing(self):
        result=templates.fill("application-summary","{{ asset_list }}\n{{ employment_list }}",{})
        self.assertEqual(result["missing_fields"],["employment_list"])
        self.assertIn("None entered",result["markdown"])

@unittest.skipUnless(os.getenv("HOMEFLOW_DB_TEST")=="1","requires isolated database")
class TemplateApiTests(unittest.TestCase):
    from tests.postgres_test import DatabaseTests
    setUp=DatabaseTests.setUp
    tearDown=DatabaseTests.tearDown

    def test_only_confirmed_fields_are_used_and_pdf_downloads(self):
        from app.db.models import ApplicationField
        self.db.add(ApplicationField(application_id=self.app_row.application_id,field_name="firstName",value="Alex",review_state="confirmed"))
        self.db.add(ApplicationField(application_id=self.app_row.application_id,field_name="lastName",value="Unverified",review_state="proposed"))
        self.db.add(ApplicationField(application_id=self.app_row.application_id,field_name="ssn",value="123-45-6789",review_state="corrected"))
        self.db.commit()
        body={"application_id":str(self.app_row.application_id)}
        response=self.client.post("/api/v1/template-documents/preview",json=body)
        self.assertEqual(response.status_code,200)
        self.assertIn("Alex",response.json()["markdown"])
        self.assertIn("***-**-6789",response.json()["markdown"])
        self.assertNotIn("123-45-6789",response.json()["markdown"])
        self.assertNotIn("Unverified",response.json()["markdown"])
        self.assertIn("last_name",response.json()["missing_fields"])
        pdf=self.client.post("/api/v1/template-documents/pdf",json=body)
        self.assertEqual(pdf.headers["content-type"],"application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))

    def test_foreign_application_and_template_path_are_rejected(self):
        self.assertEqual(self.client.post("/api/v1/template-documents/preview",json={"application_id":str(uuid4())}).status_code,404)
        self.assertEqual(self.client.post("/api/v1/template-documents/preview",json={"application_id":str(self.app_row.application_id),"template_id":"../../.env"}).status_code,404)


class RenderPreviewTests(unittest.TestCase):
    def test_preview_pages_and_download_share_pdf(self):
        import base64
        from unittest.mock import patch
        from fastapi import Response
        from app.api.v1.template_documents import render, Preview
        import fitz
        populated = {"markdown":"# Sample\nFirst name: Alex", "missing_fields":[], "sample":True}
        response = Response()
        with patch("app.api.v1.template_documents.document_templates.populate",return_value=populated):
            result = render(Preview(application_id=uuid4()),response,db=None,customer=None)
        pdf = base64.b64decode(result["pdf_base64"])
        self.assertEqual(response.headers["cache-control"],"no-store")
        self.assertEqual(template_pdf.preview_pages(pdf),result["pages"])
        self.assertTrue(base64.b64decode(result["pages"][0]).startswith(b"\x89PNG"))
        with fitz.open(stream=pdf,filetype="pdf") as document:
            self.assertIn("Alex",document[0].get_text())
