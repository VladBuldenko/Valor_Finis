# Valor Finis

Personal finance product — a FastAPI backend and an Expo / React Native mobile app — for tracking expenses and income, managing accounts, budgets, and savings goals, processing receipts, and analyzing spending.

## Overview

Valor Finis is a monorepo containing:

- **`services/api`** — FastAPI modular-monolith backend; the source of truth for authentication, ownership, financial rules, balances, FX, and analytics;
- **`apps/mobile`** — Expo / React Native mobile client (the primary client).

Users can:

- record expenses (money spent) and income (money received);
- track real-world accounts (checking, savings, cash) whose balances are derived from a transaction ledger;
- optionally link an expense or income to the account it affected;
- manage categories and recurring budgets;
- fund and track savings goals through a goal transaction ledger;
- upload receipts, run OCR, and confirm them into expenses;
- analyze spending in their base currency.

The backend is deployed in production. The mobile app implements the core finance flows. See `docs/roadmap.md` for the current state and direction.

---

## Features

### Expenses
- Create, update, list, and delete expenses
- Category assignment
- Historical FX snapshot into the user's base currency
- Optional Account link (debit in the Account ledger)
- Amounts validated against storage limits (positive, up to 12 digits with 2 decimals)

### Income
- Create, update, list, and delete income (salary, freelance, refund, gift, other)
- Historical FX snapshot into the user's base currency
- Optional Account link (credit in the Account ledger)

### Accounts
- Checking, savings, and cash accounts
- Balance derived from the AccountTransaction ledger (may be negative)
- Optional opening balance, immutable manual adjustments
- Archive instead of delete once history exists; currency locked after history

### Categories
- Full CRUD
- Case-insensitive unique names per user
- Protected default categories
- Ownership validation

### Budgets
- Weekly, monthly, and yearly budgets, optionally per category
- Versioned budget history
- Budget status with pace, projection, and risk
- Duplicate budget protection

A budget is a spending allocation, not stored cash.

### Goals
- Savings targets with a GoalTransaction ledger (opening balance, contributions, withdrawals)
- Balance derived from the ledger, never negative; overfunding allowed
- Goal progress tracking; archive once history exists

Goals are not connected to Accounts.

### Receipts
- File upload with type and size validation
- Local or Supabase Storage
- OCR processing and parsed merchant, amount, currency, and date
- Confirmation (with corrections) into an expense, optionally linked to an Account
- Atomic, concurrency-safe confirmation

### Analytics
- Monthly and category spending summaries in base currency
- Spending trend and category trend
- Current-month spending forecast
- Budget status
- Goal progress

---

## Tech Stack

| Area | Technology |
|---|---|
| API | FastAPI, Python 3.9 |
| Validation | Pydantic 2 |
| Database | PostgreSQL 16 |
| ORM | SQLAlchemy 2 |
| Migrations | Alembic |
| Authentication | Supabase Auth / development auth |
| Mobile | Expo SDK 57, React Native, Expo Router, TanStack Query, TypeScript |
| Testing | pytest, FastAPI TestClient |
| Infrastructure | Docker, Docker Compose, Render (backend), Supabase (Auth, PostgreSQL, Storage) |
| CI | GitHub Actions |

---

## Architecture

The backend follows a layered architecture:

```text
HTTP Request
    ↓
Router
    ↓
Service
    ↓
Repository
    ↓
SQLAlchemy
    ↓
PostgreSQL
```

- **Router** — HTTP endpoints and dependency injection
- **Service** — business logic and transactions
- **Repository** — database access
- **Models** — SQLAlchemy persistence models
- **Schemas** — Pydantic API contracts

Domain exceptions are converted into HTTP responses through centralized FastAPI exception handlers.

The mobile app uses Supabase only for sign-in; all business data goes through the FastAPI API:

```text
Mobile app → Supabase Auth (session)
Mobile app → FastAPI API (Bearer token) → PostgreSQL
```

Account balances and goal balances are derived from their own ledgers. Income and expenses are the canonical records; an optional Account link is a synchronized projection in the Account ledger. See `docs/architecture.md`.

### Project Structure

```text
Valor_Finis/
├── .github/
│   └── workflows/
│       └── backend-ci.yml
│
├── apps/
│   └── mobile/               # Expo / React Native client
│       ├── app/              # Expo Router routes
│       └── src/              # API client, features, config
│
├── services/
│   └── api/
│       ├── alembic/          # Database migrations
│       ├── app/
│       │   ├── core/         # Configuration and error handling
│       │   ├── db/           # Database setup
│       │   ├── modules/      # Business modules
│       │   └── main.py
│       ├── tests/
│       ├── Dockerfile
│       └── requirements.txt
│
├── docs/
├── docker-compose.yml
└── README.md
```

Backend modules:

```text
auth
categories
expenses
budgets
goals
accounts
income
financial_settings
fx
receipts
analytics
```

---

## Quick Start with Docker

Requirements: Docker and Docker Compose.

Clone the repository:

```bash
git clone https://github.com/VladBuldenko/Valor_Finis.git
cd Valor_Finis
```

Build and start the backend:

```bash
docker compose up --build
```

Docker starts:

```text
FastAPI     → http://localhost:8000
PostgreSQL  → localhost:5433
```

Database migrations are applied automatically before the API starts.

Check the API:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{
  "status": "ok",
  "service": "valor-api",
  "version": "0.1.0"
}
```

Swagger documentation: http://localhost:8000/docs

Stop the application:

```bash
docker compose down
```

---

## Local Backend Development

From the API directory:

```bash
cd services/api
```

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Create local configuration:

```bash
cp .env.example .env
```

Apply migrations:

```bash
alembic upgrade head
```

Start the API:

```bash
uvicorn app.main:app --reload
```

### Environment

Main backend variables:

```text
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/valor

AUTH_MODE=development

SUPABASE_URL=
SUPABASE_PUBLISHABLE_KEY=

RECEIPT_STORAGE_DRIVER=local
RECEIPT_UPLOAD_DIR=uploads/receipts
RECEIPT_MAX_FILE_SIZE_MB=10
```

Real `.env` files and credentials must not be committed.

### Authentication

Two authentication modes are supported. `AUTH_MODE` is required; the API refuses to start without a supported value.

- **Development** — `AUTH_MODE=development`; requests use `X-User-Id: <UUID>` (local/test only).
- **Supabase** — `AUTH_MODE=supabase`; requests use `Authorization: Bearer <token>`.

The development header is disabled when Supabase authentication mode is active.

---

## Mobile App

The mobile client lives in `apps/mobile` (Expo SDK 57). It needs Node >= 22.13 and uses npm.

```bash
cd apps/mobile
npm install
npx expo start --lan
```

It reads the API URL and public Supabase settings from its local environment (for example `EXPO_PUBLIC_API_URL`). Before changing mobile code, read `apps/mobile/AGENTS.md`.

Implemented screens: sign-in, dashboard, expenses, income, accounts (with transaction history and adjustments), categories, budgets, goals (with funding history), analytics, and receipt upload/review.

Mobile checks:

```bash
npx tsc --noEmit
npm run lint
```

---

## Receipt Flow

```text
Upload receipt
    ↓
Validate file
    ↓
Store receipt
    ↓
OCR processing
    ↓
Parse detected data
    ↓
Confirm or correct values (optional Account)
    ↓
Create expense (+ optional Account debit)
    ↓
Mark receipt as confirmed
```

Receipt confirmation, expense creation, and the optional Account debit are performed atomically.

Receipt functionality is implemented; further Receipt/OCR expansion is deferred for now.

---

## Testing

The test suite deletes all application data between tests, so it must run against a dedicated database whose name ends with `_test` (for example `valor_test`) — never the development database `valor`. pytest refuses to start otherwise.

One-time setup of the local test database (from `services/api`):

```bash
createdb -h localhost -U postgres valor_test
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/valor_test alembic upgrade head
```

Run the complete backend test suite:

```bash
cd services/api
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/valor_test python -m pytest -v
```

Stop on the first failure:

```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/valor_test python -m pytest -x -v
```

The suite includes unit and integration tests (both against real PostgreSQL) for authentication, expenses, income, accounts and the account ledger, categories, budgets, goals and the goal ledger, receipts and OCR, FX, analytics, ownership rules, concurrency, database behavior, and exception handling. Tests never depend on live FX provider availability.

---

## Continuous Integration

GitHub Actions runs automatically on pushes to `main` and pull requests targeting `main`:

```text
PostgreSQL 16 (valor_test)
    ↓
Python 3.9
    ↓
Install dependencies
    ↓
Alembic migrations
    ↓
pytest
```

Workflow: `.github/workflows/backend-ci.yml`

---

## API

Main API prefix: `/api/v1`

Main resources:

```text
/api/v1/categories
/api/v1/expenses
/api/v1/income
/api/v1/accounts
/api/v1/budgets
/api/v1/goals
/api/v1/receipts
/api/v1/analytics
```

System endpoints: `/`, `/health`, `/docs`

See `docs/api-contract.md` for the contract and `docs/database-schema.md` for the schema.

---

## Status

- Backend: implemented and deployed in production (Render, with Supabase Auth, PostgreSQL, and Storage); production hardening performed, with further operational/security hardening ongoing.
- Mobile: core finance flows implemented.
- Current phase: financial ledger / money-flow foundation — not feature-complete.
- Next milestone: Account Transfers (specification first).

See `docs/roadmap.md`.

---

## License

See LICENSE.
