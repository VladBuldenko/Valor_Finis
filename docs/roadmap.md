🗺 Roadmap — Valor Finis

This document describes the current project status and the planned development direction for Valor Finis.

The roadmap is intentionally focused on major product milestones rather than small implementation tasks.

1. Current Status

Backend MVP        ✅ Complete
Testing            ✅ Complete
Docker             ✅ Complete
CI                 ✅ Complete
Documentation      ✅ Complete
Production setup   ⏳ Next
Web client         ⏳ Planned
Mobile client      ⏳ Planned

The current backend provides a stable foundation for client integration.

It is not yet considered production-ready until production authentication, deployment, and end-to-end verification are completed.

2. Completed Backend Milestones

Core Finance

Expenses     ✅
Categories   ✅
Budgets      ✅
Goals        ✅
Analytics    ✅

Implemented capabilities include:

user-scoped financial data;

expense CRUD;

category CRUD;

case-insensitive category uniqueness;

protected default categories;

budget CRUD;

duplicate budget protection;

goal CRUD;

financial validation;

spending analytics;

budget status analytics;

goal progress analytics.

Receipt Flow

Receipt CRUD                 ✅
Receipt upload               ✅
File validation              ✅
Local receipt storage        ✅
OCR foundation               ✅
OCR processing               ✅
Receipt parsing              ✅
Receipt confirmation         ✅
Expense creation from receipt ✅
Atomic confirmation flow     ✅

Current receipt lifecycle:

uploaded
   ↓
processing
   ↓
processed
   ↓
confirmed

Failure path:

processing
   ↓
failed

Authentication

Development auth       ✅
Supabase auth support  ✅
User ownership rules   ✅
Auth error handling    ✅

Development mode:

X-User-Id

Supabase mode:

Authorization: Bearer <token>

Production Supabase end-to-end verification is still pending.

API Consistency

Versioned API routes           ✅
Pydantic request validation    ✅
PATCH update contracts         ✅
Centralized domain errors      ✅
Consistent HTTP responses      ✅

Current API prefix:

/api/v1

Database

PostgreSQL              ✅
SQLAlchemy              ✅
Alembic                 ✅
Fresh DB migrations     ✅
Constraints / indexes   ✅

Current persisted entities:

categories
expenses
budgets
goals
receipts

The full migration chain can rebuild the schema from an empty PostgreSQL database.

Testing

Unit tests          ✅
Integration tests   ✅
Database tests      ✅
Auth tests          ✅
Receipt flow tests  ✅
Error mapping tests ✅

The backend test suite is part of the Definition of Done for backend changes.

Docker

FastAPI container        ✅
PostgreSQL container     ✅
Database healthcheck     ✅
Automatic migrations     ✅
Persistent DB volume     ✅
Receipt upload volume    ✅

Local startup:

docker compose up --build

Continuous Integration

GitHub Actions backend CI is implemented.

Pipeline:

Push / Pull Request
        ↓
PostgreSQL 16
        ↓
Python 3.9
        ↓
Install dependencies
        ↓
Alembic migrations
        ↓
pytest

Current status:

Backend CI ✅

3. Documentation

Core project documentation is now established.

README.md                 ✅
docs/architecture.md      ✅
docs/api-contract.md      ✅
docs/database-schema.md   ✅
docs/roadmap.md           ✅

Documentation should evolve together with architecture and public API changes.

4. Next Milestone — Production Readiness

The next stage is to verify the backend outside the local development environment.

4.1 Supabase End-to-End Verification

Create/configure Supabase project
        ↓
Configure production auth environment
        ↓
Obtain real access token
        ↓
Call protected Valor API endpoint
        ↓
Verify CurrentUser resolution
        ↓
Verify ownership behavior

Goal:

Real Supabase user
        ↓
Bearer token
        ↓
Valor API
        ↓
User-scoped data

This closes the gap between implemented authentication support and real production authentication usage.

4.2 Production Environment Configuration

Prepare production-safe configuration for:

DATABASE_URL
AUTH_MODE
SUPABASE_URL
SUPABASE_PUBLISHABLE_KEY
RECEIPT_STORAGE_DRIVER
receipt storage settings

Development-only authentication must not be used in production.

Secrets must be stored in deployment environment configuration, not in Git.

4.3 Backend Deployment

Deploy the FastAPI backend to a production environment.

Deployment must verify:

container build
database connectivity
Alembic migrations
environment variables
health endpoint
authentication
receipt storage
API availability

Expected production flow:

Internet
   ↓
HTTPS
   ↓
Valor API
   ↓
PostgreSQL

4.4 Production Smoke Test

After deployment, verify at minimum:

GET /health
authentication
create category
create expense
create budget
create goal
upload receipt
process receipt
confirm receipt
analytics

The production environment should not be considered ready until the main business flow works end-to-end.

5. Web Client

After the backend is deployed and production authentication works, begin the web client.

Planned location:

apps/web/

Primary stack:

Next.js
TypeScript

Initial goals:

authentication
dashboard
expenses
categories
budgets
goals
receipts
analytics

The web client must consume the existing backend contract instead of recreating business rules.

Preferred integration direction:

FastAPI
   ↓
OpenAPI
   ↓
generated / typed API client
   ↓
Next.js

6. Mobile Client

Planned location:

apps/mobile/

Primary stack:

React Native
Expo
TypeScript

Main mobile goals:

authentication
expense tracking
receipt capture/upload
budget overview
goal tracking
analytics

The mobile client should use the same backend API contract as the web client.

7. Monorepo Direction

Target project structure:

Valor_Finis/
├── apps/
│   ├── web/
│   └── mobile/
│
├── services/
│   └── api/
│
├── packages/
│   ├── api-client/
│   └── ui/
│
├── docs/
├── .github/workflows/
└── docker-compose.yml

The repository may contain multiple independently deployed applications.

one repository
    ≠
one deployment

8. Future Engineering Improvements

The following are possible future improvements, not current requirements.

They should only be introduced when real usage justifies them.

API

pagination
filtering
sorting
API client generation
API version evolution

Observability

structured logging
error tracking
metrics
distributed tracing if needed

Performance

query optimization
indexes based on real usage
caching where measurable
background processing

Receipt Processing

external OCR provider
asynchronous OCR
queue / worker architecture
cloud object storage
retry policies

Security

production auth hardening
rate limiting
security headers
dependency scanning
SAST / DAST

Testing

frontend unit tests
web E2E tests
mobile E2E tests
production smoke tests
performance tests

9. Architecture Evolution

Valor Finis should continue as a modular application unless real requirements justify extracting services.

Preferred evolution:

Modular Monolith
        ↓
Production usage
        ↓
Measure bottlenecks
        ↓
Identify operational need
        ↓
Extract only necessary components

Possible future extraction candidates may include:

OCR workers
notification processing
heavy analytics

but only when independent scaling, failure isolation, infrastructure needs, or team ownership provide a concrete reason.

10. Product Development Order

Current high-level order:

Backend MVP                    ✅
        ↓
Backend tests                  ✅
        ↓
Docker                         ✅
        ↓
CI                             ✅
        ↓
Documentation                  ✅
        ↓
Supabase production E2E        ⏳
        ↓
Backend deployment             ⏳
        ↓
Web client                     ⏳
        ↓
Mobile client                  ⏳
        ↓
Real user feedback
        ↓
Iterative product development

11. Definition of Production-Ready Backend

The backend can be considered production-ready when:

production database works
all migrations apply successfully
Supabase authentication works end-to-end
development auth is disabled
HTTPS endpoint is deployed
health check works
main CRUD flows work
receipt flow works
CI is green
production smoke test passes
secrets are stored safely
basic logging is available

Production-ready does not mean feature-complete.

It means the backend can safely support real client usage.

12. Long-Term Product Direction

Valor Finis should evolve from a finance tracking backend into a complete personal finance product.

Potential long-term capabilities:

smart expense categorization
recurring expenses
advanced budgeting
financial insights
receipt automation
multi-currency support
notifications
forecasting
machine-learning-assisted insights

These are product opportunities, not current commitments.

They should be prioritized based on actual user needs and validated usage.

13. Final Rule

Build the next layer only when the current layer is working in real usage.

The immediate next milestone is:

Production Supabase verification
        ↓
Backend deployment
        ↓
Client in