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

Test database:

The suite deletes all application data between tests, so it must run against a dedicated database whose name ends with _test (for example valor_test), never the development database valor. tests/conftest.py enforces this: pytest aborts with a usage error before any test runs if DATABASE_URL points anywhere else.

One-time setup (from services/api):

createdb -h localhost -U postgres valor_test
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/valor_test alembic upgrade head

Before completing backend work:

DATABASE_URL=postgresql://postgres:postgres@localhost:5432/valor_test python -m pytest -x -v

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

Client types mirror the API contract: the mobile client keeps strict TypeScript types aligned with the backend response schemas, and all business data goes through the FastAPI client.

Mobile validation (from apps/mobile, Node 22.13.0 from `.nvmrc`; npm only):

npm ci
npx tsc --noEmit
npm run lint
npm test

`npm test` runs every `src/**/*.test.ts` and `src/**/*.test.mjs` file with Node's built-in test runner (`scripts/run-unit-tests.js`). There is no test framework dependency, and no phone, simulator, Metro, network or Supabase is needed. The runner fails when no test file is found, so a moved test directory cannot pass silently. The tests import TypeScript helpers through Node's type stripping, which needs `--experimental-strip-types` on the pinned Node 22.13 (it is on by default from 22.18); the script passes the flag, so it works on every supported version. Test files may import `./x.ts` directly (`allowImportingTsExtensions`), and `@types/node` is a devDependency for `node:test` typing. Keep tests to pure helpers: screens, navigation and device behavior are not covered by this command.

API transport (timeouts, typed `ApiError`, GET-only retry, HTTP 401 handling, cache isolation between users): see [docs/modules/mobile-api-client.md](modules/mobile-api-client.md). Its Node tests prove the rules only; staging acceptance (BR-7) is separate.

GitHub Actions (`.github/workflows/mobile-ci.yml`) runs the same four commands on every pull request to `main` and every push to `main`, on Ubuntu with the Node version from `.nvmrc`, a read-only token and no secrets. It does not build, publish or run EAS.

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

The backend is implemented and deployed in production, and the mobile client implements the core finance flows, including Account Transfers and the Financial Overview.

Current priorities (docs/roadmap.md is the authoritative direction):

VF-020 Smart Goals & Rules (VF-020B–D complete; VF-020E rules engine contract finalized — E2 outbox schema complete and applied to production (revision 115998e2e795); E3 Income outbox runtime merged; E4 rules schema applied to production (revision 861064d31463); E5 rules CRUD and floor runtime merged; E6 execution schema merged and applied to production (revision e0503e9ca9d3); E7 AUTO execution runtime merged (env RULE_EVENT_BACKGROUND_DISPATCH, default true, controls the best-effort post-response drain); E8 CONFIRM proposals merged (PR #91); E9A rule_alerts schema (migration a7c3e91d5b24) merged (PR #92) but not applied to production; E9B alert runtime merged (PR #93; it degrades gracefully without the table, but live alerting waits for the E9A production migration); E10 periodic dispatcher merged (PR #94; `python -m app.modules.financial_rules.dispatcher` from services/api, env RULE_DISPATCHER_*; not scheduled - see docs/operations/rule-dispatcher.md); alert fairness corrective plus the persistent alert-progress schema (migration c4d8a2f6e193) are on a local branch, not pushed or applied; VF-020F mobile later)
    ↓
Improve the API and the mobile app based on real usage
💡 Final Rule


Future production migration plan for E9A (DOCUMENTED ONLY - nothing below has been executed, and
no production credential was used while preparing E9A). It starts only after the E9A PR is merged
and needs its own explicit authorization:

1. Explicit authorization: a separate user message naming the revision `a7c3e91d5b24`.
2. Read-only production preflight: `alembic current` must be exactly `e0503e9ca9d3`; `rule_alerts`
   must not exist; the server must be PostgreSQL 15+ (`ON DELETE SET NULL (column)`); no other
   writer holds long locks on `financial_rules`.
3. Backup verification: a fresh logical backup (libpq environment variables, nothing secret in
   argv) with a recorded checksum and a confirmed restore path BEFORE the migration.
4. Lock-timeout policy: the migration takes only SHARE ROW EXCLUSIVE on `financial_rules`; run it
   in one transaction with a transaction-local `lock_timeout` of about 5 seconds (injected by the
   operator wrapper, never stored in the revision) and abort rather than wait.
5. Exact-revision migration: only through the fail-closed runner `docs/operations/sql/run_guarded_migration.sh` (see `docs/operations/e9a-production-migration.md` section 5); never a hand-typed Alembic command, never `head`, one transaction.
6. Post-migration verification: `alembic current` = `a7c3e91d5b24`; the table, its six CHECKs, the
   foreign key (`ON DELETE SET NULL (rule_id)`), the unique constraint and the three indexes exist
   with the documented predicates; `anon`, `authenticated` and `service_role` hold no privilege on
   `rule_alerts`; the table is empty; the deployed E8 API still answers.
7. Rollback / incident approach: the revision is additive and the E8 runtime ignores the table, so
   the first response to any problem is to leave the table in place and stop; `alembic downgrade
   e0503e9ca9d3` is available while the table is empty and refuses once alerts exist; a failed
   upgrade rolls back as one transaction (transactional DDL). E9B must not deploy before step 6
   passes.
