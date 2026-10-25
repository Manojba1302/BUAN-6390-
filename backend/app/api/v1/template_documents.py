"""Authenticated sample template preview and PDF generation."""
from uuid import UUID
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.security import current_customer
from app.db.models import Customer
from app.db.session import get_db
from app.services import document_templates, template_pdf

router = APIRouter(prefix="/template-documents",tags=["templates"])

class Preview(BaseModel):
    application_id: UUID
    template_id: str = "application-summary"


@router.get("")
def listing(customer: Customer=Depends(current_customer)):
    return [{"template_id":key,"name":value["name"],"version":value["version"],"sample":True} for key,value in document_templates.TEMPLATES.items()]


@router.post("/preview")
def preview(body: Preview, db: Session=Depends(get_db), customer: Customer=Depends(current_customer)):
    return document_templates.populate(db,customer,body.application_id,body.template_id)


@router.post("/pdf")
def pdf(body: Preview, db: Session=Depends(get_db), customer: Customer=Depends(current_customer)):
    result = document_templates.populate(db,customer,body.application_id,body.template_id)
    return Response(template_pdf.render(result["markdown"]),media_type="application/pdf",headers={"Content-Disposition":"attachment; filename=homeflow-application-summary-sample.pdf","Cache-Control":"no-store","X-Content-Type-Options":"nosniff"})


@router.post("/render")
def render(body: Preview, response: Response, db: Session=Depends(get_db), customer: Customer=Depends(current_customer)):
    import base64
    result = document_templates.populate(db,customer,body.application_id,body.template_id)
    document = template_pdf.render(result["markdown"])
    response.headers["Cache-Control"] = "no-store"
    return {**result,"pdf_base64":base64.b64encode(document).decode("ascii"),"pages":template_pdf.preview_pages(document)}
