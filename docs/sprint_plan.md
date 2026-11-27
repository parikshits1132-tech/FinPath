# FinPath MVP Sprint Plan (26 Nov – 31 Dec 2026)

## Docker Compose RAM Profiles

| Profile | Services | Estimated Container RAM | Host Docker/WSL2 Budget |
|---|---|---|---|
| **Core (Default)** | `postgres`, `objectstore` (Sprint 2), `backend`, `frontend` (Sprint 3) | ~650–950 MB | **4 GB** |
| **Full Stack (`pipeline`, `monitoring`)** | Core + `airflow` (LocalExecutor on shared Postgres) + isolated `dbt` & `great_expectations` runners + `prometheus` + `grafana` | ~2.0–2.8 GB | **6 GB** |

## Revised 5-Sprint Table

| Sprint | Dates | Deliverables & Verification |
|---|---|---|
| **Sprint 1: Foundation, Auth & Schema** | **26 Nov – 2 Dec** | Repo setup, PowerShell scripts (`scripts/*.ps1`), 4 GB base `docker-compose.yml` (`postgres`, `backend`), Alembic migrations for all 11 MVP tables + `finpath_app` RLS policies, FastAPI auth (`pwdlib` Argon2 + JWT `/auth/*`, `/me`), cross-user RLS isolation tests, GitHub Actions CI. *(Account CRUD moved to Sprint 2.)* |
| **Sprint 2: Accounts, Object Storage/Parquet, Synthetic & CSV Import** | **3 Dec – 9 Dec** | Account CRUD (derived balances, safe delete policy). **S3-compatible object storage (RustFS locally)** added to Compose; raw upload + parsed `rows.parquet` stored per `import_batch`. Seeded synthetic generator (`~100` users, `12` months, including **12-month dated asset & liability valuations**). Bank CSV parser (adapted to supplied sample), fingerprint hashing `description_raw` + **occurrence counter** (tests for cleaner stability & same-day duplicates), `import_row_errors` + resolution endpoint. |
| **Sprint 3: Categorisation, Budgets, Assets/Liabilities & UI Part 1** | **10 Dec – 16 Dec** | System categories, keyword `categorisation_rules`, transfer flagging (`is_transfer`). Monthly `budgets` CRUD + `Decimal` cash flow / budget variance excluding `is_transfer` rows. **Assets (non-market) & Liabilities (non-CC) CRUD**. **UI Part 1**: Auth, Accounts, Transactions, CSV Import & error resolution views. |
| **Sprint 4: Net Worth Snapshots, dbt Core, Airflow & UI Part 2** | **17 Dec – 23 Dec** | Forward-only `net_worth_snapshots` builder (supports truthful dated synthetic history + optional `backfill_estimated=true` flagged `is_estimated=true`; zero credit-card double counting). **dbt Core** in isolated container/venv (`staging`, `dim_date`, `fact_cash_flow`, `fact_net_worth`). **Airflow DAG** calling `monthly_snapshot -> dbt_run -> dq_placeholder` via isolated runners. **UI Part 2**: Budgets, Assets/Liabilities, Net Worth 12-month trend views. |
| **Sprint 5: Great Expectations, Monitoring, UI Polish & Acceptance** | **24 Dec – 31 Dec** | **Great Expectations** checks on `financial_transactions` and `net_worth_snapshots` in isolated runner invoked by Airflow DAG. **Prometheus + Grafana** (API latency, import failures, last snapshot). **UI Part 3**: Unified Dashboard polish. CSV exports, 4 GB / 6 GB Docker Compose verification, MVP acceptance tests, `README.md`. |
