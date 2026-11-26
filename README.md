# FinPath

Personal finance, cash flow, and net worth intelligence platform (India-first, INR default) built with transparent, reproducible data-engineering practices.

## Architecture (MVP)
- **Core Domain (`packages/finpath_core`)**: Pure, stateless Python functions using `Decimal` for all money math.
- **Backend (`backend/`)**: FastAPI, SQLAlchemy 2.0 (async), Alembic migrations, `pwdlib` (Argon2) + JWT auth, PostgreSQL Row-Level Security (`finpath_app` non-superuser role).
- **Data & Observability (added in Sprints 2–5)**: MinIO (raw CSV + Parquet archival), dbt Core on PostgreSQL, Apache Airflow DAG, Great Expectations, Prometheus + Grafana, React + TypeScript dashboard.

## Quick Start (Windows PowerShell)

1. Copy environment template and start Postgres + run migrations:
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

API docs are available at `http://localhost:8000/docs` and health check at `http://localhost:8000/api/v1/health`.

## Documentation
- [Sprint Plan & RAM Profiles](docs/sprint_plan.md)
- [Data Model & ERD](docs/erd.md)
- [Deferred Post-MVP Scope](docs/later_scope.md)
