# Run backend lint, typecheck, and pytest inside Docker Compose (matches CI)
$ErrorActionPreference = "Stop"
docker compose up -d postgres objectstore
docker compose run --rm -w /app backend ruff check backend packages
docker compose run --rm -w /app backend mypy --config-file backend/pyproject.toml packages/finpath_core/finpath_core backend/app
docker compose run --rm -w /app -e ENV=test -e STORAGE_BACKEND=memory backend pytest backend/tests -v
