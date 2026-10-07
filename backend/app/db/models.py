"""Backend ORM mappings, including database migrations 003 through 007.

Initialize PostgreSQL with db/init SQL, not Base.metadata.create_all().
Migration 007 installs the triggers that populate detail customer IDs.
Document chunks remain managed by the worker SQL rather than this ORM.
"""
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Date, DateTime,
    FetchedValue, ForeignKey, ForeignKeyConstraint, Integer, Numeric,
    SmallInteger, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.exc import CompileError


class Base(DeclarativeBase):
    pass


def _pk() -> Mapped[UUID]:
    return mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)


class _PartialSetNullForeignKey(ForeignKeyConstraint):
    """Represent PostgreSQL's column-specific SET NULL with SQLAlchemy 2.0.36."""

    def __init__(self, columns, refcolumns, *, null_column, **kwargs):
        if null_column not in columns:
            raise ValueError("The cleared column must belong to the foreign key.")
        self.null_column = null_column
        super().__init__(columns, refcolumns, **kwargs)


@compiles(_PartialSetNullForeignKey, "postgresql")
def _compile_partial_set_null(constraint, compiler, **kwargs):
    # Clear only the optional link; keep the required customer ID.
    base = compiler.visit_foreign_key_constraint(constraint, **kwargs)
    column = compiler.preparer.quote(constraint.null_column)
    return base + f" ON DELETE SET NULL ({column})"


@compiles(_PartialSetNullForeignKey)
def _unsupported_partial_set_null(constraint, compiler, **kwargs):
    raise CompileError("HomeFlow ownership constraints require PostgreSQL.")


class Customer(Base):
    __tablename__ = "customer"
    customer_id: Mapped[UUID] = _pk()
    subject: Mapped[str | None] = mapped_column(Text, unique=True)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    first_name: Mapped[str | None] = mapped_column(Text)
    last_name: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Application(Base):
    __tablename__ = "application"

    # Allow the application and its customer to be referenced together.
    __table_args__ = (
        UniqueConstraint(
            "application_id",
            "customer_id",
            name="application_id_customer_id_unique",
        ),
    )
    application_id: Mapped[UUID] = _pk()
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customer.customer_id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(Text, default="draft")
    current_step: Mapped[int] = mapped_column(SmallInteger, default=0)
    loan_purpose: Mapped[str | None] = mapped_column(Text)
    loan_type: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApplicationField(Base):
    __tablename__ = "application_field"

    __table_args__ = (
        # Keep the detail record linked to its application's customer.
        ForeignKeyConstraint(
            ["application_id", "customer_id"],
            ["application.application_id", "application.customer_id"],
            name="application_field_application_customer_fkey",
        ),
        # Require the source file to belong to the same customer.
        _PartialSetNullForeignKey(
            ["file_id", "customer_id"],
            ["file.file_id", "file.customer_id"],
            null_column="file_id",
            name="application_field_source_file_customer_fkey",
        ),
    )

    # PostgreSQL assigns the customer from the parent application.
    customer_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        nullable=False,
        server_default=FetchedValue(),
        server_onupdate=FetchedValue(),
    )
    application_id: Mapped[UUID] = mapped_column(
        ForeignKey("application.application_id", ondelete="CASCADE"), primary_key=True)
    field_name: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, default="user")
    confidence: Mapped[float | None] = mapped_column()
    file_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    page: Mapped[int | None] = mapped_column(SmallInteger)
    evidence_quote: Mapped[str | None] = mapped_column(Text)
    method: Mapped[str | None] = mapped_column(Text)
    review_state: Mapped[str] = mapped_column(Text, default="confirmed")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Employment(Base):
    __tablename__ = "employment"

    __table_args__ = (
        # Keep the detail record linked to its application's customer.
        ForeignKeyConstraint(
            ["application_id", "customer_id"],
            ["application.application_id", "application.customer_id"],
            name="employment_application_customer_fkey",
        ),
        # Require the source file to belong to the same customer.
        _PartialSetNullForeignKey(
            ["source_file_id", "customer_id"],
            ["file.file_id", "file.customer_id"],
            null_column="source_file_id",
            name="employment_source_file_customer_fkey",
        ),
    )

    # PostgreSQL assigns the customer from the parent application.
    customer_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        nullable=False,
        server_default=FetchedValue(),
        server_onupdate=FetchedValue(),
    )
    employment_id: Mapped[UUID] = _pk()
    application_id: Mapped[UUID] = mapped_column(ForeignKey("application.application_id", ondelete="CASCADE"))
    belongs_to: Mapped[str] = mapped_column(Text, default="borrower")
    employer_name: Mapped[str | None] = mapped_column(Text)
    position: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    self_employed: Mapped[bool] = mapped_column(Boolean, default=False)
    base: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    overtime: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    bonuses: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    commissions: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    pay_frequency: Mapped[str | None] = mapped_column(Text)
    source_file_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))


class Asset(Base):
    __tablename__ = "asset"

    __table_args__ = (
        # Keep the detail record linked to its application's customer.
        ForeignKeyConstraint(
            ["application_id", "customer_id"],
            ["application.application_id", "application.customer_id"],
            name="asset_application_customer_fkey",
        ),
        # Require the source file to belong to the same customer.
        _PartialSetNullForeignKey(
            ["source_file_id", "customer_id"],
            ["file.file_id", "file.customer_id"],
            null_column="source_file_id",
            name="asset_source_file_customer_fkey",
        ),
    )

    # PostgreSQL assigns the customer from the parent application.
    customer_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        nullable=False,
        server_default=FetchedValue(),
        server_onupdate=FetchedValue(),
    )
    asset_id: Mapped[UUID] = _pk()
    application_id: Mapped[UUID] = mapped_column(ForeignKey("application.application_id", ondelete="CASCADE"))
    belongs_to: Mapped[str] = mapped_column(Text, default="borrower")
    asset_type: Mapped[str | None] = mapped_column(Text)
    institution: Mapped[str | None] = mapped_column(Text)
    account_mask: Mapped[str | None] = mapped_column(Text)
    balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    as_of: Mapped[date | None] = mapped_column(Date)
    source_file_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))


class Liability(Base):
    __tablename__ = "liability"
    liability_id: Mapped[UUID] = _pk()
    application_id: Mapped[UUID] = mapped_column(ForeignKey("application.application_id", ondelete="CASCADE"))
    belongs_to: Mapped[str] = mapped_column(Text, default="borrower")
    liability_type: Mapped[str | None] = mapped_column(Text)
    creditor: Mapped[str | None] = mapped_column(Text)
    balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    monthly_payment: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    months_left: Mapped[int | None] = mapped_column(Integer)


class Declaration(Base):
    __tablename__ = "declaration"
    application_id: Mapped[UUID] = mapped_column(
        ForeignKey("application.application_id", ondelete="CASCADE"), primary_key=True)
    code: Mapped[str] = mapped_column(Text, primary_key=True)
    answer: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)


class File(Base):
    __tablename__ = "file"

    __table_args__ = (
        # Preserve the vault file when its application is deleted.
        _PartialSetNullForeignKey(
            ["application_id", "customer_id"],
            ["application.application_id", "application.customer_id"],
            null_column="application_id",
            name="file_application_customer_fkey",
        ),
        # Allow the file and its customer to be referenced together.
        UniqueConstraint(
            "file_id",
            "customer_id",
            name="file_id_customer_id_unique",
        ),

        # Prevent negative file metadata.
        CheckConstraint(
            "size_bytes >= 0",
            name="file_size_bytes_nonnegative",
        ),
        CheckConstraint(
            "page_count >= 0",
            name="file_page_count_nonnegative",
        ),
        CheckConstraint(
            "attempts >= 0",
            name="file_attempts_nonnegative",
        ),
    )
    file_id: Mapped[UUID] = _pk()
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customer.customer_id", ondelete="CASCADE"))
    application_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    document_tag: Mapped[str] = mapped_column(Text, nullable=False)
    original_name: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    checksum: Mapped[str | None] = mapped_column(Text)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    logical_path: Mapped[str] = mapped_column(Text, default="/")
    page_count: Mapped[int | None] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(Text, default="uploaded")
    error_detail: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FileClassification(Base):
    __tablename__ = "file_classification"
    file_id: Mapped[UUID] = mapped_column(
        ForeignKey("file.file_id", ondelete="CASCADE"), primary_key=True)
    selected_type: Mapped[str] = mapped_column(Text, nullable=False)
    detected_type: Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[list] = mapped_column(JSONB, default=list)
    mixed_document: Mapped[bool] = mapped_column(Boolean, default=False)
    model_name: Mapped[str | None] = mapped_column(Text)
    user_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    classified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Extraction(Base):
    __tablename__ = "extraction"
    extraction_id: Mapped[UUID] = _pk()
    file_id: Mapped[UUID] = mapped_column(ForeignKey("file.file_id", ondelete="CASCADE"))
    field_name: Mapped[str] = mapped_column(Text, nullable=False)
    value_raw: Mapped[str | None] = mapped_column(Text)
    value_normalized: Mapped[str | None] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(SmallInteger)
    evidence_quote: Mapped[str | None] = mapped_column(Text)
    bbox: Mapped[dict | None] = mapped_column(JSONB)
    method: Mapped[str | None] = mapped_column(Text)
    review_state: Mapped[str] = mapped_column(Text, default="proposed")
    corrected_value: Mapped[str | None] = mapped_column(Text)
    model_name: Mapped[str | None] = mapped_column(Text)
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DocumentMarkdown(Base):
    __tablename__ = "document_markdown"
    file_id: Mapped[UUID] = mapped_column(
        ForeignKey("file.file_id", ondelete="CASCADE"), primary_key=True)
    markdown_path: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[int | None] = mapped_column(Integer)


class AuditEvent(Base):
    __tablename__ = "audit_event"
    event_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    application_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    file_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    actor: Mapped[str] = mapped_column(Text, default="customer")
    action: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChecklistRequirement(Base):
    __tablename__ = "checklist_requirement"
    document_tag: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    required_count: Mapped[int] = mapped_column(SmallInteger, default=1)
    guidance: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0)

class AuthAccount(Base):
    __tablename__ = "auth_account"
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customer.customer_id"), primary_key=True)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class AuthSession(Base):
    __tablename__ = "auth_session"
    token_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customer.customer_id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class PasswordReset(Base):
    __tablename__ = "password_reset"
    token_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customer.customer_id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[bool] = mapped_column(Boolean, default=False)
