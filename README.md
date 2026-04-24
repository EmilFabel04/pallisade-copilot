# Pallisade Co-Pilot

AI-powered data pipeline assistant. Ask questions about your data stack, debug issues, and trace lineage.

## Quick Start

### 1. Start the Backend

```bash
cd scanner
source venv/bin/activate
uvicorn api.app:app --reload --port 8000
```

### 2. Start the Frontend

```bash
npm run dev
```

### 3. Open the App

Visit http://localhost:3002/dashboard/assistant

## Features

- **AI Chat**: Ask questions about your data pipeline
- **Pipeline Builder**: Connect your data tools (Snowflake, dbt, Airflow, etc.)
- **Lineage Tracing**: Understand data dependencies

## Environment Variables

Create a `.env` file with:

```
DATABASE_URL=your_postgres_connection_string
NEXTAUTH_SECRET=your_secret
NEXTAUTH_URL=http://localhost:3002
SCANNER_API_URL=http://127.0.0.1:8000
SCANNER_SHARED_SECRET=generate_with_openssl_rand_hex_32
ANTHROPIC_API_KEY=your_anthropic_key
```

| Variable | Description |
|---|---|
| `SCANNER_SHARED_SECRET` | Shared secret for the Next.js ↔ FastAPI trust boundary. Generate with `openssl rand -hex 32`. Required (min 32 bytes) in production; a dev default is used otherwise. Must match between the Next.js `.env` and `scanner/.env`. |

### Security

FastAPI (`scanner/`) accepts requests only from Next.js, authenticated via the
`X-Internal-Auth: $SCANNER_SHARED_SECRET` header. FastAPI also binds to
loopback (`127.0.0.1`) in production and refuses to start on a non-loopback
interface. To call FastAPI directly during development (e.g., with curl):

```
curl -H "X-Internal-Auth: $SCANNER_SHARED_SECRET" \
     -H "X-Acting-User: $YOUR_USER_ID" \
     -H "X-Acting-Org: $YOUR_ORG_ID" \
     http://127.0.0.1:8000/api/v1/drivers
```

## Tech Stack

- **Frontend**: Next.js 15, React, Tailwind CSS
- **Backend**: FastAPI, Python
- **AI**: Anthropic Claude
- **Database**: PostgreSQL (via Prisma)

## Database schema changes

This project uses `prisma db push` to sync schema changes to the database.
There is no migration history — `prisma/migrations/` is intentionally absent.

```bash
# after editing prisma/schema.prisma
npm run db:push
```

To move to proper migrations later (e.g. when team size justifies it), baseline
from the current schema state:

```bash
npx prisma migrate dev --name baseline --create-only
npx prisma migrate resolve --applied baseline
```
