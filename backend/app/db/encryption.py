"""Transparent encryption of identifier fields for the ORM models.

Rows are encrypted as they are written and decrypted as they are loaded, so services keep
working with plain values in memory while the database stores ciphertext. Only fields named
in field_crypto.SENSITIVE are affected, and only when FIELD_ENCRYPTION_KEY is set.
"""
from sqlalchemy import event
from sqlalchemy.orm.attributes import set_committed_value

import field_crypto
from app.db.models import ApplicationField, Extraction

COLUMNS = {Extraction: ("value_raw", "value_normalized", "corrected_value", "evidence_quote"),
           ApplicationField: ("value", "evidence_quote")}


def _encrypt(mapper, connection, target):
    for column in COLUMNS[type(target)]:
        setattr(target, column, field_crypto.encrypt(target.field_name, getattr(target, column)))


def _decrypt(target, *_):
    for column in COLUMNS[type(target)]:
        value = getattr(target, column, None)
        if isinstance(value, str) and value.startswith(field_crypto.PREFIX):
            set_committed_value(target, column, field_crypto.decrypt(value))


def _restore(mapper, connection, target):
    _decrypt(target)


for model in COLUMNS:
    event.listen(model, "before_insert", _encrypt)
    event.listen(model, "before_update", _encrypt)
    event.listen(model, "after_insert", _restore)
    event.listen(model, "after_update", _restore)
    event.listen(model, "load", _decrypt)
    event.listen(model, "refresh", _decrypt)
