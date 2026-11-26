# FinPath Later-Phase Scope (Deferred Post-MVP)

These capabilities and tables are intentionally excluded from the 31 Dec 2026 MVP migrations and runtime, and are documented here for post-MVP phases.

## Deferred Functional Modules
- **Investments & Market Data**: `investment_holdings`, `investment_transactions`, `portfolio_snapshots`, `market_prices`, `exchange_rates` (Alpha Vantage, CoinGecko, AMFI NAV, XIRR/CAGR, FIFO capital gains).
- **Multi-Currency**: FX conversion using dated `exchange_rates`.
- **AI Insights**: `ai_insights_log` (compute-first grounded OpenAI-compatible summaries with citations & non-advice disclaimers).
- **Goals & Scenarios**: `financial_goals` and compound-growth scenario analysis.
- **Additional Operational Tables**: `raw_import_records` (MVP stores raw CSV + parsed Parquet in MinIO), `merchants`, `recurring_transactions`, PDF statement parsing.
- **Scale & Streaming Infrastructure**:
  - Kafka + Debezium CDC + ClickHouse real-time sink (`fact_transactions`, `fact_investment_performance`, `fact_portfolio_valuation`, `dim_user`, `dim_account`, `dim_asset`, `dim_category`).
  - Kubernetes / Terraform deployment, Redis caching, OpenTelemetry tracing.

## Streaming Hook Design Note
Pure functions in `packages/finpath_core` (ingestion normalisation, deterministic fingerprinting, keyword categorisation) are stateless so they can be invoked identically by batch CSV imports (MVP) or a future Kafka/Debezium consumer without rewriting domain logic.
