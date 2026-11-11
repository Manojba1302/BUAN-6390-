"""Apply completed worker reads to draft applications without writes from GET routes."""
import logging
from threading import Event, Thread

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import prefill

log = logging.getLogger(__name__)
TABLE = """CREATE TABLE IF NOT EXISTS application_prefill_job (
    application_id uuid PRIMARY KEY REFERENCES application ON DELETE CASCADE,
    available_at timestamptz NOT NULL DEFAULT now())"""
SEED = """INSERT INTO application_prefill_job(application_id)
    SELECT application_id FROM application WHERE status='draft' ON CONFLICT DO NOTHING"""
TRIGGER = """CREATE OR REPLACE FUNCTION queue_application_prefill() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO application_prefill_job(application_id)
    SELECT d.application_id FROM application_document d JOIN application a USING(application_id)
    WHERE d.file_id=NEW.file_id AND a.status='draft' ORDER BY d.application_id
    ON CONFLICT(application_id) DO UPDATE SET available_at=now();
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS file_prefill_completed ON file;
CREATE TRIGGER file_prefill_completed AFTER UPDATE OF status ON file FOR EACH ROW
WHEN (NEW.status='completed' AND OLD.status IS DISTINCT FROM NEW.status)
EXECUTE FUNCTION queue_application_prefill()"""


def install(engine):
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(712845102)"))
        existing = conn.scalar(text("SELECT to_regclass('application_prefill_job')"))
        conn.execute(text(TABLE))
        conn.execute(text(TRIGGER))
        if not existing:
            conn.execute(text(SEED))


def run_one(engine):
    from app.api.v1.applications import _account_defaults
    from app.db.models import Application, Customer
    with Session(engine) as db, db.begin():
        aid = db.scalar(text("SELECT application_id FROM application_prefill_job WHERE available_at<=now() "
                             "ORDER BY available_at LIMIT 1 FOR UPDATE SKIP LOCKED"))
        if aid is None:
            return False
        try:
            with db.begin_nested():
                app = db.get(Application, aid, with_for_update=True)
                if app and app.status == "draft":
                    _account_defaults(db, app, db.get(Customer, app.customer_id))
                    prefill.apply_pending(db, application_id=aid)
                db.execute(text("DELETE FROM application_prefill_job WHERE application_id=:id"), {"id":aid})
        except Exception:
            log.exception("Draft prefill deferred for %s", aid)
            db.execute(text("UPDATE application_prefill_job SET available_at=now()+interval '1 minute' WHERE application_id=:id"), {"id":aid})
        return True


def start(engine):
    install(engine)
    stop = Event()
    def run():
        while not stop.is_set():
            try:
                if run_one(engine):
                    continue
            except Exception:
                log.exception("Draft prefill queue unavailable")
            stop.wait(1)
    Thread(target=run, daemon=True, name="application-prefill").start()
    return stop
