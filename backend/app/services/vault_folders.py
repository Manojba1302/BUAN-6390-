"""The customer's vault folders.

Files live in one flat store; a folder is only the file's logical_path in the database
(Oct 1 meeting). The default folders follow a common household document checklist, so the
vault is useful on its own, before any home loan. Customers can add folders of their own;
those names are kept in vault_folder so an empty folder still shows.
"""
import re

from fastapi import HTTPException
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.db.models import File
from app.services.versions import current_only

DEFAULT_FOLDERS = ("Legal", "Identification & Licenses", "People & Places", "Finances",
                   "Taxes", "Insurance & Property", "Other")
# Where an uploaded document goes when nobody picked a folder.
TAG_FOLDER = {"drivers_license": "Identification & Licenses", "ssn_card": "Identification & Licenses",
              "paystub": "Finances", "bank_statement": "Finances", "w2": "Taxes"}
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 &'().,-]{0,39}")
# What a stored-only document is ("Last Will", "Vehicle Title"): shown in the vault, nothing is extracted.
LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9 &'().,/-]{0,59}")

def default_for(tag: str) -> str:
    return TAG_FOLDER.get(tag, "Other")


def folder_of(logical_path: str | None, tag: str) -> str:
    """The folder a file shows in. Files saved before folders existed sit at "/"."""
    name = (logical_path or "").strip().strip("/")
    return name or default_for(tag)


def custom(db, customer_id) -> list[str]:
    rows = db.execute(text("SELECT name FROM vault_folder WHERE customer_id = :c ORDER BY lower(name)"),
                      {"c": customer_id}).scalars().all()
    return [name for name in rows if name not in DEFAULT_FOLDERS]


def resolve(db, customer_id, name: str) -> str | None:
    """The folder's stored spelling, matching case-insensitively, or None when it does not exist."""
    wanted = (name or "").strip().strip("/").casefold()
    return next((folder for folder in (*DEFAULT_FOLDERS, *custom(db, customer_id)) if folder.casefold() == wanted), None)


def listing(db, customer_id) -> list[dict]:
    """Every folder with how many files it holds, defaults first in checklist order."""
    files = db.execute(select(File.logical_path, File.document_tag).where(File.customer_id == customer_id, current_only())).all()
    counts: dict[str, int] = {}
    for path, tag in files:
        folder = folder_of(path, tag)
        counts[folder] = counts.get(folder, 0) + 1
    names = [*DEFAULT_FOLDERS, *custom(db, customer_id)]
    return [{"name": name, "default": name in DEFAULT_FOLDERS, "count": counts.get(name, 0)} for name in names]


def create(db, customer_id, name: str) -> str:
    clean = re.sub(r"\s+", " ", (name or "").strip())
    if not NAME.fullmatch(clean):
        raise HTTPException(400, "Use up to 40 letters, numbers, spaces or & ' ( ) . , - for a folder name.")
    if resolve(db, customer_id, clean):
        raise HTTPException(409, "You already have a folder with that name.")
    db.execute(text("INSERT INTO vault_folder (customer_id, name) VALUES (:c, :n)"), {"c": customer_id, "n": clean})
    db.commit()
    return clean


def remove(db, customer_id, name: str) -> None:
    """Delete a folder the customer made. Its files go back to their usual folder, nothing is deleted."""
    folder = resolve(db, customer_id, name)
    if folder is None:
        raise HTTPException(404, "Folder not found")
    if folder in DEFAULT_FOLDERS:
        raise HTTPException(409, "Built-in folders cannot be deleted.")
    db.execute(update(File).where(File.customer_id == customer_id, func.btrim(File.logical_path, "/") == folder)
               .values(logical_path="/"))
    db.execute(text("DELETE FROM vault_folder WHERE customer_id = :c AND name = :n"), {"c": customer_id, "n": folder})
    db.commit()


def path_for_upload(db, customer_id, requested: str | None, tag: str) -> str:
    """The logical path a new file is saved under: the chosen folder, or the usual one for its type."""
    if not (requested or "").strip().strip("/"):
        return "/" + default_for(tag)
    folder = resolve(db, customer_id, requested)
    if folder is None:
        raise HTTPException(400, "That folder does not exist. Choose another folder.")
    return "/" + folder


def set_label(db, file_id, label: str | None) -> None:
    """Remember what the customer said a document is. Blank means no label."""
    clean = re.sub(r"\s+", " ", (label or "").strip())
    if not clean:
        return
    if not LABEL.fullmatch(clean):
        raise HTTPException(400, "Use up to 60 letters, numbers, spaces or & ' ( ) . , / - to describe the document.")
    db.execute(text("""INSERT INTO vault_document_label (file_id, label) VALUES (:f, :l)
                       ON CONFLICT (file_id) DO UPDATE SET label = EXCLUDED.label"""), {"f": file_id, "l": clean})


def clear_label(db, file_id) -> None:
    db.execute(text("DELETE FROM vault_document_label WHERE file_id = :f"), {"f": file_id})


def label_of(db, file_id) -> str | None:
    value = db.execute(text("SELECT label FROM vault_document_label WHERE file_id = :f"), {"f": file_id}).scalar()
    return value if isinstance(value, str) else None
