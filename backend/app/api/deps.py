"""FastAPI dependencies for authentication and RLS-scoped DB sessions."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
 
from app.core.security import decode_token
from app.db.models import User
from app.db.session import get_db_session, get_session_factory, set_rls_user_id

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> User:
    """Validate Bearer JWT access token and return the active User."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided",
        )
    try:
        user_id = decode_token(credentials.credentials, expected_type="access")
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
        ) from exc

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account not found or inactive",
        )
    return user


async def get_rls_session(
    current_user: Annotated[User, Depends(get_current_user)],
) -> AsyncIterator[AsyncSession]:
    """Yield an async DB session with app.current_user_id enforced for RLS."""
    factory = get_session_factory()
    async with factory() as session, session.begin():
        await set_rls_user_id(session, current_user.id)
        yield session
