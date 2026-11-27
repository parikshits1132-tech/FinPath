# Generate the deterministic synthetic demo dataset (CSV statements, JSON, Parquet)
$ErrorActionPreference = "Stop"

docker compose up -d postgres objectstore backend
docker compose run --rm backend python -m finpath_core.synthetic `
    --output-dir /app/data/synthetic `
    --users 100 `
    --months 12 `
    --seed 42

Write-Host "Synthetic dataset written to .\data\synthetic"
