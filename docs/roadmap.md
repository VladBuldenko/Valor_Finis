🗺 Roadmap — Valor Finis

This document describes the current project state and the current development direction for Valor Finis.

It focuses on major product milestones rather than small implementation tasks. The direction below reflects today's priorities; it is not an immutable long-term promise.

1. Current Status

Backend (FastAPI modular monolith)        ✅ Implemented, deployed in production
Mobile client (Expo / React Native)       ✅ Implemented for the core finance flows
Financial ledger / money-flow foundation  ✅ Implemented
Account Transfers                         ✅ Implemented (VF-018, backend + mobile)
Financial Overview                        ✅ Implemented (VF-019, backend + mobile); device refresh acceptance pending
Smart Goals & Rules (VF-020)              🚧 In progress — VF-020A contract, VF-020B hardening, VF-020C Goal-Account reservations (backend and mobile) and VF-020D Goal priorities with the user lock L0 (D1–D5, D5 revision 7c1e5a9b3d28) are complete; VF-020E (rules engine, backend): contract finalized (E1), the financial_events schema (E2) is applied to production (schema revision 115998e2e795), the Income outbox runtime (E3) is implemented on its feature branch (not merged or deployed), rules and AUTO/CONFIRM are not implemented; VF-020F (mobile for rules) is not started
Financial Connections & Import (VF-021)   Later — separate stream; discovery may run in parallel
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

Accounts — checking/savings/cash; AccountTransaction ledger (opening balance, manual adjustments, income, expense, and transfer projections); balance is ledger-derived and may be negative; archive instead of delete once history exists

Account Transfers — same-currency moves between the user's own Accounts; planned (no ledger effect) or posted (a source debit and a destination credit); manual posting of planned transfers; create idempotency; hard delete; a transfer is neither Income nor an Expense

Income — salary/freelance/refund/gift/other, historical FX snapshot, optional Account link (credit projection)

Receipts — upload, storage (local or Supabase Storage), OCR, parsing, confirmation into an Expense with an optional Account link; confirmation is atomic and serialized per receipt

2.4 Analytics v2

Monthly and category summaries in the user's base currency

Spending trend and category trend

Current-month spending forecast (expense-only)

Budget status with period metrics (pace, projection, risk)

Goal progress

Financial Overview (VF-019B) — monthly Income, Expenses, Net (Income - Expenses), and savings rate, plus a monthly income-expense trend, from canonical Income and Expense records only (never Account ledger rows, Transfers, or Goal transactions)

Income feeds analytics only through the Financial Overview. Net is recorded income minus recorded expenses; there is still no bank-reconciled or true cash-flow analytics.

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

Account Transfers — list (planned and posted), create, manual post with an explicit effective date, delete; transfer rows with their counterparty Account in Account history

Financial Overview — month navigation, Income/Expenses/Net/savings rate for the selected month, 6-month history, and an income/expenses/Net card on the Dashboard

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

TRANSFER
= money moved between two of the user's own Accounts (same currency)
= NOT Income and NOT an Expense
= posted: a debit on the source and a credit on the destination Account
= planned: no ledger effect until posted

BUDGET
= a spending allocation / limit
= NOT stored cash

GOAL
= an aspirational savings target
= has its own GoalTransaction ledger
= may be linked to an Account through reservations (VF-020C): a reservation earmarks money and never moves it; a Goal is not stored cash and is not connected to any other cash source

Income and Expense are the canonical records; their AccountTransaction rows are synchronized projections. GoalTransaction and AccountTransaction are separate ledgers.

The Financial Overview's Net (Income - Expenses) is recorded income minus recorded expenses. It is not a bank reconciliation, a true cash flow, an Account balance, or net worth.

4. Current Product Phase

Financial ledger / money-flow foundation

Money can be recorded as spent (Expense) or received (Income) and, optionally, reflected in the balance of the real-world Account it affected. Money can also move between the user's own Accounts through transfers, and the Financial Overview summarizes recorded income versus expenses. Goals track savings progress on their own ledger. Goal ↔ Account semantics discovery is complete: VF-020B (Goals hardening), VF-020C (Goal-Account reservations, backend and mobile) and VF-020D (Goal priorities and the user lock L0) are implemented, the VF-020E (rules engine, backend) contract is finalized but not implemented, and VF-020F (mobile) is not started.

5. Completed Milestones — Account Transfers and Financial Overview

Account Transfers (VF-018): approved contract (VF-018A, PR #61), schema foundation (VF-018B, PR #62), API with create idempotency (VF-018C, PR #63), manual posting (VF-018D, PR #64), and mobile (VF-018E, PR #65). Same-currency only. The contract and decision record are in docs/modules/account-transfers.md.

Financial Overview (VF-019): discovery (VF-019A), backend (VF-019B, PR #67), mobile (VF-019C, PR #68), and final integration/documentation (VF-019D). The contract and decision record are in docs/modules/financial-overview.md. Physical-device acceptance of the automatic refresh after Income/Expense create/update/delete and Receipt confirmation is pending verification on the first suitable real transaction. Supporting evidence, none of which is device acceptance: static inspection of the mutation call-site wiring, two backend integration tests covering specific Income and Expense mutation sequences, and a one-off local check of the invalidation helpers against a real TanStack QueryClient (scratch script not committed; not an automated regression test). Details are in docs/modules/financial-overview.md section 11.

6. Next — VF-020 Smart Goals & Rules

Goals can be linked to Accounts since VF-020C2 (backend, merged and deployed; production runtime verified read-only via the public OpenAPI schema). The mobile integration (VF-020C3) is merged (PR #78; `main` contains C3); its independent strict review passed and its physical-device acceptance (cases A-M) is recorded as user-confirmed PASS, with no local proxy or database evidence attached. Goal funding never moves money: a linked contribution is a reservation (an earmark) against an Account.

Product discovery asked whether funding a Goal means (1) moving actual money out of an Account into a real destination, or (2) earmarking money that remains physically in the Account. The approved VF-020A contract (docs/modules/smart-goals-rules.md) answers it for VF-020: earmarking (an Account-linked reservation that moves no money) alongside the existing tracked-only Goal progress. Moving money is not part of VF-020, and internal rules never initiate payments or transfers.

The contract is approved for documentation and implementation planning only. Each stage needs its own implementation authorization:

1. VF-020A — Smart Goals & Rules contract (approved)

2. VF-020B — Goals hardening (implemented; production was at revision 8799b7fd923d after B4 — historical, superseded by later revisions)

3. VF-020C — Goal Account allocations (reservations, as-of capacity). The VF-020C contract is finalized in docs/modules/smart-goals-rules.md (v0.4). C1 (schema expand, nullable goal_transactions.account_id) is merged and applied to production (revision 98acdc7016d2). C2 (backend runtime: ORM mapping, partitions, linked contributions/withdrawals, Account capacity read model, lifecycle protection; no new migration) is merged and deployed. C3 (mobile) is merged (PR #78; Goal detail contribution source and explicit withdrawal partition, Goal and Account reservation displays, idempotency payload including account_id, cache invalidation, operation-aware error copy; no FX, no partial allocation, no safety floor, no AUTO/CONFIRM, no priorities, no advisory L0, no persistent idempotency storage). Independent strict review: PASS (0 blocker, 0 high, 0 medium). Physical-device acceptance, cases A-M (tracked and linked contribution, Account and Goal read-model refresh, tracked and explicit linked-partition withdrawal, insufficient partition and capacity errors, archived Account excluded from new reservations but still releasable, dropped-response retry / idempotent replay, legacy tracked-only Goal, Account lifecycle 409 UX): recorded as user-confirmed PASS, with no blocking UI defect reported; no automated or log evidence is attached to this record. VF-020C is complete. Fixed order: C1 → production migration → C2 → C3. The safety floor is deferred to VF-020E; the user advisory lock L0 is introduced in VF-020D (P68).

4. VF-020D — Goal priorities (COMPLETE; contract v0.5 in docs/modules/smart-goals-rules.md): `priority_rank` for all non-archived Goals (active and completed), a priority-aware Goal order, `PUT /api/v1/goals/priorities`, the mobile Priorities screen, and the user advisory lock L0 on every Goal write. Stages: D1 contract, D2 expand migration (4d2f7b91a6c3, applied to production), D3 backend runtime (PR #81), D4 mobile (PR #82), D5 lifecycle contract migration (7c1e5a9b3d28, PR #83, applied to production). Production revision: 7c1e5a9b3d28. Each production migration (D2 and D5) follows the same ordered gates: explicit authorization, read-only preflight, backup, backup verification, short lock timeout, migration, post-migration verification. No rules, AUTO/CONFIRM, safety floor or holds (VF-020E).

5. VF-020E — Rules engine (backend, schema and dispatcher only; contract finalized in docs/modules/smart-goals-rules.md v0.6, NOT implemented): durable outbox, AUTO and CONFIRM internal allocation rules, the Account safety floor as a rule, soft holds, alerts and a backend Inbox read model; unattended AUTO requires a durable periodic dispatcher. Stages: E1 contract (documentation), E2 outbox schema expand (COMPLETE: migration 115998e2e795 applied to production on 2026-10-19; production schema revision 115998e2e795), E3 Income outbox runtime (implemented on the feature branch feat/VF-020E3-income-outbox-runtime; not pushed, merged or deployed), E4 rules schema expand, E5 rules CRUD and floor runtime, E6 execution schema expand, E7 dispatcher and AUTO, E8 CONFIRM, E9A alert schema, E9B alerts and Inbox read model, E10 periodic dispatcher operationalization (P50 technical verification still required). Each schema stage (E2, E4, E6, E9A) has its own production migration gate.

6. VF-020F — Mobile completion and acceptance (all mobile rule management, proposal and Inbox UI, floor-warning UX, device acceptance; no mobile work belongs to VF-020E)

VF-021 — Financial Connections & Import is a separate strategic stream: consent-driven, read-only bank/application connections, import, reconciliation and statistics. Its discovery may run in parallel with VF-020; implementation is gated by provider, security, privacy and legal readiness.

7. Later Capabilities

These are product opportunities, not current commitments:

true cash-flow analytics (bank-reconciled; distinct from the implemented Net (Income - Expenses) and savings rate)

consolidated account activity

recurring transactions

notifications

web client

advanced receipt automation

Push notifications and scheduled (calendar-based) rules are not part of the first VF-020 release; each requires its own prerequisites (see docs/modules/smart-goals-rules.md).

8. Current Development Direction

Current implemented finance foundation (including Account Transfers and the Financial Overview)
        ↓
VF-020A Smart Goals & Rules contract (approved)
        ↓
VF-020B Goals hardening (done) → VF-020C Goal Account allocations (done: C1 → production migration → C2 → C3) → VF-020D Goal priorities (done: D1–D5, production 7c1e5a9b3d28) → VF-020E Rules engine (backend; contract E1 merged, E2 complete and applied to production, E3 Income outbox runtime on its feature branch, E4 next) → VF-020F Mobile & acceptance
        ↓
later product capabilities

In parallel: VF-021 Financial Connections & Import discovery (implementation gated separately).

The Financial Overview was deliberately prioritized before Goal ↔ Account semantics discovery (VF-019 decision Q10).

Mobile remains the primary client. The web client comes later and is not the immediate next client milestone.

9. Known Follow-ups

Production is deployed and has received hardening, while additional operational and security hardening remains ongoing, for example:

credential rotation

additional production hardening

authentication/password security settings where applicable

Receipt/OCR edge-case handling (deferred together with further Receipt work)

User timezone semantics: "today" is the server date, so the device and the server can disagree around midnight (planned transfers, effective dates, Financial Overview month state)

Financial Overview known limitations (Dashboard refresh after midnight, non-atomic reads, monthly-summary calendar semantics, pending device refresh acceptance) are listed in docs/modules/financial-overview.md

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
