# FinPath Setup Script (Windows PowerShell)
$ErrorActionPreference = "Stop"

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example"
}

docker compose build backend
docker compose up -d postgres
Write-Host "Waiting for Postgres and running Alembic migrations..."
docker compose run --rm backend alembic -c /app/backend/alembic.ini upgrade head
Write-Host "Setup complete. Run .\scripts\dev.ps1 to start the API."
