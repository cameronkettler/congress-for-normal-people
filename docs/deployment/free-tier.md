# Free-Tier Deployment

This repo is shaped for a cheap public demo stack:

- Vercel Hobby for the Next.js app in `apps/web`
- Render Free Web Service for the FastAPI app in `apps/api`
- Supabase Free Postgres for `DATABASE_URL`
- GitHub Actions cron for daily polling

## Vercel

Create a Vercel project from the repo and set the root directory to `apps/web`.

Environment variables:

```text
NEXT_PUBLIC_API_BASE_URL=https://your-render-api.onrender.com
```

## Render

Create a Render Web Service from the repo using the API Dockerfile.

Suggested settings:

```text
Dockerfile path: apps/api/Dockerfile
Health check path: /health
```

Environment variables:

```text
DATABASE_URL=postgresql+psycopg://...
WEB_CORS_ORIGINS=https://your-vercel-app.vercel.app,http://localhost:3000
CONGRESS_API_KEY=
FEC_API_KEY=
LOBBYING_DISCLOSURE_API_KEY=
LOBBYING_API_LIVE=true
OPENAI_API_KEY=
OPENAI_API_LIVE=true
JOB_TOKEN=<long random token>
```

### Render Deploy Hook

Render's GitHub auto-deploy webhook can be supplemented with a GitHub Actions deploy hook trigger. This repo includes `.github/workflows/deploy-render.yml`, which runs after every push to `main` and sends a `POST` request to Render's Deploy Hook URL.

To configure it:

1. In Render, open the API service.
2. Go to Settings -> Deploy.
3. Copy the Deploy Hook URL.
4. In GitHub, open Repository -> Settings -> Secrets and Variables -> Actions.
5. Create a repository secret named:

```text
RENDER_DEPLOY_HOOK_URL
```

Set the secret value to the Render Deploy Hook URL.

Verification:

- The workflow appears under GitHub Actions as `Deploy Render API`.
- A merge to `main` triggers the workflow.
- The workflow's curl step succeeds.
- Render's event log shows a deployment shortly after the workflow runs.

## Supabase

Use the Supabase connection string as `DATABASE_URL`, but keep the SQLAlchemy driver prefix:

```text
postgresql+psycopg://USER:PASSWORD@HOST:PORT/postgres
```

## GitHub Actions Polling

Add repository secrets:

```text
CIVIC_PULSE_API_BASE_URL=https://your-render-api.onrender.com
CIVIC_PULSE_JOB_TOKEN=<same value as Render JOB_TOKEN>
```

The workflow in `.github/workflows/poll-new-bills.yml` runs every morning at 13:00 UTC and can also be triggered manually.

## Login And Topic Preferences

The app uses built-in email/password accounts and bearer sessions stored in Postgres. Alert topics are saved per user in `user_topic_preferences`; the in-app Poll button uses the signed-in user's enabled topics. The scheduled GitHub Actions poll uses the environment-level `MONITORING_TOPICS` list.
