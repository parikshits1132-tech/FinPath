# Run backend lint, typecheck, and pytest inside Docker Compose
$ErrorActionPreference = "Stop"
docker compose up -d postgres
docker compose run --rm backend ruff check /app/backend /app/packages/finpath_core
docker compose run --rm backend mypy /app/backend/app /app/packages/finpath_core/finpath_core
docker compose run --rm backend pytest /app/backend/tests -v
