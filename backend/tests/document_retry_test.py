import unittest
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import Mock, patch
from fastapi import HTTPException
from app.api.v1 import documents

class RetryDocumentTests(unittest.TestCase):
    def test_failed_file_is_queued_without_reupload(self):
        db=Mock(); customer=SimpleNamespace(customer_id=uuid4())
        row=SimpleNamespace(file_id=uuid4(),customer_id=customer.customer_id,application_id=uuid4(),document_tag="paystub",status="failed",attempts=3,error_detail="timeout")
        db.scalar.return_value=row
        with patch.object(documents.queue,"publish_extraction_job") as publish:
            documents.retry_document(row.file_id,db,customer)
        self.assertEqual(row.status,"queued")
        self.assertEqual(row.attempts,0)
        publish.assert_called_once()

    def test_running_and_unowned_files_cannot_be_requeued(self):
        db=Mock();customer=SimpleNamespace(customer_id=uuid4())
        for row,code in [(None,404),(SimpleNamespace(status="processing"),409)]:
            db.scalar.return_value=row
            with self.assertRaises(HTTPException) as caught:
                documents.retry_document(uuid4(),db,customer)
            self.assertEqual(caught.exception.status_code,code)

    def test_queue_failure_remains_retryable(self):
        db=Mock(); row=SimpleNamespace(file_id=uuid4(),customer_id=uuid4(),application_id=uuid4(),document_tag="paystub",status="failed",attempts=3,error_detail="timeout")
        db.scalar.return_value=row
        with patch.object(documents.queue,"publish_extraction_job",side_effect=RuntimeError("queue unavailable")):
            with self.assertRaises(HTTPException):
                documents.retry_document(row.file_id,db,SimpleNamespace(customer_id=row.customer_id))
        self.assertEqual(row.status,"failed")


class DuplicateUploadTests(unittest.TestCase):
    def test_existing_file_response_identifies_its_application(self):
        import asyncio,io
        from fastapi import UploadFile
        from starlette.datastructures import Headers
        db=Mock();customer=SimpleNamespace(customer_id=uuid4())
        existing=SimpleNamespace(file_id=uuid4(),application_id=uuid4(),status="completed")
        db.scalar.return_value=existing
        upload=UploadFile(file=io.BytesIO(b"%PDF-test"),filename="test.pdf",headers=Headers({"content-type":"application/pdf"}))
        with patch.object(documents,"_check_application"),patch.object(documents,"_store_file") as store:
            result=asyncio.run(documents.upload(upload,"paystub",existing.application_id,False,"/",db,customer))
        self.assertEqual(result["file_id"],str(existing.file_id))
        self.assertEqual(result["application_id"],str(existing.application_id))
        store.assert_not_called()


class InitialQueueFailureTests(unittest.TestCase):
    def test_upload_queue_failure_is_visible_and_retryable(self):
        db=Mock()
        row=SimpleNamespace(file_id=uuid4(),customer_id=uuid4(),application_id=None,document_tag="w2",status="queued",error_detail=None)
        with patch.object(documents.queue,"publish_extraction_job",side_effect=RuntimeError("offline")):
            documents._queue_file(db,row)
        self.assertEqual(row.status,"failed")
        self.assertIn("retry",row.error_detail.lower())
        db.commit.assert_called_once()


class IncompleteW2RetryTests(unittest.TestCase):
    def test_incomplete_completed_w2_can_retry(self):
        db=Mock();db.scalars.return_value.all.return_value=[]
        row=SimpleNamespace(file_id=uuid4(),status="completed",document_tag="w2")
        self.assertTrue(documents._retry_allowed(db,row))

    def test_complete_w2_cannot_retry(self):
        db=Mock();db.scalars.return_value.all.return_value=[SimpleNamespace(field_name=k,corrected_value=None,value_normalized="value",value_raw="value") for k in ("employee_name","employer_name","box1_wages")]
        row=SimpleNamespace(file_id=uuid4(),status="completed",document_tag="w2")
        self.assertFalse(documents._retry_allowed(db,row))


class IncompleteReadRetryTests(unittest.TestCase):
    def rows(self, *names):
        return [SimpleNamespace(field_name=k, corrected_value=None, value_normalized="value", value_raw="value") for k in names]

    def test_license_without_number_can_be_read_again(self):
        db=Mock(); db.scalars.return_value.all.return_value=self.rows("full_name","date_of_birth","expiry_date")
        self.assertTrue(documents._retry_allowed(db, SimpleNamespace(file_id=uuid4(),status="completed",document_tag="drivers_license")))

    def test_complete_license_and_other_documents_cannot(self):
        db=Mock(); db.scalars.return_value.all.return_value=self.rows("full_name","date_of_birth","license_number","expiry_date")
        self.assertFalse(documents._retry_allowed(db, SimpleNamespace(file_id=uuid4(),status="completed",document_tag="drivers_license")))
        self.assertFalse(documents._retry_allowed(db, SimpleNamespace(file_id=uuid4(),status="completed",document_tag="other")))

    def test_corrected_value_counts_as_found(self):
        db=Mock(); rows=self.rows("full_name","date_of_birth","expiry_date")+[SimpleNamespace(field_name="license_number",corrected_value="52224976",value_normalized=None,value_raw=None)]
        db.scalars.return_value.all.return_value=rows
        self.assertFalse(documents._retry_allowed(db, SimpleNamespace(file_id=uuid4(),status="completed",document_tag="drivers_license")))


class ReuseVaultUploadTests(unittest.TestCase):
    def test_upload_attaches_owned_unlinked_copy(self):
        db=Mock(); customer=SimpleNamespace(customer_id=uuid4()); app=uuid4()
        row=SimpleNamespace(file_id=uuid4(),application_id=None,status="completed")
        def attach(*args): row.application_id=app
        with patch.object(documents,"link_document",side_effect=attach) as link:
            result=documents._reuse_upload(db,row,app,customer)
        link.assert_called_once()
        self.assertEqual(result["application_id"],str(app))
        self.assertEqual(result["duplicate_of"],str(row.file_id))

    def test_upload_never_moves_another_app_copy(self):
        row=SimpleNamespace(file_id=uuid4(),application_id=uuid4(),status="completed")
        with patch.object(documents,"link_document") as link:
            result=documents._reuse_upload(Mock(),row,uuid4(),Mock())
        link.assert_not_called()
        self.assertEqual(result["application_id"],str(row.application_id))
