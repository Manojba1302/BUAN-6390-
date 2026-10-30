"""Synthetic evaluation: require a disposable database named review. Never use customer data."""
import argparse
import hashlib
import json
import time
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import text
from app.db.session import SessionLocal
from app.db.models import Customer, Application, File, Extraction
from app.api.v1 import chat
from app.agent import evaluation
from app.agent.quality import grade


def seed(db, case):
    customer = Customer(customer_id=uuid4(), email=str(uuid4())+"@example.invalid")
    db.add(customer); db.flush()
    application = Application(application_id=uuid4(),customer_id=customer.customer_id)
    db.add(application); db.flush()
    files = {}
    for document in case["documents"]:
        files[document["key"]] = seed_document(db, customer, application, document)
    db.commit()
    return customer, application, files


def seed_document(db, customer, application, document):
    file = File(file_id=uuid4(),customer_id=customer.customer_id,application_id=application.application_id,document_tag=document["tag"],original_name=document["key"]+".pdf",storage_key="synthetic-"+str(uuid4()),status="completed")
    db.add(file); db.flush()
    page = document.get("page",1)
    for key,value in document.get("fields",{}).items():
        db.add(Extraction(file_id=file.file_id,field_name=key,value_raw=value,corrected_value=document.get("corrections",{}).get(key),page=page,evidence_quote=key+": "+value))
    if document.get("text"):
        db.execute(text("INSERT INTO document_chunk(file_id,customer_id,chunk_index,page,content) VALUES(:f,:c,0,:p,:t)"),{"f":file.file_id,"c":customer.customer_id,"p":page,"t":document["text"]})
    return file


def run_case(db, case):
    customer, application, files = seed(db, case)
    start = time.monotonic()
    try:
        with patch("app.agent.evaluation_store.publish") as logged:
            reply = answer(db, customer, application, case)
        result = {"case_id":case["id"],**grade(case,reply,files)}
    except Exception as exc:
        result = {"case_id":case["id"],"passed":False,"checks_failed":["request_failed"],"error_type":type(exc).__name__}
    finally:
        db.rollback(); db.delete(customer); db.commit()
    event = logged.call_args.args[0] if logged.called else {}
    result.update(route=event.get("route"),outcome=event.get("outcome"),timings=event.get("timings",{}),grader_version="facts-and-sources-v2")
    result["prompt_sha256"] = hashlib.sha256(chat.SYSTEM.encode()).hexdigest()
    result["case_sha256"] = hashlib.sha256(json.dumps(case,sort_keys=True).encode()).hexdigest()
    return {**result,"seconds":round(time.monotonic()-start,3)}


def answer(db, customer, application, case):
    body = chat.Ask(question=case["question"],application_id=application.application_id)
    if case.get("live_model"):
        return chat.ask(body,db,customer)
    with patch.object(chat.ollama,"embed",side_effect=chat.ollama.OllamaError("disabled for deterministic evaluation")), patch.object(chat.ollama,"generate_json",side_effect=AssertionError("Unexpected model call")):
        return chat.ask(body,db,customer)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-model",action="store_true")
    parser.add_argument("--case")
    args = parser.parse_args()
    cases = json.loads((Path(__file__).resolve().parents[1]/"tests/fixtures/chat_quality_cases.json").read_text())
    selected = [case for case in cases if (not case.get("live_model") or args.live_model) and (not args.case or case["id"]==args.case)]
    if not selected:
        parser.error("No selected cases; use --live-model for general model cases")
    with SessionLocal() as db:
        if db.scalar(text("select current_database()")) != "review":
            raise RuntimeError("Refusing evaluation writes: use the disposable review database")
        failed = False
        for case in selected:
            result = run_case(db,case)
            failed = failed or not result["passed"]
            print(json.dumps(result),flush=True)
        if failed:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
