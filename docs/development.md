# 🛠 Development Guide — Valor Finis

This document defines the main development rules and architectural conventions for Valor Finis.

---

# 📌 Principles

- Build simple, then scale
- Prefer clear architecture over clever abstractions
- Keep business logic outside HTTP handlers
- Keep modules focused on one business area
- Validate data at system boundaries
- Protect user ownership on the backend
- Use migrations for every database schema change
- Test business rules and API contracts
- Avoid premature optimization

---

# 🧱 Architecture

Valor Finis uses a modular monorepo structure.

```text
Valor_Finis/
├── apps/               # Web and mobile clients
├── services/
│   └── api/            # FastAPI backend
├── docs/               # Project documentation
├── .github/workflows/  # CI
└── docker-compose.yml

The backend follows a layered architecture:

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

Each backend module represents one business area.

Current modules:

auth
categories
expenses
budgets
goals
receipts
analytics
🧩 Backend Module Structure

Typical module:

modules/
└── expenses/
    ├── expenses_router.py
    ├── expenses_service.py
    ├── expenses_repository.py
    ├── expenses_models.py
    ├── expenses_schemas.py
    └── errors.py
Responsibilities
Router

Handles HTTP concerns:

request
authentication dependency
validation
response model
status code

Routers must not contain database or business logic.

Service

Contains:

business rules
ownership validation
transactions
domain operations
model → response conversion
Repository

Contains database access:

SELECT
INSERT
UPDATE
DELETE

Repositories should not contain HTTP logic.

Schemas

Pydantic schemas define API input and output contracts.

Models

SQLAlchemy models define persistence and database relationships.

Errors

Business failures are represented as domain exceptions.

They are mapped to HTTP responses by centralized exception handlers.

🔄 Feature Development Workflow

For a backend feature:

Define API contract
        ↓
Define schema
        ↓
Add/update model if needed
        ↓
Create Alembic migration
        ↓
Repository
        ↓
Service
        ↓
Router
        ↓
Unit tests
        ↓
Integration tests
        ↓
Run complete test suite

Do not start implementation before the expected API behavior and business rules are clear.

🔌 API Design

Use predictable REST endpoints.

Example:

GET    /api/v1/expenses
POST   /api/v1/expenses
GET    /api/v1/expenses/{id}
PATCH  /api/v1/expenses/{id}
DELETE /api/v1/expenses/{id}

Use:

POST   → create
GET    → read
PATCH  → partial update
DELETE → delete

API rules:

use consistent resource naming;
use Pydantic validation;
return consistent error responses;
never trust user-provided ownership identifiers;
scope user resources using the authenticated user;
keep HTTP concerns in routers.
🗄 Database

Valor Finis uses PostgreSQL with SQLAlchemy and Alembic.

Rules:

every schema change requires an Alembic migration;
migrations must work from an empty database;
use database constraints for important invariants;
use foreign keys for relationships;
add indexes only when they serve a real query pattern;
application validation does not replace database constraints.

Migration workflow:

alembic upgrade head

Check migration state:

alembic current
🔐 Authentication and Authorization

Supported modes:

development
supabase

Development mode can use:

X-User-Id: <UUID>

Supabase mode uses:

Authorization: Bearer <token>

Rules:

development authentication must never be treated as production authentication;
users may access only their own resources;
ownership is validated on the backend;
authentication failures return consistent HTTP errors;
secrets must never be committed to Git.
🧾 Receipt Processing

Receipt processing follows a controlled state flow:

Upload
  ↓
Validate file
  ↓
Store file
  ↓
OCR processing
  ↓
Parse detected data
  ↓
Confirm data
  ↓
Create Expense
  ↓
Mark Receipt confirmed

Receipt confirmation and expense creation must remain atomic.

A failure must not leave partially confirmed financial data.

🧪 Testing

Backend testing uses pytest.

Main test levels:

Unit tests
    ↓
business rules and isolated behavior

Integration tests
    ↓
API + service + repository + PostgreSQL

Tests should cover:

happy paths
validation errors
ownership rules
not-found behavior
duplicate protection
database constraints
domain error mapping
authentication
transaction-sensitive operations

Before completing backend work:

python -m pytest -x -v

The local green test suite is the primary development check.

🐳 Docker

Docker Compose provides the local application environment.

FastAPI
   ↓
PostgreSQL

Start:

docker compose up --build

The API container automatically applies:

alembic upgrade head

before starting FastAPI.

Stop containers while preserving data:

docker compose down
🚀 CI

GitHub Actions runs backend CI on pushes and pull requests to main.

Pipeline:

Checkout
   ↓
Python
   ↓
PostgreSQL
   ↓
Install dependencies
   ↓
Alembic migrations
   ↓
pytest

A feature is not considered complete when CI is failing.

📦 Code Standards

Python follows standard Python naming:

variables/functions → snake_case
classes             → PascalCase
constants           → UPPER_SNAKE_CASE
modules/files       → snake_case

Code rules:

keep functions focused;
prefer explicit code over unnecessary abstraction;
avoid hidden side effects;
avoid unrelated refactoring during feature work;
comments should explain intent or reasoning;
remove dead code instead of commenting it out.
🔒 Security Rules
never commit .env files;
never log secrets or access tokens;
validate external input;
enforce resource ownership;
use ORM/database parameterization instead of constructing SQL manually;
restrict development authentication to development environments;
return safe API errors without exposing internal implementation details.
⚡ Performance

Optimize only after identifying a real bottleneck.

Preferred order:

measure
  ↓
identify bottleneck
  ↓
optimize
  ↓
measure again

Potential tools such as pagination, caching, queues, or separate services should be introduced when real requirements justify them.

🌐 Web and Mobile

Frontend clients consume the backend through its public API contract.

Clients must not duplicate backend business rules.

Expected flow:

Web / Mobile
      ↓
Authentication
      ↓
Valor Finis API
      ↓
PostgreSQL

Shared API clients/types should be generated or derived from the API contract when frontend development begins.

✅ Definition of Done

A feature is complete when:

behavior is implemented
API contract is correct
business rules are covered
ownership/security rules are respected
database migration exists when required
unit/integration tests pass
full backend test suite passes
CI passes
documentation is updated when behavior changed
📈 Scaling Rule

Do not introduce infrastructure only because it is considered modern.

Start with clear module boundaries.

Extract queues, workers, caching, or independent services only when there is a demonstrated requirement such as:

independent scaling
failure isolation
different infrastructure needs
independent deployment
clear organizational ownership
🎯 Current Direction

The backend MVP is implemented.

Current priorities:

Documentation
    ↓
Production Supabase verification
    ↓
Backend deployment
    ↓
Web / Mobile integration
    ↓
Improve the API based on real client usage
💡 Final Rule
