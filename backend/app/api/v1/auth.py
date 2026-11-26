"""Authentication and current-user profile endpoints."""

from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_rls_session
from app.core.logging import get_logger, sanitize_log_context
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.db.models import User
from app.db.session import get_db_session
from app.schemas.auth import (
    RefreshTokenRequest,
    TokenPairResponse,
    UserLoginRequest,
    UserRead,
    UserRegisterRequest,
    UserUpdateRequest,
)

router = APIRouter(tags=["auth"])
logger = get_logger(__name__)


@router.post("/auth/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register_user(
    payload: UserRegisterRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> User:
    """Register a new FinPath user with Argon2 password hashing."""
    user = User(
        email=payload.email.strip().lower(),
        password_hash=hash_password(payload.password),
        full_name=payload.full_name.strip(),
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        ) from exc
    await session.refresh(user)
    logger.info("user_registered %s", sanitize_log_context({"user_id": str(user.id)}))
    return user


@router.post("/auth/login", response_model=TokenPairResponse)
async def login_user(
    payload: UserLoginRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TokenPairResponse:
    """Authenticate by email and password and issue JWT access + refresh tokens."""
    email = payload.email.strip().lower()
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if (
        user is None
        or not user.is_active
        or not verify_password(payload.password, user.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    logger.info("user_logged_in %s", sanitize_log_context({"user_id": str(user.id)}))
    return TokenPairResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/auth/refresh", response_model=TokenPairResponse)
async def refresh_tokens(
    payload: RefreshTokenRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TokenPairResponse:
    """Issue a new access/refresh token pair from a valid refresh token."""
    try:
        user_id = decode_token(payload.refresh_token, expected_type="refresh")
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        ) from exc

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account not found or inactive",
        )

    return TokenPairResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


@router.get("/me", response_model=UserRead)
async def read_me(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    """Return the authenticated user's profile."""
    return current_user


@router.patch("/me", response_model=UserRead)
async def update_me(
    payload: UserUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
) -> User:
    """Update the authenticated user's full name."""
    result = await session.execute(select(User).where(User.id == current_user.id))
    user = result.scalar_one()
    user.full_name = payload.full_name.strip()
    await session.flush()
    await session.refresh(user)
    return user


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_rls_session)],
) -> Response:
    """Permanently delete the authenticated user and cascade-delete all owned data."""
    await session.execute(delete(User).where(User.id == current_user.id))
    logger.info("user_deleted %s", sanitize_log_context({"user_id": str(current_user.id)}))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
