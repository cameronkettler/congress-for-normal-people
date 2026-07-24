# Congress For Normal People

Congress For Normal People is an agentic federal-legislation app that turns bill records into plain-English political context. It combines a Next.js frontend, a FastAPI backend, PostgreSQL persistence, account-scoped monitoring topics, location-based representative lookup, and provider integrations for Congress.gov, OpenFEC, Lobbying Disclosure Act filings, Census geocoding, optional SerpAPI, and OpenAI.

The goal is simple: see what changed across the policy issues you care about, understand why it matters, and drill into the underlying bills and official evidence.

## Current Features

- A personalized, topic-grouped policy briefing ranked by meaningful congressional changes.
- Immutable bill-change events captured for both new and previously tracked legislation.
- Grounded “What changed / Why it matters / Underlying bills” cards with deterministic fallbacks when AI is disabled.
- Authenticated `GET /api/briefing` and NDJSON `GET /api/briefing/stream` endpoints with per-user caching.
- Bill lookup by bill number or natural-language bill query.
- Human-readable bill labels, such as `H.Res. 11 (119th Congress)` and `S.Res. 2 (119th Congress)`, while internal cache/API IDs remain normalized.
- Plain-language political read with structured sections:
  - what the bill does
  - why supporters want it
  - why critics are concerned
  - how it could affect daily life
  - political and influence context
- Email/password accounts with bearer sessions.
- Profile settings with street address, address line 2, city, state, and ZIP.
- Congressional district and representative lookup from address data.
- Representative context from official signals:
  - sponsor
  - cosponsor
  - recorded House vote when available
  - public-source search context
  - labeled AI-assisted context
- Account-scoped watchlist topics.
- Watchlist topics used for monitoring, plus a separate topic filter for browsing tracked bills.
- Current-Congress tracked bills that can be clicked to run a report.
- Scheduled polling endpoint for GitHub Actions or another cron runner.
- Representative Deep Dive page for member profile context, recent sponsored legislation, campaign-finance coverage, election timing, public themes, and watchlist alignment.
- About page explaining how to use the application.
- Graceful handling for slow or unavailable external providers.

Briefings are cached by user, enabled topics, period, and generation version. A new relevant event or an interests change invalidates reuse. The application currently creates new tables at startup; production deployments should adopt Alembic migrations before rolling schema changes across multiple instances.

## Tech Stack

- `apps/web`: Next.js frontend
- `apps/api`: FastAPI service
- `packages/agents`: Bill lookup, monitoring, and report-generation workflows
- `packages/ingestion`: Congress.gov, OpenFEC, lobbying disclosure, Census, and search clients
- `packages/db`: SQLAlchemy models and sessions
- `packages/jobs`: Polling and digest construction
- `packages/notifications`: Email notification boundary
- `packages/shared`: Settings, schemas, and shared topic configuration
- `tests`: Backend, workflow, and integration-boundary tests

## Quick Start

Copy the example environment:

```bash
cp .env.example .env
```

Start the full Docker stack:

```bash
docker compose up --build
```

Open:

- Web UI: http://localhost:3000
- API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health

The app has deterministic fallbacks for some development paths, but the current representative and LLM features are most useful with real provider keys configured.

## Local Development

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
cd apps/web
npx tsc --noEmit
```

## Dev Scripts

Docker lifecycle helpers live in `bin/dev`.

PowerShell:

```powershell
.\bin\dev\serve.ps1 up
.\bin\dev\serve.ps1 logs
.\bin\dev\serve.ps1 down
```

Bash:

```bash
./bin/dev/serve up
./bin/dev/serve logs
./bin/dev/serve down
```

Supported commands are `up`, `down`, `restart`, `status`, and `logs`.

## Environment

Core:

```text
DATABASE_URL=postgresql+psycopg://...
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
WEB_CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
JOB_TOKEN=
```

Provider keys:

```text
CONGRESS_API_KEY=
FEC_API_KEY=
LOBBYING_DISCLOSURE_API_KEY=
OPENAI_API_KEY=
SERPAPI_API_KEY=
```

Important feature flags:

```text
LOBBYING_API_LIVE=true
OPENAI_API_LIVE=true
SERPAPI_ENABLED=true
```

Representative-context search:

```text
REP_POSITION_SEARCH_RESULTS=5
```

Monitoring:

```text
CONGRESS_CURRENT_CONGRESS=119
MONITORING_POLL_LIMIT=10
MONITORING_POLL_MAX_FETCH=50
MONITORING_TOPICS=Artificial Intelligence,Agriculture,...
```

`CONGRESS_CURRENT_CONGRESS` constrains monitoring and tracked bills to the active Congress. `MONITORING_POLL_LIMIT` controls the Congress.gov page size, and `MONITORING_POLL_MAX_FETCH` controls how many recent current-Congress bills a poll can review.

Address-to-district lookup uses the public U.S. Census Geocoder and does not require an API key:

```text
CENSUS_GEOCODER_BASE_URL=https://geocoding.geo.census.gov/geocoder
```

Timeouts are configurable in `.env.example`, including `CONGRESS_API_TIMEOUT_SECONDS`, `CONGRESS_RECENT_API_TIMEOUT_SECONDS`, `OPENAI_API_TIMEOUT_SECONDS`, and provider-specific client timeouts.

## API Highlights

- `GET /health` returns service status.
- `POST /api/auth/register` creates an account.
- `POST /api/auth/login` creates a bearer session.
- `GET /api/auth/me` returns the signed-in account.
- `POST /api/bills/lookup` runs the bill lookup workflow.
- `GET /api/bills/lookup/stream` streams bill lookup progress and the final report as NDJSON.
- `POST /api/bills/representative-context` checks a specific representative against the current bill.
- `GET /api/monitoring/recent` lists cached recent bills.
- `POST /api/monitoring/poll` polls for newly introduced bills using the signed-in user's enabled topics.
- `POST /api/jobs/poll-new-bills` runs the scheduled environment-level poll job.
- `GET /api/interests` lists the signed-in user's monitoring topics.
- `PATCH /api/interests/{topic}` enables or disables one monitoring topic.
- `GET /api/profile` returns the signed-in user's profile and representatives.
- `PUT /api/profile/location` resolves an address to a congressional district and representatives.
- `GET /api/representatives/deep-dive/stream` streams representative deep-dive progress and results.

## Representative Context

For signed-in users with a saved address, bill reports include a `Your Representative Context` section. The backend first checks official or structured signals such as sponsor, cosponsor, recorded House votes, and recorded Senate votes when available. It then enriches the section with public research through OpenAI web search and optional SerpAPI results.

AI-generated interpretation is returned separately as `ai_context` and displayed in the UI as `AI-assisted context`. That note is meant to explain likely political rationale from the available evidence, not replace official vote or sponsorship data.

## Monitoring

Watchlist topics are stored per account in `user_topic_preferences`. The in-app Refresh Bills button uses the signed-in user's enabled topics. The scheduled job endpoint uses the environment-level `MONITORING_TOPICS` list and `JOB_TOKEN`.

Tracked bills are cached in the database and shown on the dashboard. The dashboard displays all tracked current-Congress bills by default, with a separate topic filter for browsing. Clicking a tracked bill runs a lookup report for that bill.

Polling uses the configured current Congress endpoint, such as `/bill/119`, instead of the all-Congresses feed. This prevents old metadata updates from surfacing bills from prior Congresses as if they were recent.

## Deployment

The cheap public-demo deployment path is:

- Vercel Hobby for `apps/web`
- Render Free Web Service for `apps/api`
- Supabase Free Postgres for `DATABASE_URL`
- GitHub Actions for scheduled polling and Render deploy hooks

See [docs/deployment/free-tier.md](docs/deployment/free-tier.md) for the exact Render, Vercel, Supabase, and GitHub Actions setup.

For Render, the API is intended to run from the Dockerfile:

```text
Dockerfile path: apps/api/Dockerfile
Health check path: /health
```

For Vercel, set:

```text
NEXT_PUBLIC_API_BASE_URL=https://your-render-api.onrender.com
```

For Render CORS, set:

```text
WEB_CORS_ORIGINS=https://your-vercel-app.vercel.app,http://localhost:3000
```

## Notes

- Infrastructure names still use `civic-pulse` in a few places, such as package names, local database defaults, storage keys, and existing deployment URLs. Those are intentionally left stable so existing local data and deployments keep working.
- The API creates tables at startup for this demo-stage project. A production version should add Alembic migrations.
- The next production steps are durable queues, stronger source citation storage, richer vote ingestion, migrations, and background workers for slow report generation.
