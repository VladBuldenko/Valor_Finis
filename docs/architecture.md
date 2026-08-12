🧱 Architecture — Valor Finis

This document describes the current architecture of Valor Finis and the rules that should guide future development.

1. Architecture Overview

Valor Finis is designed as a modular monorepo.

The current implemented core is a FastAPI backend. Web and mobile clients can be added as separate applications in the same repository and consume the backend through its public API.

Valor_Finis/
├── apps/                  # Web / mobile clients
├── services/
│   └── api/               # FastAPI backend
├── docs/                  # Project documentation
├── .github/workflows/     # CI
└── docker-compose.yml     # Local infrastructure

The repository boundary is not the deployment boundary. Web, mobile, and API components may be built and deployed independently.

2. System Context

Web / Mobile Client
        │
        │ HTTP + JSON
        ↓
   Valor API
     FastAPI
        │
        ├── Supabase Auth
        │
        ├── Receipt storage / OCR flow
        │
        ↓
   PostgreSQL

The backend is the source of truth for:

financial business rules;

authentication and authorization;

resource ownership;

persistence;

receipt processing;

analytics.

Clients should not duplicate backend business rules.

3. Backend Architecture

The backend follows a layered modular architecture:

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

Router

Responsible for HTTP concerns:

routes;

request schemas;

response schemas;

status codes;

dependency injection;

authentication dependency.

Routers should not contain database queries or business logic.

Service

Responsible for application and business logic:

ownership validation;

domain rules;

transaction orchestration;

coordination between repositories/services;

conversion of database models into API responses.

Repository

Responsible for persistence:

SELECT;

INSERT;

UPDATE;

DELETE;

user-scoped database queries.

Repositories do not know about HTTP.

Schemas

Pydantic schemas define API input and output contracts.

Models

SQLAlchemy models define persistence structure, relationships, indexes, and database constraints.

4. Backend Modules

The current backend is divided by business capability:

app/modules/
├── auth/
├── categories/
├── expenses/
├── budgets/
├── goals/
├── receipts/
└── analytics/

Auth

Resolves the current user.

Supported modes:

development → X-User-Id
supabase    → Authorization: Bearer <token>

Development authentication is intended only for local development and tests.

Categories

Owns spending category rules, including:

user ownership;

case-insensitive uniqueness;

protection of default categories.

Expenses

Owns financial expense records and category relationships.

Budgets

Owns spending limits and duplicate-budget rules.

Goals

Owns financial goals and amount validation.

Receipts

Owns:

upload metadata;

local file storage coordination;

OCR processing;

parsed receipt data;

receipt status transitions;

confirmation into an expense.

Analytics

Reads financial data and returns derived summaries such as spending, budget status, and goal progress.

Analytics should remain read-oriented and should not become the owner of transactional financial data.

5. Module Boundaries

Modules may collaborate through services or clearly defined repository operations when required, but business ownership must remain explicit.

Example:

Receipt confirmation
        │
        ↓
Receipt Service
        │
        ├── validates receipt state
        │
        ├── prepares ExpenseCreate
        │
        ↓
Expenses Service
        │
        ↓
Expense Repository

The receipts module coordinates the workflow, while the expenses module remains responsible for creating a valid expense.

Avoid circular dependencies and direct cross-module database manipulation where a domain service already owns that behavior.

6. Authentication and Ownership

Authentication identifies the current user before business operations are executed.

Request
   ↓
get_current_user
   ↓
CurrentUser.id
   ↓
Router
   ↓
Service / Repository
   ↓
user-scoped query

Every user-owned resource must be queried using the authenticated user identifier.

The client must never be trusted to declare ownership of a resource.

Example principle:

resource.id + authenticated user_id

not:

resource.id only

This prevents one user from reading or modifying another user's data.

7. Error Handling

Business failures are represented as domain exceptions.

Service
   ↓
Domain Error
   ↓
Global Exception Handler
   ↓
HTTP Response

Centralized mappings live in:

app/core/exception_handlers.py

Example:

CategoryNotFoundError
        ↓
404
{
  "detail": "Category not found."
}

This keeps routers small and prevents repetitive HTTP error mapping across modules.

Authentication-specific failures may still originate from the authentication dependency because they belong directly to the HTTP authentication boundary.

8. Database Architecture

Valor Finis uses:

FastAPI
   ↓
SQLAlchemy
   ↓
PostgreSQL

Main persisted entities:

categories
expenses
budgets
goals
receipts

Important relationships:

Category
   ├── Expense
   └── Budget

Receipt
   └── Expense

Important invariants should be protected at both application and database levels when appropriate.

Examples:

positive financial amounts;

foreign keys;

unique category names per user;

duplicate budget prevention.

9. Database Migrations

Alembic is the only supported mechanism for schema evolution.

Model/schema change
        ↓
Alembic migration
        ↓
alembic upgrade head
        ↓
PostgreSQL

Rules:

every schema change requires a migration;

migrations must be versioned;

the full migration chain must work from an empty database;

production schema changes must not depend on manual SQL steps.

10. Receipt Processing Architecture

Receipt processing is a multi-step workflow:

Upload
  ↓
Validate file
  ↓
Store file
  ↓
Create receipt record
  ↓
OCR processing
  ↓
Parse detected values
  ↓
Processed receipt
  ↓
User confirmation
  ↓
Create expense
  ↓
Confirmed receipt

Typical receipt states:

uploaded
processing
processed
confirmed
failed

OCR Failure

When OCR processing fails:

processing
    ↓
failed

The receipt can later be processed again when its state allows it.

Confirmation Transaction

Receipt confirmation and expense creation form one transaction boundary.

BEGIN

create expense
update receipt → confirmed
link receipt → expense

COMMIT

On failure:

ROLLBACK

This prevents a receipt from being confirmed without its expense, or an expense from being created while receipt confirmation fails.

11. Configuration

Runtime configuration is environment-based.

Main variables include:

DATABASE_URL
AUTH_MODE
SUPABASE_URL
SUPABASE_PUBLISHABLE_KEY
RECEIPT_STORAGE_DRIVER
RECEIPT_UPLOAD_DIR
RECEIPT_MAX_FILE_SIZE_MB

Rules:

secrets never belong in Git;

.env is local-only;

.env.example documents required configuration;

unsupported authentication modes should fail fast.

12. Local Infrastructure

Docker Compose provides a reproducible local environment:

docker compose up
        │
        ├── PostgreSQL
        │      ↓
        │   healthcheck
        │
        ↓
      API
        │
        ├── alembic upgrade head
        │
        └── uvicorn

Current local ports:

API         → localhost:8000
PostgreSQL  → localhost:5433

Inside the Docker network, the API connects to PostgreSQL through:

db:5432

Persistent Docker volumes keep database data and receipt uploads between normal container restarts.

13. Continuous Integration

GitHub Actions validates backend changes.

Push / Pull Request
        ↓
PostgreSQL 16
        ↓
Python 3.9
        ↓
Install dependencies
        ↓
Alembic upgrade head
        ↓
pytest

A migration failure or test failure makes the workflow fail.

CI is part of the architecture because it continuously verifies that the application can be reconstructed from source code and migrations.

14. Testing Architecture

The backend uses two primary test levels.

Unit Tests

Validate isolated business behavior.

Typical targets:

service rules;

parsers;

authentication helpers;

validation;

exception mappings.

Integration Tests

Validate the complete backend path:

HTTP
 ↓
Router
 ↓
Service
 ↓
Repository
 ↓
PostgreSQL

Integration tests must verify ownership, API contracts, persistence, and important failure scenarios.

15. Scaling Strategy

Valor Finis should remain a modular application until a concrete requirement justifies extracting infrastructure or services.

Preferred evolution:

Modular Monolith
       ↓
Measure real usage
       ↓
Identify bottleneck / isolation need
       ↓
Extract only the required component

Possible future candidates could include OCR workers or asynchronous processing, but only when justified by real load, reliability, or operational requirements.

Do not introduce microservices, queues, caching, or distributed infrastructure only because they are considered modern.

16. Architectural Rules

The following rules are considered part of the project architecture:

Routers handle HTTP, not business logic.

Services own business rules and transaction orchestration.

Repositories own database access.

User-owned resources are always scoped by authenticated user ID.

Domain errors are separated from HTTP mapping.

Database changes always use Alembic.

Important invariants are enforced close to the data.

Cross-module collaboration must preserve module ownership.

Receipt confirmation must remain atomic.

Infrastructure complexity is added only when requirements justify it.

Tests and CI protect architectural behavior.

Web and mobile clients consume the backend through the API contract.

17. Current Architecture Status

Backend modular structure        ✅
PostgreSQL persistence           ✅
Alembic migrations               ✅
Development authentication       ✅
Supabase authentication support  ✅
Centralized error handling       ✅
Receipt upload / OCR flow        ✅
Atomic receipt confirmation      ✅
Docker environment               ✅
Automated backend CI             ✅
Web client                       planned
Mobile client                    planned
Production deployment            planned

18. Direction

The next architecture steps are:

Documentation
      ↓
Production Supabase verification
      ↓
Backend deployment
      ↓
Web / Mobile integration
      ↓
Evolution based on real usage

The architecture should stay simple, explicit, testable, and easy to evolve.