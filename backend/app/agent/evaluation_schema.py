"""Allowlisted object schema deliberately has no free-text content fields."""
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict

class Source(BaseModel):
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)
    source_ref: str = Field(pattern=r"^[0-9a-f]{64}$")
    page: int | None = Field(default=None, ge=1)
    lexical: float | None = None
    semantic: float | None = None

class Timings(BaseModel):
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)
    total_seconds: float = Field(ge=0)
    embedding_seconds: float | None = Field(default=None, ge=0)
    retrieval_seconds: float | None = Field(default=None, ge=0)
    first_token_seconds: float | None = Field(default=None, ge=0)
    generation_seconds: float | None = Field(default=None, ge=0)

class Record(BaseModel):
    model_config = ConfigDict(extra="ignore")
    schema_version: Literal[1]
    request_id: UUID
    created_at: datetime
    session_ref: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    route: Literal["unknown","scope","inventory","summary","calculation","comparison","field_lookup","rag","clarification","future_pay"]
    outcome: Literal["error","unavailable","answered","no_evidence","clarification","unsupported","out_of_scope","uncertain"]
    model_name: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9:._-]{1,80}$")
    context_tokens: int | None = Field(default=None, gt=0)
    max_output_tokens: int | None = Field(default=None, gt=0)
    timings: Timings
    sources: list[Source] = Field(default_factory=list)
    retrieved: list[Source] = Field(default_factory=list)
