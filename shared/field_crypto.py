"""Encryption at rest for identifiers: SSN, licence and account numbers, date of birth.

Values are stored as "enc:v1:<Fernet token>" when FIELD_ENCRYPTION_KEY is set (a Fernet
key: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())").
Without a key, or without the cryptography package, values are stored as before, so the
feature can be switched on per environment. Plain values written earlier stay readable.
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache

log = logging.getLogger(__name__)

PREFIX = "enc:v1:"
# Extraction field names and application form field names that hold identifiers.
SENSITIVE = frozenset({"ssn", "employee_ssn", "license_number", "account_mask", "account_number", "date_of_birth", "dob"})


@lru_cache
def _cipher():
    key = os.getenv("FIELD_ENCRYPTION_KEY", "").strip()
    if not key:
        return None
    try:
        from cryptography.fernet import Fernet
        return Fernet(key.encode())
    except Exception as exc:                 # missing package or malformed key: keep working, say why
        log.warning("field encryption disabled: %s", exc)
        return None


def enabled() -> bool:
    return _cipher() is not None


def encrypt(field: str, value):
    """Encrypt a value of a sensitive field; anything else is returned unchanged."""
    cipher = _cipher()
    if cipher is None or field not in SENSITIVE or value is None or not isinstance(value, str) or value.startswith(PREFIX) or value == "":
        return value
    return PREFIX + cipher.encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(value):
    """Plain text for an encrypted value; unencrypted values pass through."""
    if not isinstance(value, str) or not value.startswith(PREFIX):
        return value
    cipher = _cipher()
    if cipher is None:
        log.warning("encrypted field found but FIELD_ENCRYPTION_KEY is not set")
        return None
    try:
        return cipher.decrypt(value[len(PREFIX):].encode("ascii")).decode("utf-8")
    except Exception:
        log.warning("encrypted field could not be decrypted with the configured key")
        return None
