"""PII-safe structured logging helpers."""

from __future__ import annotations

import logging
from typing import Any

_REDACTED_KEYS = frozenset({"email", "password", "password_hash", "token", "authorization"})


def sanitize_log_context(context: dict[str, Any]) -> dict[str, Any]:
    """Redact sensitive PII or credential keys before logging."""
    return {
        key: ("[REDACTED]" if key.lower() in _REDACTED_KEYS else value)
        for key, value in context.items()
    }


def get_logger(name: str) -> logging.Logger:
    """Return a configured application logger."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    return logging.getLogger(name)
