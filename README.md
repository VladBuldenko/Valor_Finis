# Valor Finis

Personal finance backend for tracking expenses, managing budgets, processing receipts, and monitoring financial goals.


## Overview

Valor Finis is a personal finance application built around a modular FastAPI backend.

The backend allows users to:

- track and categorize expenses;
- manage spending budgets;
- create and monitor financial goals;
- upload and process receipts;
- convert confirmed receipts into expenses;
- analyze monthly and category-based spending.

The current project focus is the backend API.

---

## Features

### Expenses
- Create, update, list, and delete expenses
- Category assignment
- User ownership isolation
- Positive amount validation

### Categories
- Full CRUD
- Case-insensitive unique names per user
- Protected default categories
- Ownership validation

### Budgets
- Full CRUD
- Category support
- Positive spending limits
- Duplicate budget protection

### Goals
- Full CRUD
- Target and current amount validation
- Goal progress tracking

### Receipts
- File upload
- File type and size validation
- Receipt storage
- OCR processing flow
- Parsed merchant, amount, currency, and date
- Receipt confirmation
- Atomic expense creation

### Analytics
- Monthly spending summary
- Spending by category
- Budget status
- Goal progress

---

## Tech Stack

| Area | Technology |
|---|---|
| API | FastAPI, Python 3.9 |
| Validation | Pydantic |
| Database | PostgreSQL 16 |
| ORM | SQLAlchemy |
| Migrations | Alembic |
| Authentication | Supabase Auth / development auth |
| Testing | pytest, FastAPI TestClient |
| Infrastructure | Docker, Docker Compose |
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

Each layer has a clear responsibility:

Router — HTTP endpoints and dependency injection
Service — business logic and transactions
Repository — database access
Models — SQLAlchemy persistence models
Schemas — Pydantic API contracts

Domain exceptions are converted into HTTP responses through centralized FastAPI exception handlers.

Project Structure
Valor_Finis/
├── .github/
│   └── workflows/
│       └── backend-ci.yml
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

Backend modules:

auth
categories
expenses
budgets
goals
receipts
analytics
Quick Start with Docker
Requirements
Docker
Docker Compose

Clone the repository:

git clone https://github.com/VladBuldenko/Valor_Finis.git
cd Valor_Finis

Build and start the application:

docker compose up --build

Docker starts:

FastAPI     → http://localhost:8000
PostgreSQL  → localhost:5433

Database migrations are applied automatically before the API starts.

Check the API:

curl http://localhost:8000/health

Expected response:

{
  "status": "ok",
  "service": "valor-api",
  "version": "0.1.0"
}

Swagger documentation:

http://localhost:8000/docs

Stop the application:

docker compose down
Local Development

From the API directory:

cd services/api

Create and activate a virtual environment:

python3 -m venv .venv
source .venv/bin/activate

Install dependencies:

python -m pip install -r requirements.txt

Create local configuration:

cp .env.example .env

Apply migrations:

alembic upgrade head

Start the API:

uvicorn app.main:app --reload
Environment

Main backend variables:

DATABASE_URL=postgresql://postgres:postgres@localhost:5432/valor

AUTH_MODE=development

SUPABASE_URL=
SUPABASE_PUBLISHABLE_KEY=

RECEIPT_STORAGE_DRIVER=local
RECEIPT_UPLOAD_DIR=uploads/receipts
RECEIPT_MAX_FILE_SIZE_MB=10

Real .env files and credentials must not be committed.

Authentication

Two authentication modes are supported.

Development
AUTH_MODE=development

Requests use:

X-User-Id: <UUID>
Supabase
AUTH_MODE=supabase

Requests use:

Authorization: Bearer <token>

The development header is disabled when Supabase authentication mode is active.

Receipt Flow
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
Confirm or correct values
    ↓
Create expense
    ↓
Mark receipt as confirmed

Receipt confirmation and expense creation are performed atomically.

Testing

Run the complete backend test suite:

cd services/api
python -m pytest -v

Stop on the first failure:

python -m pytest -x -v

The suite includes unit and integration tests for:

authentication;
expenses;
categories;
budgets;
goals;
receipts and OCR;
analytics;
ownership rules;
database behavior;
exception handling.
Continuous Integration

GitHub Actions runs automatically on:

pushes to main;
pull requests targeting main.

The pipeline performs:

PostgreSQL 16
    ↓
Python 3.9
    ↓
Install dependencies
    ↓
Alembic migrations
    ↓
pytest

Workflow:

.github/workflows/backend-ci.yml
API

Main API prefix:

/api/v1

Main resources:

/api/v1/categories
/api/v1/expenses
/api/v1/budgets
/api/v1/goals
/api/v1/receipts
/api/v1/analytics

System endpoints:

/
/health
/docs
Status

Backend MVP: complete

Implemented:

REST API
PostgreSQL persistence
authentication
receipt processing
analytics
Alembic migrations
centralized error handling
Docker environment
automated tests
GitHub Actions CI

Mobile and web clients can be added on top of the existing API.

License

See LICENSE.


