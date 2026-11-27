# FinPath

Personal finance, cash flow, and net worth intelligence platform (India-first, INR default) built with transparent, reproducible data-engineering practices.

## Architecture (MVP)
- **Core Domain (`packages/finpath_core`)**: Pure, stateless Python functions using `Decimal` for all money math.
- **Backend (`backend/`)**: FastAPI, SQLAlchemy 2.0 (async), Alembic migrations, `pwdlib` (Argon2) + JWT auth, PostgreSQL Row-Level Security (`finpath_app` non-superuser role).
- **Data & Observability (added in Sprints 2–5)**: S3-compatible object storage (RustFS locally; MinIO API) for raw CSV + Parquet archival, dbt Core on PostgreSQL, Apache Airflow DAG, Great Expectations, Prometheus + Grafana, React + TypeScript dashboard.

## Quick Start (Windows PowerShell)

1. Copy environment template and start Postgres, the S3-compatible object store, and run migrations:
   ```powershell
   .\scripts\setup.ps1
   ```
2. Start the API:
   ```powershell
   .\scripts\dev.ps1
   ```
3. Run lint, typecheck, and tests (including PostgreSQL RLS isolation tests):
   ```powershell
   .\scripts\test.ps1
   ```
4. Generate the deterministic synthetic demo dataset (CSV + JSON + Parquet):
   ```powershell
   .\scripts\seed.ps1
   ```

API docs are available at `http://localhost:8000/docs` and health check at `http://localhost:8000/api/v1/health`. The S3 object-store console is at `http://localhost:9001` (`minioadmin` / `minioadmin`). Local development uses RustFS (Apache-2.0, S3-compatible) because MinIO's public images and binaries were withdrawn in 2026; the storage adapter remains S3/MinIO-compatible.

## Implemented API (Sprints 1–2)

| Area | Endpoints |
|---|---|
| Auth | `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `POST /api/v1/auth/refresh`, `GET/PATCH/DELETE /api/v1/me` |
| Accounts | `GET/POST /api/v1/accounts`, `GET/PATCH/DELETE /api/v1/accounts/{id}` (derived balances; `409` unless `confirm_delete_transactions=true`) |
| Imports | `POST/GET /api/v1/imports`, `GET /api/v1/imports/{id}`, `GET /api/v1/imports/{id}/errors`, `POST /api/v1/imports/{id}/errors/{error_id}/resolve` |

Money is always serialised as a fixed 4-decimal string (for example `"12000.2500"`) to avoid floating-point loss. Raw uploads and parsed `rows.parquet` files are archived in S3-compatible object storage (RustFS locally) under `raw/{user_id}/{batch_id}/` and `parsed/{user_id}/{batch_id}/`.


## Documentation
- [Sprint Plan & RAM Profiles](docs/sprint_plan.md)
- [Data Model & ERD](docs/erd.md)
- [Deferred Post-MVP Scope](docs/later_scope.md)
