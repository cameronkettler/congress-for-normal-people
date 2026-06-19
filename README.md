# Civic Pulse

Civic Pulse is an agentic civic intelligence platform for understanding and monitoring United States federal legislation. It combines a Next.js demo interface, a FastAPI backend, LangGraph-style workflows, PostgreSQL persistence, and provider abstractions for Congress.gov, OpenFEC, and lobbying disclosure data.

## What It Demonstrates

- Agentic bill lookup and monitoring workflows
- External API integration boundaries
- Event-oriented ingestion jobs
- PostgreSQL-backed domain models
- Email notification composition
- Full-stack Docker development
- Documentation for architecture, APIs, and data flow

## Repository Layout

```text
apps/
  web/                 Next.js frontend
  api/                 FastAPI service
packages/
  agents/              Bill lookup and monitoring workflows
  ingestion/           Congress, FEC, and lobbying service clients
  jobs/                Polling and digest jobs
  notifications/       Email notification service
  db/                  Database session and ORM models
  shared/              Shared settings and domain schemas
docs/                  Architecture, API, and workflow documentation
tests/                 Backend and workflow tests
```

## Quick Start

1. Copy environment defaults:

   ```bash
   cp .env.example .env
   ```

2. Start the stack:

   ```bash
   docker compose up --build
   ```

3. Open the apps:

   - Web UI: http://localhost:3000
   - API docs: http://localhost:8000/docs

The app runs with deterministic demo data when external API keys are not configured. Add `CONGRESS_API_KEY`, `FEC_API_KEY`, and email settings in `.env` to connect real providers.

## API Highlights

- `GET /health` returns service status.
- `POST /api/bills/lookup` runs the bill intelligence workflow.
- `GET /api/monitoring/recent` lists recent monitored bills.
- `POST /api/monitoring/poll` polls for newly introduced bills and queues notifications.
- `GET /api/interests` lists enabled monitoring topics.
- `PATCH /api/interests/{topic}` toggles a topic.

## Development

Backend:

```bash
cd apps/api
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Frontend:

```bash
cd apps/web
npm install
npm run dev
```

Tests:

```bash
pytest
```

## Dev Scripts

Docker lifecycle helpers live in `bin/dev`.

PowerShell:

```powershell
.\bin\dev\serve.ps1 up
.\bin\dev\serve.ps1 down
```

Bash:

```bash
./bin/dev/serve up
./bin/dev/serve down
```

Supported commands are `up`, `down`, `restart`, `status`, and `logs`.

## Production Notes

This repository is intentionally modular. Provider clients are isolated under `packages/ingestion`, the workflows live under `packages/agents`, persistence is under `packages/db`, and the API only coordinates use cases. The next production steps would be adding migrations, Redis/Celery workers, user authentication, durable notification queues, and stricter source citation storage.
