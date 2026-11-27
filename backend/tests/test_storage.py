"""Unit tests for the MinIO/S3 object storage adapter."""

from __future__ import annotations

import io
from typing import Any

import pytest

from app.services.storage import InMemoryObjectStorage, S3ObjectStorage


class FakeS3Client:
    """Tiny boto3 S3 client double used to verify the adapter contract."""

    def __init__(self) -> None:
        self.buckets: set[str] = set()
        self.objects: dict[tuple[str, str], bytes] = {}
        self.created: list[str] = []

    def head_bucket(self, Bucket: str) -> None:  # noqa: N803 - boto3 signature
        if Bucket not in self.buckets:
            raise FakeClientError("404")

    def create_bucket(self, Bucket: str) -> None:  # noqa: N803
        self.buckets.add(Bucket)
        self.created.append(Bucket)

    def put_object(self, Bucket: str, Key: str, Body: bytes, ContentType: str) -> None:  # noqa: N803
        self.objects[(Bucket, Key)] = Body

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        try:
            body = self.objects[(Bucket, Key)]
        except KeyError as exc:
            raise FakeClientError("NoSuchKey") from exc
        return {"Body": io.BytesIO(body)}

    def delete_object(self, Bucket: str, Key: str) -> None:  # noqa: N803
        self.objects.pop((Bucket, Key), None)

    def head_object(self, Bucket: str, Key: str) -> None:  # noqa: N803
        if (Bucket, Key) not in self.objects:
            raise FakeClientError("NoSuchKey")


class FakeClientError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


def test_s3_storage_bootstraps_bucket_and_round_trips_objects() -> None:
    """The adapter creates its bucket on demand and stores raw bytes."""
    client = FakeS3Client()
    storage = S3ObjectStorage(
        endpoint_url="http://minio:9000",
        access_key="key",
        secret_key="secret",
        bucket="finpath-test",
        region="us-east-1",
        client=client,
    )

    storage.put_object("raw/u/1/statement.csv", b"a,b\n1,2\n", "text/csv")
    assert client.created == ["finpath-test"]
    assert storage.exists("raw/u/1/statement.csv") is True
    assert storage.get_object("raw/u/1/statement.csv") == b"a,b\n1,2\n"

    storage.put_object("parsed/u/1/rows.parquet", b"PAR1data", "application/vnd.apache.parquet")
    assert client.created == ["finpath-test"]  # bucket is only created once

    storage.delete_object("raw/u/1/statement.csv")
    assert storage.exists("raw/u/1/statement.csv") is False


def test_s3_storage_propagates_unexpected_errors() -> None:
    """Non-404 bootstrap failures are not swallowed."""

    class DeniedClient(FakeS3Client):
        def head_bucket(self, Bucket: str) -> None:  # noqa: N803
            raise FakeClientError("AccessDenied")

    storage = S3ObjectStorage(
        endpoint_url="http://minio:9000",
        access_key="key",
        secret_key="secret",
        bucket="finpath-test",
        region="us-east-1",
        client=DeniedClient(),
    )
    with pytest.raises(FakeClientError):
        storage.put_object("k", b"v", "text/plain")


def test_in_memory_storage_helpers() -> None:
    """The in-memory backend exposes deterministic keys and content types."""
    storage = InMemoryObjectStorage()
    storage.put_object("a", b"1", "text/plain")
    storage.put_object("b", b"2", "text/csv")
    assert storage.keys() == ["a", "b"]
    assert storage.content_type("b") == "text/csv"
    storage.clear()
    assert storage.keys() == []
