"""Borrower-confirmed application sharing with the lender service."""
import os
import secrets
from urllib.parse import quote
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.applications import _owned, _account_defaults
from app.services import audit
from app.core.security import current_customer
from app.db.models import SubmissionFile, SubmissionRecord, Application, AuthAccount, Customer, File
from app.db.session import get_db
from app.services import attachments, storage, versions

router = APIRouter()


def key():
    value = os.getenv("LOAN_LINK_SECRET", "")
    if len(value) < 32:
        raise HTTPException(503, "Lender linking is unavailable.")
    return value


def trusted(x_loan_link: str = Header(default="")):
    if not secrets.compare_digest(key().encode(), x_loan_link.encode()):
        raise HTTPException(403, "Access denied")


class Selection(BaseModel):
    token: str = Field(min_length=32,max_length=128)
    accept: bool = False
    model_config = {"extra":"forbid"}


@router.post("/lender-invitations")
def select_application(body: Selection, customer: Customer = Depends(current_customer), db: Session = Depends(get_db)):
    account = db.get(AuthAccount, customer.customer_id)
    if not account:
        raise HTTPException(403, "Sign in with the invited account.")
    info = claim_invitation(body, account.email, customer.customer_id)
    if body.accept:
        start_application(db, customer, UUID(info["application_id"]))
    return info


def claim_invitation(body: Selection, email: str, customer_id: UUID) -> dict:
    """Ask HomeDeed to check the invitation; with accept, it creates the loan's application id."""
    base = os.getenv("HOMEDEED_INTERNAL_URL","http://host.docker.internal:8100/api").rstrip("/")
    try:
        result = httpx.post(base+"/internal/borrower-link",headers={"X-Loan-Link":key()},
            json={**body.model_dump(mode="json"),"email":email,"customer_id":str(customer_id)},timeout=12)
    except httpx.RequestError:
        raise HTTPException(503,"HomeDeed is unavailable. Try again.")
    if result.status_code == 404:
        raise HTTPException(404,"This invitation has expired, was used, or belongs to another account.")
    if result.status_code != 200:
        raise HTTPException(503,"Unable to reach the lender.")
    return result.json()


def start_application(db: Session, customer: Customer, app_id: UUID) -> None:
    """Every accepted invitation is a new application; accepting again reuses it."""
    created=db.scalar(insert(Application).values(application_id=app_id,customer_id=customer.customer_id)
                      .on_conflict_do_nothing().returning(Application.application_id))
    app=_owned(db,app_id,customer)
    if created:
        _account_defaults(db,app,customer)
        audit.record(db,action="application.created",customer_id=customer.customer_id,application_id=app_id)
    db.commit()


def lender_request(method,path,**kwargs):
    base=os.getenv("HOMEDEED_INTERNAL_URL","http://host.docker.internal:8100/api").rstrip("/")
    try:
        result=httpx.request(method,base+path,headers={"X-Loan-Link":key()},timeout=45,**kwargs)
    except httpx.RequestError:
        raise HTTPException(503,"Lender service unavailable. Retry to confirm delivery.")
    if result.status_code==409:
        raise HTTPException(409,"Refresh the document request and choose a new version.")
    if result.status_code!=200:
        raise HTTPException(404 if result.status_code==404 else 503,"Lender or loan unavailable.")
    return result.json()


def linked_lenders(customer_id: UUID, app: UUID) -> list:
    """The lender loans this application belongs to; none when lender linking isn't set up on this server."""
    if len(os.getenv("LOAN_LINK_SECRET", "")) < 32:
        return []
    return lender_request("GET", f"/internal/destinations/{customer_id}/{app}")


@router.get("/applications/{app}/lenders")
def lenders(app: UUID,customer: Customer=Depends(current_customer),db: Session=Depends(get_db)):
    _owned(db,app,customer)
    return lender_request("GET",f"/internal/destinations/{customer.customer_id}/{app}")


@router.post("/applications/{app}/lenders/{loan}/documents/{file_id}")
def deliver(app: UUID,loan: UUID,file_id: UUID,request_id: UUID | None=None,customer: Customer=Depends(current_customer),db: Session=Depends(get_db)):
    application = _owned(db,app,customer)
    if application.status == "submitted" and db.get(SubmissionRecord, app):
        copy = db.get(SubmissionFile, (app, file_id))
        if copy is None:
            raise HTTPException(404, "This document was not part of the submission.")
        return lender_request("POST", f"/internal/deliveries/{customer.customer_id}/{app}/{loan}",
            data={"source": str(file_id), "family": str(copy.family_id), **({"request_id": str(request_id)} if request_id else {})},
            files={"file": (copy.original_name, copy.body)})
    row=db.scalar(select(File).where(File.customer_id==customer.customer_id,File.file_id==file_id,attachments.attached_to(app)))
    if not row:
        raise HTTPException(404,"Attach this document to the application first.")
    family=versions.chain(db,file_id)[0].file_id
    return lender_request("POST",f"/internal/deliveries/{customer.customer_id}/{app}/{loan}",
        data={"source":str(file_id),"family":str(family),**({"request_id":str(request_id)} if request_id else {})},files={"file":(row.original_name,storage.get_object(row.storage_key))})


@router.get("/applications/{app}/lenders/{loan}/requests")
def requests_for_loan(app: UUID,loan: UUID,customer: Customer=Depends(current_customer),db: Session=Depends(get_db)):
    _owned(db,app,customer)
    return lender_request("GET",f"/internal/requests/{customer.customer_id}/{app}/{loan}")
