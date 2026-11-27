"""Statement upload, import status, and row-error resolution endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_rls_session
from app.core.config import get_settings
from app.db.models import ImportBatch, ImportRowError, User
from app.schemas.imports import (
    ImportBatchRead,
    ImportRowErrorRead,
    ResolveImportErrorRequest,
)
from app.services import imports as import_service
from app.services.storage import get_storage

router = APIRouter(prefix="/imports", tags=["imports"])


@router.post("", response_model=ImportBatchRead, status_code=status.HTTP_201_CREATED)
async def upload_statement(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
    account_id: Annotated[UUID, Form()],
    file: Annotated[UploadFile, File()],
    parser_name: Annotated[str, Form()] = "bank_csv",
) -> ImportBatch:
    """Upload a bank statement, archive it, parse rows, and deduplicate transactions."""
    settings = get_settings()
    content = await file.read(settings.max_import_file_bytes + 1)
    if len(content) > settings.max_import_file_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {settings.max_import_file_bytes} byte upload limit",
        )
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    try:
        return await import_service.process_import(
            session,
            get_storage(),
            user_id=current_user.id,
            account_id=account_id,
            file_name=file.filename or "statement.csv",
            content=content,
            parser_name=parser_name,
        )
    except import_service.UnknownParserError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown parser: {parser_name}",
        ) from exc
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Account not found"
        ) from exc
    except import_service.InactiveAccountError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Account '{exc}' is inactive; reactivate it before importing",
        ) from exc


@router.get("", response_model=list[ImportBatchRead])
async def list_import_batches(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
    account_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ImportBatch]:
    """List recent import batches for the current user."""
    return await import_service.list_batches(
        session, current_user.id, account_id=account_id, limit=limit
    )


@router.get("/{batch_id}", response_model=ImportBatchRead)
async def get_import_batch(
    batch_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
) -> ImportBatch:
    """Fetch one import batch."""
    batch = await import_service.get_batch(session, current_user.id, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import not found")
    return batch


@router.get("/{batch_id}/errors", response_model=list[ImportRowErrorRead])
async def list_import_errors(
    batch_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
) -> list[ImportRowError]:
    """List row-level errors for an import batch."""
    batch = await import_service.get_batch(session, current_user.id, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import not found")
    return await import_service.list_row_errors(session, current_user.id, batch_id)


@router.post(
    "/{batch_id}/errors/{error_id}/resolve",
    response_model=ImportRowErrorRead,
)
async def resolve_import_error(
    batch_id: UUID,
    error_id: UUID,
    payload: ResolveImportErrorRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
) -> ImportRowError:
    """Correct or ignore a single unparseable statement row."""
    corrected_payload = (
        payload.corrected_payload.model_dump(mode="json")
        if payload.corrected_payload is not None
        else None
    )
    try:
        error = await import_service.resolve_row_error(
            session,
            current_user.id,
            batch_id,
            error_id,
            resolution=payload.resolution,
            corrected_payload=corrected_payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if error is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Import row error not found"
        )
    return error
