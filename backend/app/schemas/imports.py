"""Pydantic schemas for statement imports and row-error resolution."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

ImportStatus = Literal["pending", "processing", "completed", "partial_failed", "failed"]
ResolutionStatus = Literal["open", "corrected", "ignored"]


class ImportBatchRead(BaseModel):
    """Import batch metadata and counts."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    account_id: UUID
    parser_name: str
    file_name: str
    file_sha256: str
    raw_object_key: str
    parsed_parquet_key: str | None
    file_size_bytes: int
    status: ImportStatus
    total_rows: int
    inserted_rows: int
    duplicate_rows: int
    error_rows: int
    error_summary: dict[str, Any] | None
    created_at: datetime
    completed_at: datetime | None


class ImportRowErrorRead(BaseModel):
    """An unresolved or resolved row-level import error."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    import_batch_id: UUID
    row_number: int
    error_code: str
    error_message: str
    raw_row: dict[str, Any]
    resolution_status: ResolutionStatus
    corrected_payload: dict[str, Any] | None
    resolved_at: datetime | None


class CorrectedTransactionPayload(BaseModel):
    """Manually validated replacement for an unparseable statement row."""

    transaction_date: date
    direction: Literal["debit", "credit"]
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    description_raw: str = Field(min_length=1, max_length=1000)
    description_clean: str | None = Field(default=None, max_length=1000)
    reference_number: str | None = Field(default=None, max_length=200)


class ResolveImportErrorRequest(BaseModel):
    """Resolution for a single row error."""

    resolution: Literal["corrected", "ignored"]
    corrected_payload: CorrectedTransactionPayload | None = None

    @model_validator(mode="after")
    def validate_payload_for_resolution(self) -> ResolveImportErrorRequest:
        """Corrected rows require a payload; ignored rows must not carry one."""
        if self.resolution == "corrected" and self.corrected_payload is None:
            raise ValueError("corrected_payload is required when resolution is 'corrected'")
        if self.resolution == "ignored" and self.corrected_payload is not None:
            raise ValueError("corrected_payload must be omitted when resolution is 'ignored'")
        return self
