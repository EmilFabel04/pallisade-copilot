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
ANTHROPIC_API_KEY=your_anthropic_key
```

## Tech Stack

- **Frontend**: Next.js 15, React, Tailwind CSS
- **Backend**: FastAPI, Python
- **AI**: Anthropic Claude
- **Database**: PostgreSQL (via Prisma)
