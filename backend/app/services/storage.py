"""Object storage abstraction for raw statement and parsed Parquet archival.

Production uses any S3-compatible store (RustFS locally) through the boto3 S3
API. Tests use an in-memory implementation so the suite does not depend on an
external service.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Protocol

from app.core.config import get_settings


class ObjectStorage(Protocol):
    """Minimal S3-compatible object storage contract used by the import pipeline."""

    def put_object(self, key: str, data: bytes, content_type: str) -> None:
        """Store bytes under ``key``."""

    def get_object(self, key: str) -> bytes:
        """Read bytes stored under ``key``."""

    def delete_object(self, key: str) -> None:
        """Delete ``key`` if it exists."""

    def exists(self, key: str) -> bool:
        """Return whether ``key`` currently exists."""


class InMemoryObjectStorage:
    """Deterministic in-process storage used by the test suite."""

    def __init__(self) -> None:
        self._objects: dict[str, tuple[bytes, str]] = {}

    def put_object(self, key: str, data: bytes, content_type: str) -> None:
        self._objects[key] = (data, content_type)

    def get_object(self, key: str) -> bytes:
        try:
            return self._objects[key][0]
        except KeyError as exc:
            raise KeyError(f"Object not found: {key}") from exc

    def delete_object(self, key: str) -> None:
        self._objects.pop(key, None)

    def exists(self, key: str) -> bool:
        return key in self._objects

    def content_type(self, key: str) -> str | None:
        """Return the stored content type (test helper)."""
        return self._objects[key][1] if key in self._objects else None

    def clear(self) -> None:
        """Remove every stored object (test helper)."""
        self._objects.clear()

    def keys(self) -> list[str]:
        """Return stored keys sorted for assertions (test helper)."""
        return sorted(self._objects)


class S3ObjectStorage:
    """S3-compatible storage backed by boto3 (RustFS in local development)."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str,
        client: Any | None = None,
    ) -> None:
        self._bucket = bucket
        if client is None:
            import boto3  # noqa: PLC0415 - keep import cost out of test collection

            client = boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region,
            )
        self._client = client
        self._bucket_ready = False

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except Exception as exc:  # boto3 surfaces botocore.exceptions.ClientError
            code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
            if code in {"404", "NoSuchBucket", "NotFound"}:
                self._client.create_bucket(Bucket=self._bucket)
            else:
                raise
        self._bucket_ready = True

    def put_object(self, key: str, data: bytes, content_type: str) -> None:
        self._ensure_bucket()
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )

    def get_object(self, key: str) -> bytes:
        self._ensure_bucket()
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        body: bytes = response["Body"].read()
        return body

    def delete_object(self, key: str) -> None:
        self._ensure_bucket()
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def exists(self, key: str) -> bool:
        self._ensure_bucket()
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
        except Exception:
            return False
        return True


def build_storage() -> ObjectStorage:
    """Build the configured storage backend (uncached, useful for tests)."""
    settings = get_settings()
    if settings.storage_backend == "memory" or (
        settings.storage_backend == "auto" and settings.env == "test"
    ):
        return InMemoryObjectStorage()
    return S3ObjectStorage(
        endpoint_url=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        bucket=settings.minio_bucket,
        region=settings.minio_region,
    )


@lru_cache
def get_storage() -> ObjectStorage:
    """Return the process-wide object storage implementation."""
    return build_storage()


def reset_storage_cache() -> None:
    """Drop the cached storage instance (used between tests)."""
    get_storage.cache_clear()


def get_memory_storage() -> InMemoryObjectStorage:
    """Return the cached in-memory storage, asserting the test backend is active."""
    storage = get_storage()
    if not isinstance(storage, InMemoryObjectStorage):
        raise RuntimeError("In-memory storage is only available when STORAGE_BACKEND=memory")
    return storage
