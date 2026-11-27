"""Small PyArrow helpers shared by the synthetic generator and import pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _arrow_module() -> Any:
    try:
        import pyarrow as pa  # noqa: PLC0415 - optional dependency kept lazy
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency is declared in backend
        raise RuntimeError(
            "pyarrow is required for Parquet support. Install finpath-backend dependencies."
        ) from exc
    return pa


def records_to_parquet_bytes(records: list[dict[str, Any]]) -> bytes:
    """Serialise a list of flat records to an in-memory Parquet file."""
    pa = _arrow_module()
    import pyarrow.parquet as pq  # noqa: PLC0415

    table = pa.table({}) if not records else pa.Table.from_pylist(records)
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink, compression="snappy")
    return bytes(sink.getvalue().to_pybytes())


def write_parquet_file(records: list[dict[str, Any]], path: Path) -> None:
    """Write records to a Parquet file on disk."""
    pa = _arrow_module()
    import pyarrow.parquet as pq  # noqa: PLC0415

    table = pa.table({}) if not records else pa.Table.from_pylist(records)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path, compression="snappy")
