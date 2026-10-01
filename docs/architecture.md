🧱 Architecture — Valor Finis

This document describes the current architecture of Valor Finis and the rules that should guide future development.

1. Architecture Overview

Valor Finis is a modular monorepo with a FastAPI backend and an Expo / React Native mobile client. Mobile is the primary client; a web client is planned for later.

Valor_Finis/
├── apps/
│   └── mobile/            # Expo / React Native client
├── services/
│   └── api/               # FastAPI backend
├── docs/                  # Project documentation
├── .github/workflows/     # CI
└── docker-compose.yml     # Local infrastructure

The repository boundary is not the deployment boundary. The mobile app and the API can be built and deployed independently.

2. System Context

Mobile Client (Expo)
        │
        ├── Supabase Auth ── sign-in / session only
        │
        │ HTTP + JSON (Authorization: Bearer <access_token>)
        ↓
   Valor API (FastAPI)
        │
        ├── Supabase Auth ── verifies the bearer token per request
        │
        ├── Receipt storage (local or Supabase Storage) / OCR
        │
        ├── FX providers (ECB / NBU) ── historical rates at write time
        │
        ↓
   PostgreSQL

In production the backend runs on Render, and PostgreSQL, Auth, and receipt Storage are provided by Supabase.

The backend is the source of truth for:

financial business rules;

authentication and authorization;

resource ownership;

persistence and ledger balances;

FX snapshots;

receipt processing;

analytics.

Clients must not duplicate backend business rules or financial calculations.

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

user-scoped database queries;

row locking (SELECT ... FOR UPDATE) where a service needs serialization.

Repositories do not know about HTTP.

Schemas

Pydantic schemas define API input and output contracts. Request schemas mirror storage limits (for example NUMERIC(12,2) amounts and VARCHAR lengths) so invalid input is rejected with 422 before it reaches the database.

Models

SQLAlchemy models define persistence structure, relationships, indexes, and database constraints.

4. Backend Modules

The backend is divided by business capability:

app/modules/
├── auth/
├── categories/
├── expenses/
├── budgets/
├── goals/
├── accounts/
├── income/
├── financial_settings/
├── fx/
├── receipts/
└── analytics/

Auth

Resolves the current user.

Supported modes:

development → X-User-Id
supabase    → Authorization: Bearer <token>

AUTH_MODE is required and fails closed. Development authentication is intended only for local development and tests.

Categories

Owns spending category rules: user ownership, case-insensitive uniqueness, protected default categories, and hiding categories that are referenced by budgets.

Expenses

Owns expense records (money spent), their category relationship, their historical FX snapshot, and the optional Account link (a synchronized debit projection in the Account ledger).

Budgets

Owns spending limits: weekly/monthly/yearly periods, versioned budget history (BudgetVersion), and duplicate-budget rules. A Budget is an allocation, never stored cash.

Goals

Owns savings goals and their GoalTransaction ledger (opening balance, contributions, withdrawals). A Goal's balance is derived from its ledger. Goals are not connected to Accounts.

Accounts

Owns Accounts (checking, savings, cash) and the AccountTransaction ledger: opening balance, manual adjustments, and the Income/Expense/Transfer projections. An Account's balance is derived from its ledger and may be negative.

It also owns Account Transfers (VF-018C): the canonical AccountTransfer record, its service (create with server-side idempotency, list, hard delete), and its router mounted at /api/v1/account-transfers. Transfers live inside the accounts module because the Account lifecycle rules must read them.

Income

Owns income records (money received), their historical FX snapshot, and the optional Account link (a synchronized credit projection in the Account ledger).

Financial Settings

Internal module holding per-user financial settings, currently the base currency (EUR by default). It has no public API.

FX

Resolves historical exchange rates (ECB, NBU) into the user's base currency at write time. Identity conversions never call a provider.

Receipts

Owns:

upload metadata;

storage coordination (local or Supabase Storage);

OCR processing;

parsed receipt data;

receipt status transitions;

confirmation into an Expense (optionally linked to an Account).

Analytics

Reads financial data and returns derived summaries: monthly and category summaries in base currency, spending and category trends, the current-month spending forecast, budget status with period metrics, and goal progress. Analytics is read-only and expense-oriented; Income is not yet part of analytics.

5. Financial Ledger Architecture

Valor Finis keeps two separate ledgers. They are not the same ledger and they are not connected.

GoalTransaction rows are append-only.

In the AccountTransaction ledger, direct entries such as opening balances and manual adjustments are immutable, while Income/Expense projection rows are synchronized with their canonical records and may be updated, moved to another Account, or removed together with them (on detach or when the canonical record is deleted). Transfer projection rows are created only when an Account Transfer is posted and removed only together with the transfer.

Account
   ↓
AccountTransaction ledger
   ↓
derived Account balance (SUM(credits) − SUM(debits); may be negative)

Goal
   ↓
GoalTransaction ledger
   ↓
derived Goal balance (never negative)

Neither Account nor Goal stores a balance column. Balances are always computed from ledger rows at read time.

Income and Expense ↔ Account

Income
   ↓
optional linked AccountTransaction credit (kind "income")
   ↓
Account

Expense
   ↓
optional linked AccountTransaction debit (kind "expense")
   ↓
Account

Income and Expense are the canonical records. Their AccountTransaction is a synchronized projection:

the link lives on the projection row (account_transactions.income_id / expense_id); there is no account_id column on income or expenses;

creating, correcting (amount/date), moving, detaching, or deleting the canonical record updates the projection in the same database transaction;

linking requires the record's currency to exactly match the Account's currency — the ledger uses the record's own amount, never its base-currency value;

an archived Account cannot receive new linked activity, but existing links can be corrected, detached, or moved out.

Direct Account ledger entries (opening balance and manual adjustments) are immutable; corrections are made with a compensating adjustment. An Account with ledger history cannot be deleted, only archived; its currency becomes immutable once history exists.

Account Transfers

AccountTransfer (canonical, same currency, same user)
   ├── planned: no ledger rows, no balance effect
   └── posted:  debit AccountTransaction on the source Account
                credit AccountTransaction on the destination Account
                (kind "transfer", both dated effective_date)

A transfer moves the user's own money between two Accounts. It is neither Income nor Expense and never feeds expense analytics or budgets. Implemented (VF-018C):

create: transfer_date <= server today creates a posted transfer and both projections in one database transaction; a later date creates a planned transfer with no ledger rows. There is no insufficient-funds check.

create idempotency: every create carries a client_request_id. The service looks it up before locking, locks both Accounts, looks it up again, and only then validates the Accounts (owned, active, same currency) for a new transfer. An existing transfer with the same original payload is returned as a replay (200) without re-validating current Account state; a different payload is a 409. UNIQUE(user_id, client_request_id) is the final defense against concurrent duplicates, recognized by its constraint name.

list: planned and posted transfers, stored state only.

hard delete: removes the transfer and, if posted, both projections (ON DELETE CASCADE). Archived Accounts never block it.

manual posting (VF-018D): POST /api/v1/account-transfers/{id}/post moves a planned transfer to posted with an effective_date (default: server today, never in the future, before or after planned_date). In one transaction it locks the transfer, then both Accounts in ascending id order, requires the transfer to be planned (else 409) and both Accounts active (else 409, transfer stays planned), marks it posted (planned_date kept), creates both projections dated effective_date, and commits once. The transfer row lock plus the one-way planned -> posted status make a transfer post at most once; posting has no idempotency key.

Account lifecycle guard: an Account referenced by a planned transfer cannot be deleted or actually change currency (409); archiving stays allowed. Posted transfers are covered by the existing ledger-history rules.

History read model: each transfer row in Account history carries transfer_id and a read-only counterparty_account_id resolved in the same query (no per-row lookup).

The domain contract is docs/modules/account-transfers.md.

Concurrency

Lifecycle and linkage operations lock the affected rows with SELECT ... FOR UPDATE. Canonical rows are locked before Account rows, and FX resolution (external network I/O) happens before any Account row lock is taken, so no Account lock is held across a network call.

Whenever two Accounts are locked (an Income/Expense move, a transfer create, post, or delete) they are locked in ascending id order, so operations over the same pair in opposite directions cannot lock them in opposite orders. Transfer post and delete lock the transfer row first, then its Accounts. Account delete and currency change lock only the Account and read planned-transfer references without locking them, before writing, so the Account path never takes transfer row locks. This removes the known lock-order cycles; it is verified by concurrency tests rather than claimed as a proof that no deadlock can ever occur.

Not yet implemented

Any automatic scheduler for planned transfers, and any Goal ↔ Account movement or earmarking (pending product discovery). A planned transfer stays planned until it is posted manually (the mobile client posts with an explicit effective_date, VF-018E).

6. Module Boundaries

Modules may collaborate through services or clearly defined repository operations when required, but business ownership must remain explicit.

Example:

Receipt confirmation
        │
        ↓
Receipt Service
        │
        ├── locks and validates the receipt
        │
        ├── prepares ExpenseCreate (optionally with account_id)
        │
        ↓
Expenses Service
        │
        ├── validates the Account link (ownership, active, currency)
        │
        ├── writes the Expense and its debit projection
        │
        ↓
Expense / AccountTransaction repositories

The receipts module coordinates the workflow, while the expenses module remains responsible for creating a valid expense and its ledger projection.

Avoid circular dependencies and direct cross-module database manipulation where a domain service already owns that behavior.

7. Authentication and Ownership

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

FastAPI is the only business-data gateway: business tables are never
queried through Supabase's Data API (PostgREST). Supabase Auth (session
issuance/refresh, verified per-request against `/auth/v1/user`) and
Supabase Storage (receipt files, via `/storage/v1/object/...`) are
structurally independent of Data API table privileges. As of VF-SEC-01,
anon/authenticated/service_role hold no privileges on any
application-owned public table (see docs/database-schema.md §10.1 for
the full posture and rationale) - this is a database-level hardening
layered on top of, not a replacement for, the application-layer
ownership check above, which remains mandatory regardless.

8. Mobile Client Architecture

apps/mobile is an Expo SDK 57 / React Native app using Expo Router, TanStack Query, and strict TypeScript.

Expo route / screen
        ↓
feature service
        ↓
src/api/api-client.ts (adds the Supabase access token)
        ↓
Valor API (FastAPI)

Rules:

Supabase is used for authentication only (email/password sign-in, session). Business data is never read or written through the Supabase Data API — all finance CRUD goes through FastAPI.

Routes are thin; feature code lives in src/features/<feature>.

The auth context owns only the session; routes behind sign-in are protected.

TanStack Query owns server state; component state owns form/UI state. Mutations invalidate only the affected query families (for example, a linked Income/Expense change also refreshes the Account list and transaction history).

Money values stay strings end to end; the app never uses floating-point arithmetic for financial values.

Balances, FX, currency matching, and archived-Account rules are decided by the backend and surfaced through its error messages.

9. Error Handling

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

10. Database Architecture

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
budget_versions
goals
goal_transactions
accounts
account_transactions
income
receipts
user_financial_settings

Important relationships:

Category
   ├── Expense
   └── Budget ── BudgetVersion

Goal ── GoalTransaction

Account ── AccountTransaction (opening balance, adjustments, projections)

Income  ── optional synchronized AccountTransaction credit ── Account
Expense ── optional synchronized AccountTransaction debit  ── Account

Receipt ── Expense

Important invariants are protected at both application and database levels when appropriate.

Examples:

positive financial amounts stored as NUMERIC (never float);

foreign keys and composite ownership keys;

unique category names per user;

duplicate budget prevention;

at most one Account projection per Income/Expense.

See docs/database-schema.md for the full schema.

11. Database Migrations

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

12. Receipt Processing Architecture

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
User confirmation (optional Account)
  ↓
Create expense (+ optional Account debit)
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

Receipt confirmation, expense creation, and the optional Account debit form one transaction boundary.

BEGIN

lock receipt row (SELECT ... FOR UPDATE)
verify the receipt is still confirmable
create expense
create Account debit projection (when account_id is given)
update receipt → confirmed
link receipt → expense

COMMIT

On failure:

ROLLBACK

The receipt row lock serializes concurrent confirmations of the same receipt, so a receipt can never produce two expenses or two debits. This prevents a receipt from being confirmed without its expense, or an expense from being created while receipt confirmation fails.

Further Receipt/OCR expansion is deferred; the existing flow remains implemented.

13. Configuration

Runtime configuration is environment-based.

Main variables include:

DATABASE_URL
AUTH_MODE
SUPABASE_URL
SUPABASE_PUBLISHABLE_KEY
RECEIPT_STORAGE_DRIVER
RECEIPT_UPLOAD_DIR
RECEIPT_MAX_FILE_SIZE_MB
RECEIPT_OCR_DRIVER

The mobile app reads EXPO_PUBLIC_API_URL and its public Supabase settings from its own environment.

Rules:

secrets never belong in Git;

.env is local-only;

.env.example documents required configuration;

unsupported authentication modes fail fast.

14. Local Infrastructure

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

The mobile app runs separately through the Expo development server and talks to the configured API URL.

15. Continuous Integration

GitHub Actions validates backend changes.

Push / Pull Request
        ↓
PostgreSQL 16 (valor_test)
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

16. Testing Architecture

The backend uses two primary test levels, both against a real PostgreSQL database ("unit" means layer-focused, not DB-mocked).

Unit Tests

Validate focused business behavior.

Typical targets:

service rules;

schemas and validation;

parsers;

authentication helpers;

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

Integration tests must verify ownership, API contracts, persistence, ledger balances, and important failure scenarios, including atomic rollback and concurrency (row-lock) races.

Test safety and determinism:

pytest refuses to run unless the database name ends with _test, because the suite deletes all application data;

business tests never depend on live ECB/NBU availability — the FX resolution boundary is replaced where FX is not under test, and provider tests use mocked HTTP responses.

Mobile changes are verified with TypeScript type-checking, linting, and targeted manual device checks; mobile automated E2E testing is deferred.

17. Scaling Strategy

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

18. Architectural Rules

The following rules are considered part of the project architecture:

Routers handle HTTP, not business logic.

Services own business rules and transaction orchestration.

Repositories own database access.

User-owned resources are always scoped by authenticated user ID.

Domain errors are separated from HTTP mapping.

Database changes always use Alembic.

Important invariants are enforced close to the data.

Money is Decimal / NUMERIC on the backend and a string on the client — never float.

Balances are derived from ledgers, never stored.

Income and Expense are canonical; their Account ledger entries are projections kept in sync in the same transaction.

Cross-module collaboration must preserve module ownership.

Receipt confirmation must remain atomic.

Infrastructure complexity is added only when requirements justify it.

Tests and CI protect architectural behavior.

Clients consume the backend through the API contract.

19. Current Architecture Status

Backend modular structure             ✅
PostgreSQL persistence                ✅
Alembic migrations                    ✅
Supabase authentication (fail-closed) ✅
Supabase Data API hardening           ✅
Centralized error handling            ✅
FX snapshots / base-currency analytics ✅
Goal ledger (GoalTransaction)         ✅
Account ledger (AccountTransaction)   ✅
Income / Expense Account projections  ✅
Receipt upload / OCR flow             ✅
Atomic, serialized receipt confirmation ✅
Docker environment                    ✅
Automated backend CI                  ✅
Test database safety guard            ✅
Production backend deployment         ✅
Mobile client                         ✅ core finance flows
Account transfers (create/list/delete/post) ✅ backend + mobile
Goal ↔ Account semantics              pending product discovery
Web client                            later

Production operational and security hardening is ongoing.

20. Direction

The next architecture steps are:

Goal ↔ Account semantics discovery
      ↓
cash-flow / financial overview
      ↓
Evolution based on real usage

The architecture should stay simple, explicit, testable, and easy to evolve.
