🗺 Roadmap — Valor Finis

This document describes the current project state and the current development direction for Valor Finis.

It focuses on major product milestones rather than small implementation tasks. The direction below reflects today's priorities; it is not an immutable long-term promise.

1. Current Status

Backend (FastAPI modular monolith)        ✅ Implemented, deployed in production
Mobile client (Expo / React Native)       ✅ Implemented for the core finance flows
Financial ledger / money-flow foundation  ✅ Implemented
Account Transfers                         ⏳ Next — specification/discovery first
Goal ↔ Account semantics                  ⏳ Requires product discovery
Web client                                Later

Valor Finis has moved beyond a CRUD MVP into a financial ledger / money-flow foundation. It is not feature-complete.

2. Implemented Foundation

2.1 Backend Platform

FastAPI modular monolith (Router → Service → Repository → SQLAlchemy → PostgreSQL)

PostgreSQL + SQLAlchemy 2 + Alembic (every schema change is a versioned migration)

Supabase Auth integration (Authorization: Bearer <token>); AUTH_MODE is required and fails closed; development X-User-Id auth is local/test-only

Production deployment: the backend runs on Render, with Supabase-hosted PostgreSQL, Auth, and receipt Storage; production schema changes are applied through Alembic

Security hardening: Supabase Data API (PostgREST) access to application tables is revoked (VF-SEC-01); FastAPI is the only business-data gateway

Centralized domain-error → HTTP mapping

Historical FX snapshots and base-currency analytics (ECB / NBU providers)

API/database validation parity: request schemas reject values the storage columns cannot hold exactly (e.g. amounts beyond NUMERIC(12,2), descriptions over 500 characters) with 422 instead of silent rounding or a 500

2.2 Quality and CI

GitHub Actions backend CI: PostgreSQL 16 → Python 3.9 → Alembic upgrade head → pytest

Test database safety: pytest refuses to run unless the database name ends with _test (e.g. valor_test), because the suite deletes application data

Deterministic tests: business tests never depend on live ECB/NBU availability (the FX resolution boundary is replaced where FX is not under test; provider tests use mocked HTTP)

Concurrency tests for ledger and lifecycle races (row locking)

2.3 Finance Domain

Expenses — CRUD, categories, historical FX snapshot, optional Account link (debit projection)

Categories — CRUD, case-insensitive uniqueness, protected defaults, hide instead of delete when referenced by a budget

Budgets v2 — weekly/monthly/yearly periods, versioned history (BudgetVersion), calendar-aware budget status, pace/projection/risk metrics

Goals v2 — GoalTransaction ledger (opening balance, contributions, withdrawals); balance is ledger-derived and never negative; overfunding allowed; archive instead of delete once history exists

Accounts — checking/savings/cash; AccountTransaction ledger (opening balance, manual adjustments, income and expense projections); balance is ledger-derived and may be negative; archive instead of delete once history exists

Income — salary/freelance/refund/gift/other, historical FX snapshot, optional Account link (credit projection)

Receipts — upload, storage (local or Supabase Storage), OCR, parsing, confirmation into an Expense with an optional Account link; confirmation is atomic and serialized per receipt

2.4 Analytics v2

Monthly and category summaries in the user's base currency

Spending trend and category trend

Current-month spending forecast (expense-only)

Budget status with period metrics (pace, projection, risk)

Goal progress

Income is not yet part of any analytics endpoint; there is no cash-flow or net-income analytics yet.

2.5 Mobile Client (apps/mobile)

Expo SDK 57, Expo Router, TanStack Query, TypeScript (strict)

Supabase email/password sign-in; protected routes

Dashboard

Expenses — create/edit/delete, currency, optional Account link

Categories and Budgets management

Goals — funding (contributions/withdrawals), transaction history, archived goals

Analytics

Accounts — active/archived lists, create with optional opening balance, detail with transaction history, manual adjustments, edit, archive/reactivate, delete when no history

Income — list/create/edit/delete with optional Account link

Receipts — upload, review, and confirmation with an optional Account link

2.6 Receipts Status

Receipt upload, OCR, and confirmation are implemented and remain available. Further Receipt/OCR expansion is deferred for now and is not the next product milestone. This is a prioritization decision, not a technical deprecation.

3. Financial Model

These distinctions are part of the product and must be preserved:

ACCOUNT
= a real-world place where money exists (checking, savings, cash)
= balance derived from its AccountTransaction ledger
= balance may be negative

INCOME
= money received
= may optionally project a credit into an Account

EXPENSE
= money spent
= may optionally project a debit into an Account

BUDGET
= a spending allocation / limit
= NOT stored cash

GOAL
= an aspirational savings target
= has its own GoalTransaction ledger
= currently NOT connected to any Account or other cash source

Income and Expense are the canonical records; their AccountTransaction rows are synchronized projections. GoalTransaction and AccountTransaction are separate ledgers.

4. Current Product Phase

Financial ledger / money-flow foundation

Money can be recorded as spent (Expense) or received (Income) and, optionally, reflected in the balance of the real-world Account it affected. Goals track savings progress on their own ledger. The next work extends how money moves between Accounts.

5. Next Milestone — Account Transfers

Status: not implemented. The next step is specification/discovery, before any implementation.

Likely initial direction:

Account A
   debit
      ↓
Transfer
      ↓
   credit
Account B

The initial scope should preferably be same-currency transfers only, unless discovery decides otherwise.

Planned sequence:

Account Transfers discovery/specification
        ↓
Account Transfers backend
        ↓
Account Transfers mobile

6. After Transfers — Goal ↔ Account Semantics

Goals are not connected to Accounts today. Before any cash integration, product discovery must answer an open question:

Is funding a Goal:

1. moving actual money out of an Account into a real destination, or

2. earmarking money that remains physically in the Account?

This is not decided. Goal funding from Accounts is not implemented and must not be assumed.

7. Later Capabilities

These are product opportunities, not current commitments:

true cash-flow analytics

net income

savings rate

consolidated account activity

recurring transactions

notifications

web client

advanced receipt automation

8. Current Development Direction

Current implemented finance foundation
        ↓
Documentation/state synchronization
        ↓
Account Transfers discovery/specification
        ↓
Account Transfers backend
        ↓
Account Transfers mobile
        ↓
Goal/Account semantics discovery
        ↓
possible Goal cash/earmarking integration
        ↓
cash-flow / financial overview
        ↓
later product capabilities

Mobile remains the primary client. The web client comes later and is not the immediate next client milestone.

9. Known Follow-ups

Production is deployed and hardened, but operational and security work is ongoing, for example:

credential rotation

additional production hardening

authentication/password security settings where applicable

Receipt/OCR edge-case handling (deferred together with further Receipt work)

10. Engineering Principles

Keep the modular monolith until a concrete requirement justifies extracting a component:

Modular Monolith
        ↓
Production usage
        ↓
Measure bottlenecks
        ↓
Identify operational need
        ↓
Extract only necessary components

Possible future extraction candidates (OCR workers, notification processing, heavy analytics) are considered only when independent scaling, failure isolation, or operational needs provide a concrete reason.

Build the next layer only when the current layer is working in real usage.
