"""Pydantic schemas for authentication and user profile endpoints."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserRegisterRequest(BaseModel):
    """Payload to create a new user account."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=120)


class UserLoginRequest(BaseModel):
    """Credentials for email/password login."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RefreshTokenRequest(BaseModel):
    """Refresh token payload."""

    refresh_token: str = Field(min_length=1)


class TokenPairResponse(BaseModel):
    """Access and refresh JWT pair."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserRead(BaseModel):
    """Public user profile representation."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str
    base_currency: str
    is_active: bool
    created_at: datetime


class UserUpdateRequest(BaseModel):
    """Fields allowed for self-service profile updates."""

    full_name: str = Field(min_length=1, max_length=120)
