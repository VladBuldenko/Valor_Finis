# MVP Repository Audit (VF-MVP-ENG-001, Part 1)

Audit date: 2026-10-27. Audited commit: `08d985c030a38823fe43863c806d90bbc86e97b4` (`main`, merge of PR #97).
Status of this document: evidence-based snapshot. It does not change behavior and does not authorize any
implementation or production action.

## 1. Method and evidence base

| Source | How it was used |
|---|---|
| `services/api` source | Routers, schemas, error mapping, services read directly. |
| OpenAPI | Generated offline with `app.openapi()` (no database connection; `DATABASE_URL` pointed at a `_test` name only to satisfy settings). This is the authority for endpoints, request and response schemas. |
| `apps/mobile` source | Every route file, every feature directory, services, query keys, cache helpers, load/error/empty handling. |
| `docs/*` | Compared against the two sources above. Documentation is never treated as proof that code exists. |
| Tests | Counted statically (`def test_` per directory) and a bounded subset executed locally (section 6). |

Classification vocabulary: **IMPLEMENTED** (verified in source), **PARTIAL**, **MISSING**, **BLOCKED**
(cannot proceed until a named dependency is resolved), **UNKNOWN** (cannot be verified offline), **DEFERRED**
(deliberately out of the MVP).

## 2. Domain classification

"Backend" means the FastAPI behavior exists in source and is covered by tests. "Mobile" means a screen in
`apps/mobile` can perform the action today. "Production" is UNKNOWN for everything newer than the last
operator-recorded migration (see [mvp-ops-dependencies.md](mvp-ops-dependencies.md)).

| Domain | Backend | Mobile | Notes |
|---|---|---|---|
| Authentication / session | IMPLEMENTED (Supabase JWT; dev `X-User-Id` local/test only) | PARTIAL | Email+password sign-in and sign-out exist. No sign-up, password reset, session-expiry/401 handling, or cache clear on sign-out. |
| Dashboard | IMPLEMENTED (analytics endpoints) | IMPLEMENTED (limited) | Shows month summary, income/expenses/net, category spend, budget status, goals. Shows **no account balances** and no rule/alert/proposal signal. |
| Accounts and balances | IMPLEMENTED | IMPLEMENTED | List (active/archived), create with opening balance, detail + ledger, manual adjustment, edit, archive/reactivate, delete when no history. Capacity fields: only `current_balance`, `reserved_amount`, `reservable_amount`, `balance_as_of_today`, `allocation_status` are typed/shown. |
| Income | IMPLEMENTED | IMPLEMENTED | CRUD with optional Account link. List is unpaginated. |
| Expenses | IMPLEMENTED | IMPLEMENTED | CRUD, category, currency, optional Account link. List unpaginated. |
| Categories | IMPLEMENTED | IMPLEMENTED | CRUD, hide/show, protected defaults. |
| Budgets | IMPLEMENTED | IMPLEMENTED | Create/edit/delete, status/risk. |
| Account transfers | IMPLEMENTED (idempotent create, manual post, delete) | IMPLEMENTED | Same-currency only. No scheduler for planned transfers. |
| Goals and reservations | IMPLEMENTED | IMPLEMENTED | Reservation/release through Goal transactions with `account_id`; no money moves. |
| Goal priorities | IMPLEMENTED (`PUT /goals/priorities`) | IMPLEMENTED | Up/down reorder screen with stale-set handling. |
| Receipts and OCR | IMPLEMENTED | PARTIAL | Upload, process, review/confirm exist. Mobile never lists, edits or deletes receipts (no receipt list screen). OCR quality/edge cases deferred by product decision. |
| Analytics | IMPLEMENTED | IMPLEMENTED | Monthly, category, trends, forecast, budget status, goal progress. |
| Financial Overview | IMPLEMENTED | IMPLEMENTED (device refresh acceptance recorded pending in roadmap) | Income vs Expenses vs Net only; not bank cash flow. |
| Smart Rules (CRUD) | IMPLEMENTED (`/financial-rules`, 4 rule types, enable/pause/disable) | **MISSING** | No mobile feature directory for rules. |
| AUTO / CONFIRM execution | IMPLEMENTED (user-triggered drain and best-effort post-Income drain) | **MISSING** | Nothing in mobile calls `POST /financial-rules/evaluate`. |
| Unattended execution (dispatcher) | PARTIAL (CLI merged; fairness + progress schema merged) | n/a | **UNKNOWN / BLOCKED**: no Cron Job exists; scheduled execution has never been observed (P50 unverified). |
| Rule proposals | IMPLEMENTED (list/get/confirm/reject, lazy expiry) | **MISSING** | |
| Rule dry-run preview | **MISSING in backend** | **MISSING** | Contract §20.4 specifies `POST /financial-rules/{id}/preview`; it does not exist in OpenAPI. See contract matrix. |
| Alerts | IMPLEMENTED (`GET /rule-alerts`, acknowledge) | **MISSING** | Live alerting also needs E9A applied in production (UNKNOWN). |
| Inbox | PARTIAL (no Inbox endpoint; composed client-side from proposals + alerts + executions) | **MISSING** | The contract says the Inbox is composed; no composed endpoint or unread count exists. |
| Safety-floor warning (manual reservation) | IMPLEMENTED (`warnings[]` on Goal-transaction response) | **MISSING** | Mobile type for the response does not read `warnings`; the advisory is never shown. |
| Hard capacity rejection (manual) | IMPLEMENTED (409 `Reservation exceeds the Account's reservable capacity.`) | IMPLEMENTED | Mapped in `goal-transaction-errors.ts`. |
| Bank connections (VF-021), investments, web, push, scheduled allocation | n/a | n/a | DEFERRED. |

## 3. Backend facts that constrain design

- **Errors carry no machine-readable code.** Every domain error is `{"detail": "<English string>"}` with an
  HTTP status (`app/core/exception_handlers.py`, 66 mapped domain errors). Validation errors are FastAPI's
  `{"detail": [...]}`. The mobile client already matches exact strings for Goal transactions. Any new screen
  that must distinguish two 409s depends on string equality unless the backend adds codes.
- **No pagination** on Accounts, Goals, Budgets, Categories, Expenses, Income, Receipts, Transfers, Financial
  Rules. Pagination (`limit`, `offset`, default 20, max 100) exists only on `rule-executions`, `rule-proposals`,
  `rule-alerts` (and a `limit` on `evaluate`).
- **No `GET` by id** for Accounts, Income, Transfers (documented and confirmed). Goals, Budgets, Expenses have
  none either; mobile resolves single objects from list caches.
- **Idempotency** exists for Goal transactions (`client_request_id`, required when `account_id` is set) and
  Account transfers (`client_request_id` required). Everything else (Expense, Income, Account transaction,
  Budget, Rule create, Receipt confirm, Proposal confirm) has no client idempotency key; replay safety is
  state-based only where documented.
- **`user_id`** is never accepted in payloads (`extra="forbid"` on rule schemas; user from the JWT).
- **Today = server date.** Client and server can disagree around midnight (roadmap known follow-up).
- **Monetary values** are JSON strings (Decimal) in responses; requests accept number or string.

## 4. Mobile facts that constrain design

- Single `apiRequest` wrapper: attaches the Supabase access token; **no timeout, no 401 refresh/sign-out
  handling, no retry policy beyond TanStack Query defaults**; throws `Error("API request failed: <status> <body>")`.
- `QueryClient` is created with defaults: no `staleTime`, no offline/online manager, no focus manager.
- **No pull-to-refresh anywhere** (`RefreshControl` is not used).
- Load failures show a static line ("Unable to load …") with **no retry action**.
- Query keys are user-scoped (`[family, userId, …]`) except receipts (`["receipts","detail",id]`).
- No `queryClient.clear()` on sign-out; the user-scoped keys prevent cross-user reads but memory is retained.
- Navigation is a flat Stack with a button grid on the Dashboard; there are no tabs and no navigation entry for
  any rule/alert/proposal surface. Receipt routes are not registered in `(app)/_layout.tsx` (default titles).
- Automated mobile tests: six Node test files for Goals helpers (62 tests, pass). No component, integration or
  E2E tests; no mobile CI.

## 5. Outdated or contradictory documentation (kept separate on purpose)

These are documentation defects, not code defects. They must be corrected by a separate documentation task;
this task did not edit them.

| # | Location | Statement | Verified reality |
|---|---|---|---|
| D1 | `docs/roadmap.md` §1 | The fairness corrective and the persistent alert-progress schema `c4d8a2f6e193` "are on a local branch". | Merged: PRs #95 and #96; `alembic heads` on `main` = `c4d8a2f6e193`. |
| D2 | `docs/roadmap.md` §6 item 5 | E10 fairness corrective "on the local branch `fix/VF-020E10-dispatcher-fairness`, not pushed". | Same as D1. |
| D3 | `docs/roadmap.md` §4 | "the VF-020E (rules engine, backend) contract is finalized but not implemented". | E2–E10 are implemented and merged (PRs #85–#97). Same file §1 says so; the file contradicts itself. |
| D4 | `docs/roadmap.md` §6 item 5 heading | "contract finalized ... NOT implemented". | As D3. |
| D5 | `docs/product-requirements.md` update section | Production revision `861064d31463`; "rule execution (AUTO / CONFIRM) is not implemented". | Implemented. Production revision is UNKNOWN offline; roadmap/contract cite `e0503e9ca9d3` as operator-supplied state. Three docs give three values. |
| D6 | `docs/modules/smart-goals-rules.md` §1 | E10 "IMPLEMENTED on the local feature branch ... NOT pushed". E8 "implemented on the local branch, not yet deployed" (§20.4). | E8 PR #91, E10 PR #94 merged. |
| D7 | `docs/operations/rule-dispatcher.md` status line | "implemented on the local feature branch ... NOT pushed, merged, deployed or scheduled". | Merged (PR #94). The "not deployed/scheduled" half remains true. |
| D8 | `docs/development.md` (E9A plan, lines ~420–440) | Hand-typed `alembic upgrade a7c3e91d5b24`. | Superseded by the operations runbooks; the runbooks themselves on `main` still contain a hand-typed upgrade (see HIGH finding in the ops document). |
| D9 | `docs/modules/smart-goals-rules.md` §20.4, §10, §21 | `POST /financial-rules/{id}/preview`; "AUTO requires a preview before enable". | **No preview endpoint exists.** There is no backend dry run at all. |
| D10 | `docs/modules/smart-goals-rules.md` §20.4 | `POST/GET/PATCH/DELETE /api/v1/financial-rules` shorthand. | There is no collection-level DELETE; DELETE is `/financial-rules/{rule_id}`. Shorthand only. |
| D11 | `docs/modules/smart-goals-rules.md` §1 | "All mobile work is not started"; "E9B ... composed backend Inbox". | Accurate that mobile rules are not started. There is **no Inbox endpoint**; "composed" means client-side. |
| D12 | `docs/roadmap.md` §2.5 | Lists mobile features. | Accurate for what is listed; it omits that mobile has no receipt list, no 401 handling, no rule screens. |

Consistent (verified, no drift): no `GET /accounts/{id}`, `/income/{id}`, `/account-transfers/{id}` (docs and
OpenAPI agree); `Account != Budget != Goal` semantics text matches the schemas.

## 6. Existing evidence versus evidence produced by this task

**Existing evidence (not re-run in full by this task):** Backend CI workflow (`backend-ci.yml`: PostgreSQL 16,
Python 3.9, `alembic upgrade head`, `pytest -x -v`, `AUTH_MODE=development`). The last full local backend run
recorded in the preceding OPS-02 work (2535 passed on the OPS-02 corrections branch) is **not** a run of this
branch's `main` and is not presented as one. Statically there are 2023 `def test_` functions in `services/api/tests`
(parametrization raises the executed count).

**Executed during this task (2026-10-27, local, disposable target `valor_test`, migrated to `c4d8a2f6e193`):**

| Check | Result |
|---|---|
| `alembic heads` | single head `c4d8a2f6e193` |
| OpenAPI generation (`app.openapi()`) | succeeded; 69 operations (67 under `/api/v1`) enumerated |
| Targeted pytest: `tests/integration/test_health.py`, `financial_rules/test_financial_rules_router.py`, `test_confirm_proposals.py`, `test_rule_alerts_runtime.py` | 108 passed |
| `npx tsc --noEmit` (mobile) | exit 0 |
| `npm run lint` (mobile) | exit 0 |
| `node --test src/features/goals/*.test.mjs` | 62 passed |

The full backend suite was **not** re-run: this task changes documentation only.
