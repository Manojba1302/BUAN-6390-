import unittest
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.api.v1 import auth
from app.api.v1.applications import _owned
from app.core.security import current_customer, digest
from app.db.models import Customer, AuthAccount, AuthSession, PasswordReset, Application
from app.db.session import get_db

class AuthTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
        for model in (Customer, AuthAccount, AuthSession, PasswordReset, Application):
            model.__table__.create(self.engine)
        def db():
            with Session(self.engine,expire_on_commit=False) as session: yield session
        self.app=FastAPI();self.app.include_router(auth.router,prefix="/api/v1")
        self.app.dependency_overrides[get_db]=db
        @self.app.get("/owned/{application_id}")
        def owned(application_id:str, session=Depends(get_db), customer=Depends(current_customer)):
            from uuid import UUID
            return {"id":str(_owned(session,UUID(application_id),customer).application_id)}
        self.client=TestClient(self.app)
        self.headers={"Origin":"http://localhost:5173"}
        auth._auth_hits.clear()
    def register(self,email="one@example.test"):
        return self.client.post("/api/v1/auth/register",headers=self.headers,json={"email":email,"password":"Secure@123","first_name":"Maya","last_name":"Test"})
    def test_sessions_and_ownership(self):
        r=self.register();self.assertEqual(r.status_code,201);first=r.json()["customer_id"]
        self.assertIn("HttpOnly",r.headers["set-cookie"])
        self.assertIn("SameSite=strict",r.headers["set-cookie"])
        self.assertEqual(self.client.get("/api/v1/auth/me",headers={"X-Customer-Email":"attacker@test"}).json()["customer_id"],first)
        with Session(self.engine) as db:
            customer=db.scalar(select(Customer).where(Customer.email=="one@example.test"))
            app=Application(customer_id=customer.customer_id);db.add(app);db.commit();app_id=str(app.application_id)
        self.assertEqual(self.client.get("/owned/"+app_id).status_code,200)
        self.register("two@example.test")
        self.assertEqual(self.client.get("/owned/"+app_id).status_code,404)
        token=self.client.cookies.get("homeflow_session")
        self.assertEqual(self.client.post("/api/v1/auth/logout",headers=self.headers).status_code,200)
        self.client.cookies.set("homeflow_session",token)
        self.assertEqual(self.client.get("/api/v1/auth/me").status_code,401)
    def test_password_reset_and_replay(self):
        self.register();token=self.client.cookies.get("homeflow_session")
        emails=[]
        class SMTP:
            def __init__(self,*a,**k): pass
            def __enter__(self): return self
            def __exit__(self,*a): pass
            def send_message(self,msg): emails.append(msg)
        from unittest.mock import patch
        with patch.object(auth.smtplib,"SMTP",SMTP):
            known=self.client.post("/api/v1/auth/forgot-password",headers=self.headers,json={"email":"one@example.test"})
            unknown=self.client.post("/api/v1/auth/forgot-password",headers=self.headers,json={"email":"unknown@example.test"})
        self.assertEqual(known.json(),unknown.json());self.assertEqual(len(emails),1)
        reset_token=emails[0].get_content().split("#reset=")[1].split()[0]
        body={"token":reset_token,"password":"NewSecure@123"}
        self.assertEqual(self.client.post("/api/v1/auth/reset-password",headers=self.headers,json=body).status_code,200)
        self.assertEqual(self.client.get("/api/v1/auth/me").status_code,401)
        self.assertEqual(self.client.post("/api/v1/auth/reset-password",headers=self.headers,json=body).status_code,400)
        self.assertEqual(self.client.post("/api/v1/auth/login",headers=self.headers,json={"email":"one@example.test","password":body["password"]}).status_code,200)
    def test_expiry_lockout_and_rate_limit(self):
        self.register()
        with Session(self.engine) as db:
            session=db.scalar(select(AuthSession));session.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.commit()
        self.assertEqual(self.client.get("/api/v1/auth/me").status_code,401)
        body={"email":"one@example.test","password":"wrong-password-123"}
        for _ in range(5): self.assertEqual(self.client.post("/api/v1/auth/login",headers=self.headers,json=body).status_code,401)
        self.assertEqual(self.client.post("/api/v1/auth/login",headers=self.headers,json=body).status_code,429)
        auth._auth_hits.clear()
        for _ in range(15): self.client.post("/api/v1/auth/forgot-password",headers=self.headers,json={"email":"unknown@example.test"})
        self.assertEqual(self.client.post("/api/v1/auth/forgot-password",headers=self.headers,json={"email":"unknown@example.test"}).status_code,429)
    def test_rejects_spoofing_origin_and_weak_password(self):
        self.assertEqual(self.client.get("/api/v1/auth/me",headers={"X-Customer-Email":"one@example.test"}).status_code,401)
        self.assertEqual(self.client.post("/api/v1/auth/register",headers={"Origin":"https://evil.test"},json={"email":"a@test","password":"Secure@123","first_name":"A","last_name":"B"}).status_code,403)
        self.assertEqual(self.client.post("/api/v1/auth/register",headers=self.headers,json={"email":"a@test","password":"short","first_name":"A","last_name":"B"}).status_code,422)
        self.register();self.assertEqual(self.register().status_code,409)
    def test_new_password_policy(self):
        from pydantic import ValidationError
        for model, extra in ((auth.Registration, {"email":"a@test", "first_name":"A", "last_name":"B"}), (auth.ResetBody, {"token":"x"*32})):
            self.assertEqual(model(password="Abcdef1@x", **extra).password, "Abcdef1@x")
            for password in ("Abcd1@xy", "abcdef1@x", "ABCDEF1@X", "Abcdefg@x", "Abcdef12x", "Abcdef1 x"):
                with self.assertRaises(ValidationError): model(password=password, **extra)
        self.assertEqual(auth.Credentials(email="a@test",password="old-password").password,"old-password")
    def test_income_requires_answers(self):
        from app.api.v1.applications import _income_errors
        self.assertTrue(_income_errors({}, []))
        self.assertTrue(_income_errors({"employmentStatus":"Retired"}, []))
        self.assertFalse(_income_errors({"employmentStatus":"Retired","pensionIncome":"0"}, []))
        self.assertTrue(_income_errors({"employmentStatus":"Employed"}, [{"employer_name":"Company","base":0}]))
        self.assertFalse(_income_errors({"employmentStatus":"Employed"}, [{"employer_name":"Company","base":1000}]))
if __name__=="__main__":unittest.main()

