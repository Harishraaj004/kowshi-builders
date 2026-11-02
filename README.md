# Kowshi Builders – AI Chat Agent

A website for a construction business with an AI chat agent (Claude), customer accounts, a project dashboard and an admin console.

**Stack:** FastAPI · PostgreSQL (psycopg 3) · Anthropic Claude API · TypeScript + Tailwind CSS (compiled to `static/`) · deployable on Vercel.

## Features

- **Chat agent** powered by Claude with a deterministic `estimate_construction_quote` tool (`app/tools.py`) and persistent conversation history.
- **Accounts:** email signup/login with emailed verification codes, optional Google Sign-In.
- **Customer dashboard** (`/dashboard`): projects, appointments, approval-document uploads.
- **Admin console** (`/admin`): clients, appointments (accept / request change), user and engineer management.

## Project layout

```
app/                FastAPI backend (main, auth, admin, projects, llm, tools, database, config, emailer)
frontend/           TypeScript + Tailwind sources and build tooling
static/             HTML pages and compiled JS/CSS served by FastAPI
vercel.json         Vercel config (function region)
.env.example        Template of all environment variables
```

## Run locally

Prerequisites: Python 3.11+, Node 18+, a PostgreSQL database, an [Anthropic API key](https://console.anthropic.com/settings/keys).

```bash
git clone https://github.com/Harishraaj004/kowshi-builders-chat-agent.git
cd kowshi-builders-chat-agent

python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env     # then fill in ANTHROPIC_API_KEY, DATABASE_URL, admin settings
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000 (chat), `/dashboard`, `/admin`, and `/docs` (API docs). Tables are created automatically on startup.

### Changing the frontend

```bash
cd frontend
npm install
npm run build        # or: npm run watch:css / npm run watch:js
```

Compiled files in `static/` are committed so the Vercel deploy needs no Node build — commit them after rebuilding.

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | yes | Claude API key |
| `DATABASE_URL` | yes | PostgreSQL URL (`postgresql://user:pass@host:5432/db`) |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | yes | Admin console login (created/updated on each start) |
| `ADMIN_EMAILS` | no | Comma-separated emails promoted to admin on signup |
| `GOOGLE_CLIENT_ID` | no | Enables Google Sign-In |
| `COOKIE_SECURE` | prod | Set `true` on HTTPS |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | prod | Sends verification codes; if `SMTP_HOST` is empty, codes print to the server log |
| `UPLOAD_DIR` | no | Where uploaded documents are stored (default `uploads`) |

Never commit `.env`; it is git-ignored.

## Deploy to Vercel

1. Create a hosted Postgres database reachable from the internet (e.g. [Neon](https://neon.tech), Supabase or Vercel Postgres) and copy its connection string (use `?sslmode=require`).
2. Go to [vercel.com/new](https://vercel.com/new), import `Harishraaj004/kowshi-builders-chat-agent`. Framework preset: **Other**; leave build/output settings empty.
3. Add the environment variables above (at least `ANTHROPIC_API_KEY`, `DATABASE_URL` (Neon pooled string), `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `COOKIE_SECURE=true`, SMTP settings, and `UPLOAD_DIR=/tmp/uploads`).
4. Deploy. Every push to `main` redeploys automatically.

Or from the CLI: `npm i -g vercel && vercel --prod`.

**Serverless caveats**
- Uploaded documents are written to `/tmp`, which is **ephemeral** on Vercel. For durable uploads, move storage to S3 / Vercel Blob (see `app/projects.py`).
- If you use Google Sign-In, add your Vercel domain to the OAuth client's authorized JavaScript origins.

## License

Private learning project.
