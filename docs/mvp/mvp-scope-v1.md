# MVP Scope v1 (VF-MVP-ENG-001, Part 2)

Version: 1.0-proposed. Date: 2026-10-27. Basis: `main` @ `08d985c030a38823fe43863c806d90bbc86e97b4`.

**Approval status: PROPOSED, pending product-owner approval.** This document freezes scope as an engineering
recommendation grounded in the repository audit ([mvp-repository-audit.md](mvp-repository-audit.md)). Nothing in
it is approved until the owner resolves section 9. Status words are used exactly as defined in the audit
(IMPLEMENTED, PARTIAL, MISSING, BLOCKED, UNKNOWN, DEFERRED).

## 1. Product objectives

1. Let a person see where their money is (Accounts) and where it goes (Expenses, Categories, Budgets).
2. Let a person record money received (Income) and understand the month (Income, Expenses, Net, analytics).
3. Let a person plan for goals without moving real money: a Goal **reservation** earmarks money that stays in an
   Account.
4. Let a person automate that earmarking with **internal** rules (AUTO or CONFIRM) and be warned when an Account
   is overcommitted, below its safety floor, or a Budget is at risk.
5. Keep every number explainable: each figure comes from the backend; the client never recomputes money.

## 2. Target users

Young professionals, freelancers, and people who want to control spending (from `docs/product-requirements.md`).
Single user per account; no sharing, no household, no advisor role. Mobile first (iOS and Android through Expo).

## 3. Canonical financial semantics (binding for all MVP design)

These distinctions are product rules; designers must not blur them.

| Concept | Meaning | Must never be shown as |
|---|---|---|
| Account | A real-world place money exists. `current_balance` is ledger-derived and may be negative. | A Goal, a Budget, or net worth. |
| Income | Money received. May credit an Account. | A transfer or a Goal deposit. |
| Expense | Money spent. May debit an Account. | A transfer or a reservation. |
| Transfer | Money moved between two owned Accounts (same currency). Planned = no ledger effect; posted = debit + credit. | Income or Expense. |
| Budget | A spending limit. | Stored cash. |
| Goal | A savings target with its own ledger. | Stored cash or a bank account. |
| **Goal reservation** | An earmark against one Account. **Not a bank transfer.** The Account's `current_balance` does not change. | A transfer, a withdrawal from the bank, or "money moved". |
| Release | Reducing a reservation. Writes a Goal transaction, **creates no Transfer**. | A transfer back. |
| `reservable_amount` | Balance as of today minus reservations, scheduled outflows and planned outgoing transfers. | "Cash you can spend" or "bank-available cash". |
| `unallocated_amount` / `rule_capacity` | Internal planning figures. | Bank-available cash. |
| Financial Overview Net | Recorded Income minus recorded Expenses. | Bank-reconciled cash flow, Account balance, net worth. |

Designers must not invent a "total balance", "safe to spend" or "available cash" figure. If the owner wants one
it needs a backend definition first (decision Q10).

## 4. Existing supported functionality

All rows below are IMPLEMENTED on the backend; the mobile column states what a user can do today.
See the screen inventory for routes.

| Domain | Mobile capability today |
|---|---|
| Authentication / session | Email+password sign-in, sign-out (Dashboard), protected routes. |
| Dashboard | Month summary, Income/Expenses/Net card, category spend, budget status, goals, navigation grid. |
| Accounts and balances | List active/archived, create (optional opening balance), detail with ledger, manual credit/debit adjustment, edit, archive/reactivate, delete when no history, reserved/reservable display, overcommitted indicator. |
| Income | List, create, edit, delete, optional Account link. |
| Expenses | List + inline create, detail edit/delete, currency, optional Account link. |
| Categories | List (incl. hidden), create, edit, hide/show, delete. |
| Budgets | List with status/risk, create, edit, delete. |
| Account transfers | List (planned/posted), create (idempotent), post planned with effective date, delete. |
| Goals and reservations | List (current/completed/archived), create, edit, delete, contribute/withdraw (tracked or linked to an Account), history, allocation display. |
| Goal priorities | Reorder screen with save and stale-set recovery. |
| Receipts and OCR | Camera/library upload, process, review and confirm into an Expense with optional Account. |
| Analytics | Spending trend, category trend, forecast, category breakdown. |
| Financial Overview | Month navigation, Income/Expenses/Net/savings rate, 6-month history. |

## 5. Required MVP functionality still missing

Items are required by the MVP domain list given for this task and are not available to a user today.

| ID | Missing capability | Kind | Class |
|---|---|---|---|
| M01 | Smart Rules: list, create, edit, enable/pause/disable, delete (INCOME_ALLOCATION, MINIMUM_UNALLOCATED_FLOOR, OVERCOMMITMENT_ALERT, BUDGET_ALERT) | Mobile | MISSING (backend IMPLEMENTED) |
| M02 | AUTO / CONFIRM mode selection and explanation | Mobile | MISSING |
| M03 | Rule **preview** (dry run) | **Backend + mobile** | MISSING; contract demands it for AUTO (D9). **BLOCKED** until the owner decides Q3. |
| M04 | Rule proposals: list, detail, confirm, reject, expiry display | Mobile | MISSING (backend IMPLEMENTED) |
| M05 | Alerts: list, acknowledge | Mobile | MISSING (backend IMPLEMENTED; live alerting UNKNOWN in production) |
| M06 | Inbox surface that composes proposals + alerts (+ failed executions) and a badge/count | Mobile (+ optional backend) | MISSING |
| M07 | Rule execution history, failures, recovery paths | Mobile | MISSING (backend IMPLEMENTED) |
| M08 | Manual-reservation safety-floor warning display | Mobile | MISSING (backend IMPLEMENTED) |
| M09 | Account safety-floor / holds / `rule_capacity` display | Mobile | MISSING (fields returned, not typed) |
| M10 | User-triggered rule evaluation on foreground / Inbox open (`POST /financial-rules/evaluate`) | Mobile | MISSING |
| M11 | Session-expiry handling (401), cache clear on sign-out, request timeout | Mobile | MISSING |
| M12 | Retry action on load failure; pull-to-refresh | Mobile | MISSING |
| M13 | Receipts list/manage screen (list, delete) | Mobile | MISSING (decision Q6) |
| M14 | Sign-up and password reset | Mobile | MISSING (decision Q5) |
| M15 | Machine-readable error codes | Backend | MISSING (decision Q4); today clients match English strings |
| M16 | Pagination for large lists | Backend + mobile | MISSING (decision Q7) |
| M17 | Verified unattended execution (Render Cron observed running) | Operations | BLOCKED / UNKNOWN |

## 6. Explicitly deferred

VF-021 bank connections and import; investments; web client; push notifications; scheduled calendar-based
allocation; recurring transactions; bank-reconciled cash-flow analytics; FX reservations and cross-currency
transfers; household/shared accounts; advanced receipt automation; Receipt/OCR expansion (product decision in
the roadmap: prioritization, not deprecation); mobile automated E2E until the product is functionally complete
(CLAUDE.md), see [mvp-qa-readiness.md](mvp-qa-readiness.md) for the interim plan.

## 7. Dependencies

```text
Offline UX work (research, wireframes)      no dependency on production
        |
Product decisions Q1-Q12                    owner
        |
Backend contract gaps (Q3 preview, Q4 codes, Q7 pagination, optional Inbox)   backend tasks
        |
Mobile foundations (M11, M12)               before any rules screen
        |
Rules screens M01, M02, M04-M10             need the contract above
        |
Operations: E9A+E10 applied, Cron observed   needed for "unattended" claims and Beta, NOT for the above
```

Hard dependencies: M03 needs a backend endpoint (or an approved alternative). M05 and live alert acceptance need
E9A applied in production. M17 needs the OPS release gates ([mvp-ops-dependencies.md](mvp-ops-dependencies.md)).

## 8. Acceptance requirements (MVP level)

An MVP domain is accepted only when all of these hold:

1. Every user-visible number is traceable to a backend field; no client money arithmetic beyond display.
2. Each primary journey in [mvp-user-journeys.md](mvp-user-journeys.md) passes on a physical iOS and a physical
   Android device against a development or staging backend with a disposable database.
3. Every state in [screen-state-and-design-requirements.md](screen-state-and-design-requirements.md) marked
   "required" is implemented or has a documented waiver.
4. Ownership: a second test user cannot read or mutate the first user's objects through any new screen (404, not
   403 leakage) – covered by backend tests and a manual cross-user check.
5. Rules: a user-triggered evaluation demonstrates AUTO, CONFIRM, confirm, reject, expiry and a floor/overcommit
   alert end to end. **"Runs automatically while the app is closed" is claimed only after Gate I** (an observed
   scheduled run); until then the UI copy says rules are evaluated when the app is opened or refreshed.
6. Typecheck, lint, existing Node tests, full backend regression green; new mobile logic with pure helpers has
   Node tests like the Goals helpers.
7. Accessibility baseline (labels, roles, dynamic type, contrast, non-color status) per the state document.
8. No production access was used to produce acceptance evidence.

## 9. Known blockers

| ID | Blocker | Effect |
|---|---|---|
| B1 | OPS HIGH finding: E9A/E10 migrations are still a hand-typed `alembic upgrade` on `main`; the fail-closed runner exists only in local commit `c4fbd73`, unpushed and not in any PR | Blocks any production release of E9A/E10 and therefore Beta. Does not block offline design or implementation. |
| B2 | OPS MEDIUM finding: Gate H stage 1 on `main` claims a disabled dispatcher proves the database connection; it does not | Blocks Cron activation. |
| B3 | No rule preview endpoint | Blocks M03 and the "AUTO requires preview" rule. |
| B4 | Production revision, deployed SHA, connectivity, E9A/E10 application are UNKNOWN | Blocks every claim about production state. |
| B5 | No Cron Job exists | Blocks "unattended" claims. |
| B6 | No machine-readable error codes | Raises cost and fragility of every rule-screen error path. |

## 10. Decisions requiring product-owner approval

| ID | Question | Recommendation |
|---|---|---|
| Q1 | Are Smart Rules screens (M01–M10) part of MVP v1, or is MVP v1 the existing finance foundation plus Beta of rules later? | Include (the task lists them), but sequence after M11/M12. |
| Q2 | May AUTO be offered before the scheduler is verified, with "evaluated when you open the app" copy? | Yes, with that exact honesty; never say "automatically while you sleep". |
| Q3 | Preview: (a) add a backend dry-run endpoint, (b) drop the AUTO preview rule and rely on CONFIRM as the safe path, (c) client-side simulation. | (a). (c) violates "do not duplicate backend calculations". (b) is the fallback. |
| Q4 | Add stable error codes to the backend error body? | Yes, additive `code` field, before rule screens. |
| Q5 | Sign-up and password reset in MVP, or provisioned accounts only? | Owner decision; blocks J01 scope. |
| Q6 | Receipts list/manage screen in MVP? | Defer; keep upload/confirm only (consistent with the roadmap). |
| Q7 | Pagination for Expenses/Income/Transfers lists before Beta? | Yes for Expenses and Income; unbounded lists are a performance risk. |
| Q8 | Timezone: server date vs device date for "today"? | Keep server date for MVP; show the date used. |
| Q9 | Inbox: client-composed, or add a backend summary/unread-count endpoint? | Client-composed first; add count endpoint only if the composed call count is a measured problem. |
| Q10 | Any aggregate "total across accounts" on the Dashboard? | No unless defined per currency with explicit semantics; do not sum different currencies. |
| Q11 | Which rule types ship in v1? | All four exist in the backend; recommend INCOME_ALLOCATION (CONFIRM first), MINIMUM_UNALLOCATED_FLOOR, OVERCOMMITMENT_ALERT, BUDGET_ALERT. |
| Q12 | Minimum supported OS versions and device matrix. | Owner decision; needed by QA. |
