param(
    [string]$Target = "head"
)
$ErrorActionPreference = "Stop"

docker compose up -d postgres
docker compose run --rm backend alembic -c /app/backend/alembic.ini upgrade $Target
