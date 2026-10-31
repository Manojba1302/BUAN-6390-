import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.api.v1 import auth, google_auth as g
from app.db.models import Customer, AuthAccount, AuthSession, GoogleIdentity, GoogleChallenge
from app.db.session import get_db
from app.core.security import password_hash

class GoogleTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
        for model in (Customer,AuthAccount,AuthSession,GoogleIdentity,GoogleChallenge): model.__table__.create(self.engine)
        def db():
            with Session(self.engine,expire_on_commit=False) as session: yield session
        app=FastAPI();app.include_router(g.router);app.include_router(auth.router);app.dependency_overrides[get_db]=db
        self.client=TestClient(app);self.client.headers["Origin"]="http://localhost:5173"
        auth._auth_hits.clear()
        self.config=patch.object(g.settings,"google_client_id","test-client");self.config.start()
        self.addCleanup(self.config.stop)
        self.claims={"sub":"google-subject","email":"google@example.test","email_verified":True,"given_name":"Test"}

    def send(self, password="", **override):
        nonce=self.client.post("/auth/google/challenge").json()["nonce"]
        with patch.object(g.id_token,"verify_oauth2_token",return_value={**self.claims,"nonce":nonce,**override}):
            return self.client.post("/auth/google/login",json={"credential":"signed-token","password":password})

    def test_new_and_returning_google_account(self):
        first=self.send();self.assertEqual(first.status_code,200)
        second=self.send();self.assertEqual(first.json()["customer_id"],second.json()["customer_id"])
        self.assertIn("HttpOnly",first.headers["set-cookie"])

    def test_existing_requires_password_before_link(self):
        with Session(self.engine) as db:
            customer=Customer(email=self.claims["email"]);db.add(customer);db.flush()
            db.add(AuthAccount(customer_id=customer.customer_id,email=customer.email,password_hash=password_hash("Testpass1!")))
            db.commit();customer_id=str(customer.customer_id)
        self.assertEqual(self.send().status_code,409)
        self.assertEqual(self.send(password="wrong").status_code,401)
        self.assertEqual(self.send(password="Testpass1!").json()["customer_id"],customer_id)

    def test_bad_nonce_and_unverified_email(self):
        self.assertEqual(self.send(nonce="wrong").status_code,401)
        self.assertEqual(self.send(email_verified=False).status_code,401)

    def test_missing_challenge_and_replay(self):
        self.assertEqual(self.client.post("/auth/google/login",json={"credential":"token"}).status_code,401)
        self.assertEqual(self.send().status_code,200)
        self.assertEqual(self.client.post("/auth/google/login",json={"credential":"token"}).status_code,401)

    def test_origin_and_disabled_configuration(self):
        self.assertEqual(self.client.post("/auth/google/challenge",headers={"Origin":"https://evil.test"}).status_code,403)
        with patch.object(g.settings,"google_client_id",""):
            self.assertEqual(self.client.post("/auth/google/challenge").status_code,503)

    def test_invalid_signature_is_rejected(self):
        self.client.post("/auth/google/challenge")
        with patch.object(g.id_token,"verify_oauth2_token",side_effect=ValueError("bad signature")):
            self.assertEqual(self.client.post("/auth/google/login",json={"credential":"token"}).status_code,401)

    def test_expired_challenge(self):
        from datetime import datetime, timedelta, timezone
        self.client.post("/auth/google/challenge")
        with Session(self.engine) as db:
            for row in db.scalars(select(GoogleChallenge)):
                row.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)
            db.commit()
        self.assertEqual(self.client.post("/auth/google/login",json={"credential":"token"}).status_code,401)

    def test_other_browser_cannot_use_challenge(self):
        self.client.post("/auth/google/challenge")
        self.client.cookies.clear()
        self.assertEqual(self.client.post("/auth/google/login",json={"credential":"token"}).status_code,401)

    def test_subject_preserves_account_when_email_changes(self):
        original=self.send().json()["customer_id"]
        changed=self.send(email="changed@example.test")
        self.assertEqual(changed.json()["customer_id"],original)

    def test_legacy_customer_cannot_be_claimed(self):
        with Session(self.engine) as db:
            db.add(Customer(email=self.claims["email"]));db.commit()
        self.assertEqual(self.send(password="Anything1!").status_code,409)

    def test_google_session_can_read_profile_and_logout_revokes_it(self):
        from app.core.security import COOKIE
        signed=self.send(); token=self.client.cookies.get(COOKIE)
        self.assertEqual(self.client.get("/auth/me").json()["customer_id"],signed.json()["customer_id"])
        self.assertEqual(self.client.post("/auth/logout").status_code,200)
        self.client.cookies.set(COOKIE,token)
        self.assertEqual(self.client.get("/auth/me").status_code,401)

    def test_verifier_receives_configured_audience(self):
        nonce=self.client.post("/auth/google/challenge").json()["nonce"]
        with patch.object(g.id_token,"verify_oauth2_token",return_value={**self.claims,"nonce":nonce}) as verify:
            self.assertEqual(self.client.post("/auth/google/login",json={"credential":"signed-token"}).status_code,200)
            self.assertEqual(verify.call_args.args[0],"signed-token")
            self.assertEqual(verify.call_args.args[2],"test-client")

    def test_verification_outage_is_retryable_and_does_not_create_account(self):
        self.client.post("/auth/google/challenge")
        with patch.object(g.id_token,"verify_oauth2_token",side_effect=g.TransportError("private internal error")):
            result=self.client.post("/auth/google/login",json={"credential":"token"})
        self.assertEqual(result.status_code,503)
        self.assertNotIn("private internal error",result.text)
        with Session(self.engine) as db:
            self.assertIsNone(db.scalar(select(Customer)))
            self.assertIsNone(db.scalar(select(AuthSession)))
        self.assertEqual(self.client.post("/auth/google/login",json={"credential":"token"}).status_code,401)
        self.assertEqual(self.send().status_code,200)

    def test_failed_link_attempts_lock_account_even_with_correct_password(self):
        with Session(self.engine) as db:
            customer=Customer(email=self.claims["email"]);db.add(customer);db.flush()
            db.add(AuthAccount(customer_id=customer.customer_id,email=customer.email,password_hash=password_hash("Testpass1!")))
            db.commit()
        for _ in range(5): self.assertEqual(self.send(password="wrong").status_code,401)
        self.assertEqual(self.send(password="Testpass1!").status_code,429)
        with Session(self.engine) as db:
            self.assertIsNone(db.scalar(select(GoogleIdentity)))
            self.assertIsNone(db.scalar(select(AuthSession)))

    def test_secure_cookie_configuration_and_no_cache(self):
        with patch.object(g.settings,"cookie_secure",True):
            response=self.client.post("/auth/google/challenge")
        cookie=response.headers["set-cookie"]
        for flag in ("Secure","HttpOnly","SameSite=strict"): self.assertIn(flag,cookie)
        self.assertEqual(response.headers["cache-control"],"no-store")
        self.assertEqual(self.client.get("/auth/google/config").headers["cache-control"],"no-store")

    def test_invalid_identity_claims_are_rejected(self):
        for override in ({"sub":""},{"sub":123},{"email":None},{"email":"invalid"}):
            with self.subTest(override=override): self.assertEqual(self.send(**override).status_code,401)

    def test_distinct_google_subject_cannot_replace_linked_identity(self):
        self.assertEqual(self.send().status_code,200)
        self.assertEqual(self.send(sub="different-subject").status_code,409)
        with Session(self.engine) as db:
            self.assertEqual(list(db.scalars(select(GoogleIdentity.subject))),["google-subject"])

    def test_email_password_login_still_works_after_google_link(self):
        with Session(self.engine) as db:
            customer=Customer(email=self.claims["email"]);db.add(customer);db.flush()
            db.add(AuthAccount(customer_id=customer.customer_id,email=customer.email,password_hash=password_hash("Testpass1!")))
            db.commit()
        linked=self.send(password="Testpass1!")
        self.client.post("/auth/logout")
        signed=self.client.post("/auth/login",json={"email":self.claims["email"],"password":"Testpass1!"})
        self.assertEqual(signed.status_code,200)
        self.assertEqual(signed.json()["customer_id"],linked.json()["customer_id"])
