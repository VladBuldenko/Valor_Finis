# VF-020A — Smart Goals & Rules: Product & Technical Contract

**Status: VF-020A — APPROVED FOR DOCUMENTATION / IMPLEMENTATION PLANNING**

**Implementation is not authorized by this document alone.** This document
approves no migration, no VF-020B…F implementation, no production-data access,
no external bank integration and no deployment. Each of those requires its own
explicit authorization.

---

## 1. Document Metadata and Approval Status

| | |
|---|---|
| Contract version | v0.3 (final), approved for documentation / implementation planning |
| Approval date | 2026-10-05 |
| Baseline | `main` @ `635ea7506f50f4df669c569a7407fd356ef0b790` (after VF-019D, PR #69) |
| History | v0.1 draft (2026-10-03) → v0.2 revision (2026-10-03) → v0.3 consolidated (2026-10-04) → approval of the remaining product decisions (2026-10-05) |
| Scope | VF-020 Smart Goals & Rules. VF-021 Financial Connections & Import is a separate milestone (§22) |
| Implementation state | Nothing in this document is implemented. Goals are currently not connected to Accounts |

Status tags used throughout:

| Tag | Meaning |
|---|---|
| **APPROVED** | Explicitly accepted by the user. |
| **ESTABLISHED (EST)** | Proven existing behavior at the baseline. |
| **PROPOSED** | Architectural recommendation; not binding until approved. |
| **UDR** | Unresolved user decision. |
| **EXT** | External, legal, provider or platform verification required. |

A PROPOSED item that refines an APPROVED decision does not inherit its approval.

---

## 2. Executive Summary

**VF-020 Smart Goals & Rules** works only on data already recorded in Valor
Finis (manual Income, Expenses, Accounts, Transfers, Receipts). It defines:

- **Model B + C (APPROVED):** account-linked Goal reservations alongside
  independent tracked-only Goal progress. A reservation never moves money and
  never writes an `AccountTransaction`.
- **An as-of-today capacity model (APPROVED P36, P49):** future credits never
  create capacity; recorded future debits and planned outgoing Transfers reduce
  it; `current_balance` is unchanged.
- **Goal priorities.**
- **A typed Rules Engine:** every internal allocation rule offers `AUTO` and
  `CONFIRM` (APPROVED P01) and never moves external money (APPROVED P16).
  Percentage rules use `Income.amount` (APPROVED P44). Pending `CONFIRM`
  proposals hold capacity softly (APPROVED P55) and expire after 7 days
  (APPROVED P54). The Account safety floor is strict for rules and
  warning-only for manual reservations (APPROVED P56).
- **Durable, database-backed event delivery:** a transactional outbox plus a
  dispatcher, idempotent executions, deterministic ordering under concurrency,
  and explicit provenance so that historical entries and imports never trigger
  `AUTO` (manual live window of 7 days, APPROVED P51). Unattended `AUTO` may be
  presented as guaranteed only once a durable periodic dispatcher exists
  (APPROVED P50).
- **Alerts that observe the existing Budgets.** Budgets remain the only
  authority for spending limits.

**VF-021 Financial Connections & Import** (consent-driven external data,
normalization, reconciliation, canonical integration) is a separate strategic
stream. Its discovery may proceed in parallel; implementation is gated on
provider, legal, privacy and security readiness, and it does not depend on the
VF-020 sequence.

**Resolved design requirements:** F1 durable trigger delivery (§12), F2 an
execution state machine with no retry/uniqueness contradiction (§13), F3
deterministic rule order under concurrency (§14), F4 provenance excluding
historical import and historical manual entries (§16).

**No user decision blocks the VF-020 product semantics.** The remaining
PROPOSED items are technical refinements finalized within their stages (§4);
VF-021 items remain UDR/EXT.

---

## 3. Approved Decisions

| ID | Approved content |
|---|---|
| P01 | Every supported internal allocation rule offers `AUTO` and `CONFIRM`. `AUTO` creates only authorized internal reservations; `CONFIRM` creates a proposal that requires explicit user approval. Neither initiates external payments. |
| P02 | Financial model = **B** (account-linked reservation) + **C** (tracked-only progress). A reservation does not transfer money; a tracked contribution makes no claim about money held in an Account. |
| P03 | Linking is per GoalTransaction, not a permanent mode of the whole Goal. |
| P04 | A new reservation above the permitted capacity is rejected with **409**; no partial write. |
| P05 | Expenses and Transfers are never blocked by reservations; underfunding is shown as `overcommitted`; Goal history is never silently rewritten. |
| P06 | Linked reservations require exact Goal/Account currency equality; no FX reservations in VF-020. |
| P07 | Withdrawals name their partition (tracked, or one specific Account-linked reservation); every partition stays nonnegative. |
| P09 | Archived Account: historical reservations kept; new linked contributions rejected; releases allowed; existing lifecycle invariants preserved. |
| P10 | Archived Goal: new contributions rejected; withdrawals and releases allowed; history preserved. This **intentionally changes** today's permissive behavior and requires explicit regression coverage. |
| P11 | Completed Goal: manual status semantics and currently permitted operations preserved; no automatic status or funding change. |
| P12 | Legacy GoalTransactions stay unchanged and unlinked; no invented Account associations. *(Also EST.)* |
| P13 | New GoalTransactions get an explicit `effective_date`: default = the current supported business date; future dates rejected; existing rows untouched; legacy rows without it keep their original meaning; `created_at` ≠ `effective_date`. |
| P14 | Every new Goal money-changing operation is idempotent, including tracked contributions and withdrawals, with an explicit transition plan for existing clients. Exactly-once is not claimed for legacy requests without a stable idempotency key. |
| P15 | Terminology: Recorded balance · Balance as of today · Reserved · Unallocated · Reservable · Overcommitted. Unallocated money is never called a guaranteed bank-available balance. |
| P16 | Internal rules never initiate real banking payments or Transfers. |
| P18 | Goals hardening ships separately and before the Goal allocation integration. |
| P19 | Integrity enforced by the database where feasible (composite FKs, consistent ownership, currency equality), with historical data verified before constraints and no invented history. **No migration is approved by this decision alone.** |
| P29 | Configurable partial allocation, default `allow_partial = false`. When false: all-or-nothing per rule; insufficient capacity yields `skipped` with an explicit reason. When true: partial execution in the approved deterministic order, recording exactly what was allocated, idempotently. |
| P35 | Rules act only on eligible Income: owned by the user; linked to the configured source Account; not future-dated; matching currency; within the rule's effective period; `refund` excluded by default; source Account and Goals eligible; duplicate processing cannot duplicate allocations. **Income has no posted/confirmed status, and none is invented.** |
| P36 | Capacity uses an as-of-today balance; future credits excluded; recorded future debit obligations subtracted (conservative); `current_balance` semantics unchanged. |
| P44 | Percentage-based Income allocation uses `Income.amount` in the matching Account/Goal currency, never `base_amount`. It applies only where the Income, the source Account and every target Goal satisfy the same-currency rule. |
| P45 | `Decimal`; allocation amounts use `ROUND_DOWN` to 0.01; the fractional remainder stays unallocated; authorized capacity is never exceeded. Financial Overview rounding is unchanged. |
| P46 | Enabling a rule never executes it retroactively over old Income. Historical bank backfill never generates automatic reservations merely because the related canonical Income is newly created. |
| P47 | Income corrections or deletion never undo, rewrite or reverse Goal transactions. Instead: executed history is preserved, current capacity recalculated, overcommitment and floor violations detected, the changed source state recorded, the user notified, and an explicit corrective release is available. |
| P48 | Precedence: (1) ownership and hard financial invariants → (2) capacity and safety floor → (3) rule order → (4) Goal priority → (5) per-goal and per-rule limits → (6) Decimal rounding → (7) partial-allocation policy. It must hold under concurrent execution; an ordered SQL query alone is not a concurrency guarantee. |
| P49 | Planned **outgoing** AccountTransfers reduce `reservable` capacity; planned **incoming** Transfers never increase current capacity. This is a read-model calculation over the existing canonical planned `account_transfers` records only: a planned Transfer still creates no `AccountTransaction`, no future ledger rows are invented, and existing AccountTransfer semantics are unchanged. A posted Transfer is represented by its ledger rows and is no longer counted as planned. |
| P50 | Unattended `AUTO` may be presented as guaranteed automation only once a **durable periodic dispatcher** exists. The mechanism is not fixed by this contract (a hosting-platform scheduled job, another supported scheduled execution mechanism, or another small durable backend mechanism) and must be technically verified before implementation. Working cadence target ≈ 10 minutes (range 5–15), an operations parameter. Without it, a beta may only promise execution at the next supported user-triggered drain. |
| P51 | v1 live window `N = 7` days. A manually created Income is classified `manual/live` only when its financial date (`received_at`) falls within the seven-day live-entry window; older manual entries are `manual/historical`: valid Income that participates in normal accounting and Financial Overview, but never triggers retrospective `AUTO` allocation. No user override in v1. Provenance remains the primary semantic guard; VF-021 imports are classified by their import provenance, not by timestamps alone. |
| P54 | `CONFIRM` proposals expire after **7 days**. Expiry creates no reservation and no GoalTransaction; an expired proposal can never be confirmed; a repeated action returns the terminal state. Lazy expiry at read, confirmation and dispatch is acceptable. |
| P55 | A valid pending `CONFIRM` proposal creates a **soft capacity hold** that reduces the capacity available to later rule evaluations and so preserves P48. The hold is not part of `reserved_amount`, is not a GoalTransaction, does not change any Account balance, and does not block a real Expense, an AccountTransfer or an explicit manual Goal reservation. Because a manual action may consume the underlying capacity, every confirmation fully revalidates; insufficient capacity rejects the confirmation and cancels the proposal as stale with no hidden partial write. The hold ends when the proposal is executed, rejected, expired, cancelled or superseded. A proposal never counts against its own confirmation. |
| P56 | The Account safety floor is strict for rule-generated allocations and **warning-only** for an explicit manual Goal reservation. The floor warning never overrides P04 capacity, ownership, currency equality, partition non-negativity, Goal/Account lifecycle restrictions or any other hard invariant: a manual reservation can never reserve money that does not exist under the reservable-capacity model. |

P34 (reversal after a trigger change) is **superseded by P47**.

---

## 4. Pending and External Decisions

| ID | Topic | Status | Finalized in |
|---|---|---|---|
| P08 | Moving a reservation between Accounts: manual release + reserve; an atomic move is deferred | PROPOSED | — |
| P17 | Attributing an Expense to a Goal | PROPOSED (deferred) | — |
| P23 | Automatic canonical posting of imported transactions | UDR | VF-021 |
| P24–P26 | Review of ambiguous imports; matching manual/receipt records; bank vs ledger balance | PROPOSED | VF-021 |
| P28 | Tie-break between rules (`execution_order`, `created_at`, `id`) | PROPOSED, subordinate to P48 | VF-020E |
| P30–P33 | Server-date timezone in v1; one source Account per rule; `AUTO` blocked on incomplete data; in-app notification defaults | PROPOSED | VF-020E |
| P37 | Invalid rule → `blocked` executions | PROPOSED | VF-020E |
| P38 | Credit-card / liability accounts outside VF-020 | PROPOSED / EXT research | VF-021 |
| P41–P43 | User timezone (deferred); v1 triggers = Income events + outbox + drain; in-app channel | PROPOSED | VF-020E |
| **P52** | Strict per-user FIFO with head-of-line blocking by failed events | **PROPOSED**, to be finalized during dispatcher implementation and review | VF-020E |
| P53 | Retention of processed events as provenance | PROPOSED (VF-021 data: EXT) | VF-020E / VF-021 |
| P57 | Goal deletion referenced by a rule → 409; rule deletion only without executions | PROPOSED | VF-020C/E |
| P58 | `effective_date` of linked rows = today only | PROPOSED | VF-020B/C |
| P59 | Timing for making `client_request_id` mandatory for all clients | PROPOSED | after VF-020F |
| P20, P21, P22, P27, P39 | Access model, provider/region, wallets, retention after disconnect, card FX | **EXT** | VF-021 |
| P50 mechanism | Choice of the periodic dispatcher technology (the requirement itself is APPROVED) | technical verification | VF-020E |

---

## 5. Existing Architecture (EST)

- Modular monolith; FastAPI with Router → Service → Repository → SQLAlchemy →
  PostgreSQL 16; Alembic; Supabase Auth (JWT); backend hosted on Render.
- Mobile: Expo SDK 57, Expo Router, TypeScript, TanStack Query. Supabase is used
  for auth only; all finance CRUD goes through FastAPI. The device workflow is
  Expo Go over LAN.
- Supabase Data API privileges are revoked on the application tables
  (migrations `edcfdf3f7114`, `1edb74dc96d8`).
- **There is no background mechanism**: no scheduler, worker, queue,
  `BackgroundTasks` or advisory locks exist in the code at the baseline.
- `income_service.create_income` supports `commit=False`: Income, its Account
  projection and a new outbox event can commit together. External FX
  resolution happens **before** any row lock.

---

## 6. Canonical Financial Invariants

### 6.1 Established

| ID | Invariant | Where |
|---|---|---|
| INV-01 | `Decimal` / `NUMERIC(12,2)`; money reaches mobile as decimal strings. | models, schemas |
| INV-02 | `user_id` comes only from authentication; repositories are user-scoped; the Account ledger uses composite `(…, user_id)` foreign keys. | `account_transaction_models.py` |
| INV-03 | Income, Expense and AccountTransfer are canonical; `account_transactions` holds their projections. | `docs/architecture.md` §5 |
| INV-04 | `current_balance` = SUM of all of the Account's ledger rows, with no date filter; it may be negative; there is no insufficient-funds check. Future-dated rows can come from Income/Expense in the base currency, adjustments and opening balances; Transfer projections are only ever dated ≤ today. | `account_transaction_repository.calculate_ledger_balance` |
| INV-05 | Every write to the Account ledger first locks the Account row: Income/Expense create/update/delete, Receipt confirmation, adjustments, Transfer create/post/delete. Order: canonical row → Accounts in ascending UUID. | income, expenses, accounts services |
| INV-06 | Goal balance ≥ 0; overfunding allowed; history append-only; status manual; currency immutable once history exists; a Goal with history cannot be deleted. | `goal_service.py` |
| INV-07 | Goal writes lock the Goal row first. | `goal_repository.get_goal_by_id_for_update` |
| INV-08 | Transfers: same currency, idempotent, neither Income nor Expense, no interaction with Goals. A planned Transfer has **no** ledger rows (`effective_date IS NULL`). | `account_transfer_models.py`, `docs/modules/account-transfers.md` |
| INV-09 | Financial Overview reads only canonical Income/Expense `base_amount`; unresolved FX records are counted separately. | `docs/modules/financial-overview.md` |
| INV-10 | Historical `base_amount` snapshots are never revalued. | FX module |
| INV-11 | Budgets are the authority on spending limits (`category_id` nullable, `limit_amount`, `currency`, `period` weekly/monthly/yearly, `start_date`/`end_date`, versions); status via `GET /api/v1/analytics/budget-status`, `risk_status` ∈ healthy/watch/at_risk/exceeded. | `budgets_models.py`, `budget_metrics.py` |
| INV-12 | "Today" = server `date.today()` (known limitation D13); there is no per-user timezone. | analytics, `financial_settings` |
| INV-13 | Income: full CRUD; `amount`, `currency`, `received_at`, `source` ∈ {salary, freelance, refund, gift, other}, `description`, FX snapshot, `created_at`, `updated_at`; **no lifecycle status**. | `income_models.py` |
| INV-14 | Archived Account: no new direct activity and no attach/move-in; detach/move-out allowed. | `income_service.py`, `expenses_service.py` |
| INV-15 | Destructive tests run only against a `*_test` database. | `tests/database_safety.py` |

### 6.2 Known gaps closed in VF-020B

| ID | Gap |
|---|---|
| G1 | Goal currency validation accepts non-alphabetic codes such as `"12$"`. |
| G2 | `goals.status` has no database CHECK. |
| G3 | The database does not guarantee that a goal transaction's owner equals the goal's owner. |
| G4 | Archived and completed Goals accept contributions (resolved by P10/P11). |
| G5 | Goal transactions have no idempotency (P14). |
| G6 | `goal_repository.get_goals(user_id=None)` returns every user's goals. |

### 6.3 Contract invariants for VF-020/021

| ID | Invariant |
|---|---|
| FIN-001 | No invented money: Goals, rules, priorities, holds and reservations never create Account money. |
| FIN-002 | No double counting: one economic event = at most one canonical record; Goal balances are never added to Account totals, net worth or Financial Overview. |
| FIN-003 | Canonical records stay authoritative; imports are evidence. |
| FIN-004 | A reservation is not a transfer, payment or withdrawal. |
| FIN-005 | Historical `base_amount` stays authoritative. |
| FIN-006 | Decimal everywhere; money is sent to mobile as strings. |
| FIN-007 | Ownership on every read and write; a provider identifier is never authorization. |
| FIN-008 | Related financial changes are atomic. |
| FIN-009 | Repeated requests, events and executions never duplicate a financial effect. |
| FIN-010 | Data completeness is visible; incomplete required state never feeds `AUTO`. |
| FIN-011 | GoalTransaction history is append-only; legacy history is never rewritten. |
| FIN-012 | Financial Overview semantics do not change. |

---

## 7. Goal Financial Semantics

### 7.1 Move, reserve, track

- **Move** money between Accounts = an AccountTransfer: outside VF-020 (P16, INV-08).
- **Reserve** money that stays in an Account = a linked partition (P02).
- **Track** progress without any claim about Accounts = the tracked partition, today's behavior (P02, P12).

### 7.2 Partitions (P02, P03, P07)

```
tracked(G)    = Σ opening_balance(G) + Σ contribution(G, account NULL) − Σ withdrawal(G, account NULL)
linked(G, A)  = Σ contribution(G, A) − Σ withdrawal(G, A)
total(G)      = tracked(G) + Σ_A linked(G, A)          -- identical to today's Goal balance formula
reserved(A)   = Σ_G linked(G, A)                       -- across all of the user's Goals, archived included
```

After every write: `tracked(G) ≥ 0` and `linked(G, A) ≥ 0` for every Account A.
No `AccountTransaction` is created for a reservation (FIN-004). No Goal
allocation changes Financial Overview (FIN-012).

### 7.3 GoalTransaction fields

| Field | Status | Notes |
|---|---|---|
| `goal_id`, `user_id`, `type`, `amount`, `description`, `created_at` | EST | unchanged; `amount > 0`; `type` CHECK unchanged |
| `account_id` (NULL = tracked) | APPROVED principle (P02/P03); schema PROPOSED | composite FK `(account_id, user_id, currency)` → `accounts(id, user_id, currency)`; that target unique constraint already exists |
| `currency` | APPROVED principle (P19); schema PROPOSED | deterministic copy of `goals.currency`; Goal currency is already immutable once history exists, so the copy is stable |
| `effective_date` | APPROVED (P13) | NULL for legacy rows; `≤ today` checked by the service; linked rows: today only (P58) |
| `client_request_id` | APPROVED (P14) | partial `UNIQUE(user_id, client_request_id)` |
| `rule_execution_id` | PROPOSED | composite FK `(rule_execution_id, user_id)` → `rule_executions(id, user_id)` |
| `CHECK (type <> 'opening_balance' OR account_id IS NULL)` | PROPOSED | opening balances always stay tracked |

### 7.4 Compatibility

| Consumer / case | Behavior |
|---|---|
| Existing `POST /api/v1/goals/{id}/transactions` without `account_id` | Tracked row, as today; `effective_date` = today; idempotency transition per §20.2. |
| Withdrawal without `account_id` | Validated against `tracked(G)`; for legacy goals `tracked = total`, so nothing changes. |
| Archived Goal | Contributions (tracked and linked) → 409 (P10). New behavior; no existing tests cover it, so new regression tests are required. |
| Completed Goal | Unchanged (P11). |
| Goal currency change | Unchanged rule (409 once history exists); the composite FK is the last line of defense. |
| `GET /api/v1/analytics/goal-progress` | `current_amount` = total; meaning unchanged; only additive fields. |
| API responses | Additive fields only (`account_id`, `effective_date`, `rule_execution_id`, partition breakdowns). Tests comparing complete dicts may need updating without any behavior change. |
| Mobile types | Additive; existing clients ignore new fields. |

Historical rows are never rewritten. The only data operation in scope is the
deterministic `currency` copy (P19), which requires its own migration approval.

### 7.5 Example

Account A balance as of today 2,000.00 EUR. Goal G: 300.00 tracked + 500.00 linked to A.
A reserved 500.00 · A unallocated 1,500.00 · G total 800.00 · user assets 2,000.00 (**not** 2,800.00).

---

## 8. Account Reservations and As-Of Balances

### 8.1 Formulas (read model; nothing is stored)

```
D                          = as_of_date: server date.today(), resolved once per request or transaction (INV-12)
current_balance(A)         = Σ all ledger rows of A                    -- EST, unchanged ("Recorded balance")
balance_as_of(A, D)        = Σ ledger rows of A with transaction_date ≤ D   ("Balance as of today")
scheduled_outflows(A, D)   = Σ debit ledger rows of A with transaction_date > D
planned_transfer_out(A)    = Σ amount of account_transfers with status = 'planned' AND source_account_id = A
reserved(A)                = §7.2
unallocated(A)             = balance_as_of(A, D) − reserved(A)
reservable(A)              = unallocated(A) − scheduled_outflows(A, D) − planned_transfer_out(A)
active_holds(A)            = Σ planned item amounts on A of proposals in 'awaiting_confirmation' with expires_at > now
rule_capacity(A)           = reservable(A) − floor(A) − active_holds(A)
```

- `balance_as_of` is not a competing balance: it is the same ledger read with a
  date boundary. `current_balance` keeps its name, meaning and API position.
- **No double subtraction:** future-dated debit ledger rows (`scheduled_outflows`)
  and planned Transfers (no ledger rows) are disjoint sets. Posting a planned
  Transfer requires `effective_date ≤ today`, so its projections land in
  `balance_as_of` and it leaves `planned_transfer_out` in the same transaction.
- Planned **incoming** Transfers and future-dated credits are never added.
- Holds reduce only `rule_capacity`; they are not part of `reserved`,
  `unallocated` or `reservable` (P55).
- All amounts are Decimal in the Account currency; a Transfer, a linked
  reservation and the Account always share one currency (INV-08, P06).

### 8.2 Clarifications

| # | Topic | Contract |
|---|---|---|
| 1 | Date boundary | A row is present if `transaction_date ≤ D`; D is fixed once per request or dispatcher transaction. |
| 2 | Future credits | Excluded from `balance_as_of` and from every capacity figure; they never create capacity (P36). |
| 3 | Future debits | Excluded from `balance_as_of`, subtracted through `scheduled_outflows` (P36). |
| 4 | Opening balance | Dated by `opening_balance_date` (default: day of creation). A future-dated positive opening balance is a future credit; a negative one is a scheduled outflow. |
| 5 | Adjustments | By `transaction_date` and `direction`, like any other row. |
| 6 | Future-dated Income/Expense | Through their projections (`received_at` / `expense_date`), like any other row. |
| 7 | Planned Transfers | No ledger rows exist and none are invented. Planned outgoing Transfers are subtracted through `planned_transfer_out` regardless of `planned_date` (a past `planned_date` can still be unposted because posting is manual); planned incoming Transfers are ignored (P49). |
| 8 | Negative balance | Allowed (INV-04). `reservable ≤ 0` → new reservations get 409; releases are always allowed. |
| 9 | Archived Account | All figures are computed and shown; new linked contributions → 409 (P09); rules are `blocked`. |
| 10 | Overcommitted | `allocation_status = overcommitted` ⇔ `reserved > 0 ∧ unallocated < 0`. Warning `scheduled_shortfall` (PROPOSED term) ⇔ `reserved > 0 ∧ unallocated ≥ 0 ∧ reservable < 0`. `negative_balance` is a separate flag. |
| 11 | Manual vs rule allocations | Manual reservations are limited by `reservable` (P04); the floor only warns (P56) and holds do not apply (P55). Rule-generated allocations (AUTO and confirmations) are limited by `rule_capacity` (§11.3). |
| 12 | Safety floor | `MINIMUM_UNALLOCATED_FLOOR` per Account (§10.6). |
| 13 | Date rollover | Figures change without writes; deferred events become due (§12); overcommitment may appear or disappear; history is never rewritten; Financial Overview rollover is unaffected. |
| 14 | Timezone | Server date; device and server may disagree near midnight (D13); a user timezone is deferred (P41). |

Bank-reported balances (VF-021) are a separate observation and never enter these formulas (P26).

### 8.3 Account lifecycle with reservations

- **Archive:** allowed (P09).
- **Delete:** pre-checks return 409 `AccountReferencedByGoalAllocation` /
  `AccountReferencedByRule`; FK RESTRICT is the last line of defense. This is
  mandatory: deleting the only linked Income can leave an Account with no ledger
  rows but live reservations, where today's history check would pass and the FK
  would surface as a 500.
- **Currency change:** pre-check returns 409 when referenced by goal rows or
  rules; the composite FK is the last line of defense (VF-018C pattern).

---

## 9. Goal Priorities (PROPOSED; principles follow APPROVED P48)

- `priority_rank` INT, 1 = highest; only active Goals are ranked.
- Deterministic order: `(priority_rank NULLS LAST, created_at, id)`.
- Reorder: `PUT /api/v1/goals/priorities` with the complete ordered list of the
  user's active Goals; under the user lock L0 (§14) the Goals are locked in
  ascending UUID order and ranks rewritten as 1…n; idempotent.
- No database uniqueness on rank (a partial unique index cannot be deferrable);
  the tie-break plus the locked rewrite are sufficient.
- Archive sets `priority_rank = NULL`; reactivation appends the Goal last.
- Rule order precedes Goal priority (P48 levels 3 → 4); Goal priority orders the
  targets **inside** one rule.
- A priority change affects only future evaluations; a deadline affects only estimates.

---

## 10. Rules Engine

### 10.1 v1 scope

| Type | Kind | Mode | v1 |
|---|---|---|---|
| `INCOME_ALLOCATION` | internal reservation | AUTO / CONFIRM (P01) | yes |
| `MINIMUM_UNALLOCATED_FLOOR` | per-Account constraint + alert | — | yes |
| `OVERCOMMITMENT_ALERT` | alert | — | yes |
| `BUDGET_ALERT` | alert observing Budgets | — | yes |
| `GOAL_DEADLINE_ALERT` | alert | — | optional |
| Scheduled (calendar) allocation | reservation | AUTO / CONFIRM | **no**: requires a user timezone (P41) and a scheduler |
| Proportional / residual / deadline-weighted distribution | — | — | deferred |

### 10.2 Definition

Typed: a Pydantic discriminated union by `rule_type`. **No scripts, no
expressions, no user-supplied code.**

`INCOME_ALLOCATION` fields:

| Field | Meaning |
|---|---|
| `name`, `status` (draft/enabled/paused/disabled), `execution_mode`, `execution_order`, `version` | |
| `active_since` | timestamptz; start of the current enabled period, reset on every enable |
| `effective_from` | date; defaults to the activation date |
| `source_account_id` | exactly one Account (P31) |
| `income_sources` | subset of {salary, freelance, gift, other, refund}; `refund` excluded by default (P35) |
| `policy` | `FIXED_PER_GOAL` \| `PERCENT_OF_INCOME_WATERFALL` |
| `percent` | 0 < p ≤ 100, two decimals |
| targets | `(goal_id, amount_or_cap, position)`; every target Goal's currency equals the source Account currency |
| `cap_at_target` | default true |
| `allow_partial` | default false (P29) |

Rule **validity** (source Account active, targets active, currencies equal) is
derived at read and evaluation time, not stored; an invalid rule produces
`blocked` executions (P37).

### 10.3 Versions

A material edit increments `version`; executions store the version and a
parameter snapshot. An edit cancels open proposals (`cancelled: superseded`,
which ends their holds) and does **not** reset `active_since`, so it causes no
re-execution of historical Income.

### 10.4 Policies

- `FIXED_PER_GOAL`: fixed amounts per target.
- `PERCENT_OF_INCOME_WATERFALL`: `total = ROUND_DOWN(Income.amount × percent / 100, 0.01)`
  (P44, P45), filled in Goal priority order; each target is limited by
  `min(rule cap, max(target_amount − total(G), 0) if cap_at_target)`.
- Percentage basis is `Income.amount` in the Account/Goal currency, never
  `base_amount` (P44).

### 10.5 Precedence (APPROVED P48), applied inside one coordinated transaction (§14)

1. Ownership and hard invariants (E1–E10, active statuses, currency, idempotency).
2. `rule_capacity` of the source Account (reservable − floor − active holds).
3. Rule order: `execution_order`, `created_at`, `id` (P28).
4. Goal priority inside the rule (§9).
5. Caps: per target → target remainder → rule total.
6. Rounding: `ROUND_DOWN` 0.01; remainder unallocated (P45).
7. Partial policy (P29).

### 10.6 Safety floor (APPROVED P56)

`MINIMUM_UNALLOCATED_FLOOR(A, amount)` is strict for every rule-generated
allocation on A (AUTO executions and CONFIRM confirmations). An explicit manual
reservation below the floor is allowed with a warning, but only within
`reservable` and all other hard invariants.

### 10.7 Examples (each names its policy)

Setup for A–D: today 2026-10-10; CHK (EUR) opening 2,000.00 dated 2026-10-01,
500.00 already reserved for G1; G1 rank 1 (target 3,000), G2 rank 2 (target
5,000), G3 rank 3 (target 1,000); no future rows, no planned Transfers, no
holds. Rule R: `PERCENT_OF_INCOME_WATERFALL` 20 %, source CHK, sources
{salary}, caps G1 300 / G2 200 / G3 none, `cap_at_target`,
`allow_partial = false`, floor(CHK) = 1,000. A salary of 3,000.00 is recorded
with `received_at` = today, linked to CHK.

| Example | Calculation | Result |
|---|---|---|
| A | total 600; balance as of today 5,000, reserved 500, unallocated 4,500; rule_capacity 3,500 | G1 300 · G2 200 · G3 100; reserved 1,100; unallocated 3,900 |
| B | floor 4,200 → rule_capacity 300 < 600 | `skipped (insufficient_capacity)`; with `allow_partial`: G1 300, `executed_partial` |
| C | 3,333.33 × 7 % = 233.3331 | G1 233.33; 0.0031 unallocated |
| D | R (order 1) as in A; R2 (order 2) `FIXED_PER_GOAL` G3 4,000 | R 600; R2 sees 2,900 < 4,000 → `skipped` |
| E | rule_capacity 600; R1 (order 1) FIXED G1 500; R2 (order 2) FIXED G3 400 | R1 500, remaining 100, R2 `skipped`; with R2 `allow_partial`: G3 100 |

---

## 11. AUTO and CONFIRM (P01 APPROVED)

### 11.1 AUTO

- Explicit enable after a preview; pause and disable are always available.
- Internal reservations only; no external movement (P16).
- Executes through the durable dispatcher (§12), in one transaction per
  triggering event (§14).
- Idempotent (§13), recoverable (§12), audited (`rule_execution_audit`).
- No retroactive execution (P46, §16).
- Guaranteed **unattended** execution only with the durable periodic
  dispatcher (P50); otherwise execution happens at the next supported drain.

### 11.2 CONFIRM

- A proposal is an execution in `awaiting_confirmation` with planned items. It
  writes **no** reservation and **no** GoalTransaction, and it may fail at
  confirmation: CONFIRM is not guaranteed execution.
- The user sees the source, the Goals, the amounts, current figures and
  expected figures after execution.
- Expiry: 7 days after creation (P54), applied lazily at read, confirmation and
  dispatch. An expired proposal can never be confirmed; a repeated action
  returns `expired`.

### 11.3 Soft capacity holds (APPROVED P55)

- Each proposal gets a monotonically increasing `hold_sequence`, assigned at
  creation in processing order (event order, then P48 rule order).
- A proposal's hold is active while it is `awaiting_confirmation` and
  `expires_at > now`; it ends on `executed`, `rejected`, `expired` or
  `cancelled` (including `superseded`).
- Later rule evaluations (AUTO and new proposals) subtract **all** active holds
  on the Account: `rule_capacity = reservable − floor − active_holds`.
- Confirming proposal X requires `confirm_capacity(X) ≥ Σ planned amounts of X`, where
  `confirm_capacity(X) = reservable − floor − Σ(active holds on the Account with hold_sequence < X.hold_sequence)`.
  X never counts against itself; proposals created after X already accounted
  for X's hold.
- Holds do not block Expenses, Transfers or manual reservations; a manual
  reservation may consume the underlying capacity, which is why every
  confirmation fully revalidates.

### 11.4 Confirmation procedure

Under locks (L0 → execution → Goals → Account):

1. the rule is enabled, valid and at the proposal's version;
2. the source Income still exists, matches the snapshot and is still eligible;
3. the Goals and the Account are active;
4. the §11.3 confirmation capacity covers exactly the proposed amounts.

If all hold: `executed`, GoalTransactions written, hold ended. Otherwise 409
and `cancelled (stale)`, hold ended, nothing written. Nothing is silently
recalculated. A repeated confirmation returns the stored result; rejection
(`rejected`) is final.

### 11.5 Audit codes

proposed, applied, applied_partial, skipped, blocked, confirmed, rejected,
expired, cancelled (superseded / stale / source_changed / source_deleted /
rule_inactive), source_changed, source_deleted. Retries are visible on the
event (§12). Completed executions are never rewritten; annotations are only
appended.

---

## 12. Durable Event Delivery / Outbox (F1)

### 12.1 Options considered

| Option | Atomic with Income | Recovery | Complexity | Verdict |
|---|---|---|---|---|
| Processing only after commit (v0.2) | no | events lost on crash | low | rejected |
| Transactional outbox `financial_events` + database dispatcher | **yes** | yes (leases, retries) | moderate | **chosen** |
| External message broker | no (needs an outbox anyway) | yes | high, new infrastructure | rejected without evidence |

### 12.2 Write

- `income_service` create/update/delete inserts one `financial_events` row in
  the **same** transaction (`commit=False`, single commit) through a narrow
  function of the events module. Types: `income.created`, `income.updated`,
  `income.deleted`.
- A failed Income write rolls back → no event. A committed Income always has its event.
- The event stores provenance (§16), a typed source snapshot (`amount`,
  `currency`, `received_at`, `account_id`, `income_source`,
  `aggregate_updated_at`) and `not_before` (start of the `received_at` day for a
  future-dated Income, otherwise now).

### 12.3 Event states

| Status | Meaning | Terminal |
|---|---|---|
| `pending` | committed and waiting (possibly deferred by `not_before`) | no |
| `processing` | claimed; `lease_expires_at` set; `attempts` already incremented | no |
| `processed` | handled; `outcome_summary` holds non-monetary codes | yes |
| `failed_retryable` | technical failure; `next_attempt_at` set | no |
| `dead` | `attempts ≥ max_attempts`; visible to the user and operations; manual re-queue allowed | yes (until re-queued) |

Delivery is at least once. The exactly-once **financial effect** comes from
execution uniqueness (§13), not from delivery.

### 12.4 Claim and process

1. **Claim** (short transaction): `status = 'processing'`, `attempts + 1`,
   `lease_expires_at = now + lease`, only if the event is due. Counting attempts
   before processing bounds events that crash the process.
2. **Process** (one transaction per event, §14): L0 → event `FOR UPDATE` →
   verify it is still claimed and is the user's oldest due event (P52) → rules →
   executions → Goals → Account → writes → `processed` → commit.
3. **Technical error:** rollback, then a short transaction sets
   `failed_retryable` with `next_attempt_at` per backoff; `deadlock_detected`
   and serialization failures are retryable.
4. **Crash** before or during processing: the database rolls back; the lease
   expires; the event becomes claimable again with its attempts counted.

"Due" = `pending` with `not_before ≤ now`; or `failed_retryable` with
`next_attempt_at ≤ now`; or `processing` with `lease_expires_at < now`.

Backoff (PROPOSED): `max_attempts = 6`, delays 1 min, 5 min, 30 min, 2 h, 12 h,
then `dead`. Lease: 5 minutes.

### 12.5 Consumption and guarantees

| Mechanism | Durable | Guarantee |
|---|---|---|
| (a) Best effort after the response (e.g. FastAPI `BackgroundTasks` in the same process) | no | usually within seconds; may be lost on a crash, but the event stays `pending` |
| (b) User-triggered drain: `POST /api/v1/financial-rules/evaluate` on app foreground and Inbox open; at most N due events of **that** user | yes (reads the outbox) | processed at the user's next activity |
| (c) Durable periodic dispatcher (APPROVED requirement P50) | yes | eventual processing **without** user activity, within the configured cadence (target ≈ 10 min) |

- Mechanism (c) is required before `AUTO` is presented as guaranteed unattended
  automation (GA). Its technology (a hosting-platform scheduled job, another
  supported scheduled execution mechanism, or another small durable backend
  mechanism) is selected and technically verified during VF-020E; this contract
  does not fix it.
- Without (c), a beta must truthfully state that `AUTO` executes after the
  transaction and at the latest at the next supported user-triggered drain.
- A message broker is not needed.

### 12.6 Bounded queries

The dispatcher reads only `financial_events` through partial indexes on due
statuses; it **never scans** `income`. Batches: K users per pass, at most M
events per user.

### 12.7 Failure cases

| Failure | Outcome |
|---|---|
| Income rolled back | no event |
| Crash after commit, before dispatch | event stays `pending` → (b) or (c) |
| Crash during processing | rollback; lease expires; retried |
| Business rule outcome | terminal execution (`blocked`/`skipped`); event `processed` |
| Technical error | `failed_retryable` → retries → `dead` |
| Source changed after the event | detected via snapshot vs `aggregate_updated_at` (§15) |
| Duplicate dispatch | the second worker sees `processed` under L0 → no-op |

### 12.8 Operational readiness

Metrics: counts per event status; age of the oldest due event; processing time;
attempt distribution. Alerts: oldest due event older than ~3× the dispatcher
cadence (with (c) enabled); any `dead` event. A runbook for `dead` events.
Logs contain no amounts or personal data beyond identifiers.

### 12.9 Retention

Processed events are kept as the durable provenance record (§16); retention and
deletion follow the user-data deletion policy (P53; VF-021 data: EXT).

---

## 13. Execution State Machine and Idempotency (F2)

### 13.1 Four entities

| Entity | Storage | Identity |
|---|---|---|
| Source-trigger event | `financial_events` | `id`; `income.created` unique per Income |
| Evaluation attempt | `financial_events.attempts`, `last_error_code`, timestamps (no separate table) | (event, attempt number) |
| Financial execution (one rule's decision about one source) | `rule_executions` + `rule_execution_items` | `UNIQUE(user_id, rule_id, source_type, source_id)` |
| CONFIRM proposal | the **state** `awaiting_confirmation` of that execution | same as the execution |

Audit: `rule_execution_audit`, append-only, records every transition and annotation.

### 13.2 Retry vs uniqueness

An execution row is created **only inside the successful processing
transaction**. A technical failure rolls the row back as well, so the retry
sees no row and evaluates again. A **business** outcome (executed, skipped,
blocked, proposal) is a committed row and is the final decision. Hence E10: "no
**committed** execution exists for (R, I)": retries are possible, duplicates
are not.

### 13.3 Execution states

| State | Terminal | Retry | Reopens after source change | Confirmable | Writes goal rows | Duplicate request | Audit |
|---|---|---|---|---|---|---|---|
| `awaiting_confirmation` | no | — | no; a source change → `cancelled` | **yes** | no (only on confirmation) | returns the proposal | proposed |
| `executed` | yes | no | no; annotations only | no | **yes**, once, in the same transaction | replay | applied |
| `executed_partial` | yes | no | no; annotations only | no | **yes** | replay | applied_partial |
| `skipped` | yes | no | no | no | no | replay | skipped + reason |
| `blocked` | yes | no | no | no | no | replay | blocked + reason |
| `rejected` | yes | no | no | no | no | replay | rejected |
| `expired` | yes | no | no | no | no | replay | expired |
| `cancelled` | yes | no | no | no | no | replay | cancelled + reason |

"Not eligible" is **not** stored as an execution; it is recorded in the event's
`outcome_summary`. A later correction can therefore make the Income eligible,
but only within the provenance and window rules of §15–§16.

### 13.4 Unique key `UNIQUE(user_id, rule_id, source_type, source_id)`

| Case | Supported | How |
|---|---|---|
| Retry after a technical failure | yes | no committed row → evaluated again |
| Rule edit / new version | yes | the key excludes the version; historical Income is **not** executed again; open proposals → `cancelled: superseded` |
| Disable / re-enable | yes | `active_since` reset; Income from the disabled period is not eligible (E5) |
| Expired / cancelled proposal | yes | terminal; **no** new proposal for the same source |
| Manual evaluation | yes | only drains events; creates no new identities |
| Repeated delivery | yes | row exists → replay |
| Backfill suppression | yes | not eligible by provenance → no row; provenance is permanent, so it never becomes eligible |
| Bypass through a new identity | **forbidden** | `source_id` is always the canonical Income id; a new id exists only for a new canonical record with its own provenance |

---

## 14. Deterministic Concurrency and Lock Ordering (F3)

### 14.1 Options

| Option | Atomicity | Partial failure | Retry | Lock duration | Rule order |
|---|---|---|---|---|---|
| 1. One transaction for all rules of one event | all or nothing per event | impossible (rollback) | whole event, deterministic | short | **guaranteed** within the event |
| 2. One transaction per rule + claiming | per rule | possible | per rule | short | needs extra serialization; an Account row lock alone does not enforce priority |
| 3. Database dispatcher with per-user coordination | — | — | leases | — | orders events relative to each other |

**Design (PROPOSED): 1 + 3.** All rules of one event are processed in one
transaction in P48 order with a running capacity; events of one user are
serialized by the user lock L0, FIFO among due events (P52).

### 14.2 Global lock order

| Level | Lock | Taken by |
|---|---|---|
| L0 | `pg_advisory_xact_lock(key(user_id))` (alternative: a per-user lock row) | **every** write of the goals and financial-rules modules: manual goal transactions, Goal CRUD/archive, priority reorder, rule create/edit/state, confirm/reject, dispatcher |
| L1 | event `FOR UPDATE`, then execution rows (`INSERT … ON CONFLICT DO NOTHING` + `SELECT … FOR UPDATE`) | dispatcher, confirm/reject |
| L2 | Goals `FOR UPDATE`, ascending UUID (all targets of all rules, locked together) | goal-financial paths |
| L3 | Accounts `FOR UPDATE`, ascending UUID | goal-financial paths |
| — | canonical row → Accounts ascending UUID (INV-05) | existing Income/Expense/Transfer/adjustment paths, **unchanged** |

Cycle analysis:

- Existing canonical paths never take or wait on L0–L2; they hold a canonical
  row plus Accounts.
- VF-020 paths never lock Income, Expense or Transfer rows; the dispatcher reads
  the Income without a lock and compares the snapshot. Planned Transfers are
  read without locks for `planned_transfer_out`.
- The only shared lock class is L3, which both families take last, so the
  design has no lock cycle by construction.
- Account lifecycle paths lock the Account and only **read** goal references.
- FK checks: inserting a goal row takes `KEY SHARE` on a Goal and an Account the
  transaction already holds `FOR UPDATE`; deleting an Account checks append-only
  `goal_transactions`, which are never updated.
- Cross-user: L0 keys differ; a hash collision only serializes two users.
- No network calls under locks: FX is resolved by Income before its locks; the
  dispatcher performs no network calls.

Deadlock freedom is a **design claim** that must be confirmed by CT-01…CT-12
(§25); any `deadlock_detected` is handled as a retryable failure.

### 14.3 Timeline: higher-priority rule wins (S31)

Setup: CHK `rule_capacity` = 600. R1 (order 1) FIXED G1 500, AUTO. R2 (order 2)
FIXED G3 400, AUTO. Salary event E. Worker W1 (after-response task) and worker
W2 (drain) start together.

```
t0  W1: claim E (processing, attempts=1)     W2: claim fails (E is processing, lease active)
t1  W1: BEGIN; L0(user) acquired
t2  W1: E FOR UPDATE; oldest due event of the user? yes
t3  W1: load enabled rules [R1, R2] ordered by (execution_order, created_at, id)
t4  W1: insert-or-get executions (R1, income), (R2, income) FOR UPDATE
t5  W1: lock Goals {G1, G3} ascending; lock CHK
t6  W1: capacity 600 → R1 500 → executed; running 100
                    → R2 400 > 100, allow_partial = false → skipped (insufficient_capacity)
t7  W1: insert goal_transactions (G1, CHK, 500, rule_execution_id = R1 execution); E processed; COMMIT
t8  W2: later drain → E processed → no-op
```

A concurrent manual reservation M (G3, 400, CHK) is serialized by L0: if M runs
first, reservable becomes 200 and both R1 and R2 are `skipped`; if W1 runs
first, M sees reservable 100 and gets 409. Both outcomes are deterministic and
neither violates P48 within the event.

### 14.4 Separate events for one Account

Serialized by L0 in FIFO order among due events (`occurred_at`, `id`). A failed
event blocks newer **due** events of the same user until it succeeds or becomes
`dead` (P52, PROPOSED). Events deferred by `not_before` do not block. FIFO
applies to *committed* events; an event that commits after a newer one was
processed is processed when it becomes visible.

---

## 15. Income Eligibility and Correction Handling

### 15.1 Predicates (P35, P46, P51 APPROVED; formalization below)

Evaluated when an event is processed, against the **current** Income state.

| # | Predicate | On failure |
|---|---|---|
| E1 | Income, rule and event belong to one user | not eligible |
| E2 | Income is linked to `R.source_account_id` | not eligible |
| E3 | `received_at ≤ D` | event **deferred** (`not_before = received_at`) |
| E4 | The Income's **creation** event has provenance `manual/live` (v1; `import/live` only in VF-021 under its policy) | not eligible (permanent) |
| E5 | The creation event occurred at or after `R.active_since`, and `received_at ≥ R.effective_from` | not eligible (permanent) |
| E6 | `received_at ≥ date(triggering_event.occurred_at) − 7 days` (inclusive; P51) | not eligible |
| E7 | `income.source ∈ R.income_sources` (`refund` excluded by default) | not eligible |
| E8 | Income/Account currency = every target Goal's currency | `blocked` |
| E9 | Account active; targets active (archived → blocked; completed → allowed, P11); rule valid | `blocked` |
| E10 | No **committed** execution exists for (R, I) | replay / annotation |

### 15.2 Processing by event type

- `income.created`: E1–E10 for every enabled rule in P48 order.
- `income.updated`: existing `executed` / `executed_partial` → audit
  `source_changed` when the snapshot differs; `awaiting_confirmation` →
  `cancelled (source_changed)` (hold ends); no row → E1–E10, where E6 is
  measured from the **update** time while E4/E5 still use the **creation**
  provenance, so an old Income can never become eligible through an edit.
- `income.deleted`: executions get `source_deleted`; proposals →
  `cancelled (source_deleted)` (hold ends); floor and overcommitment alerts are
  re-evaluated; **no compensating entries** (P47).

### 15.3 Corrections after execution (P47)

| Change | Execution | Reservations | Derived state | User |
|---|---|---|---|---|
| Amount decreased | `source_changed` annotation | unchanged | recomputed | alert + "Release" option |
| Amount increased | annotation; **no** additional allocation | unchanged | recomputed | option to top up manually |
| Date moved into the future | annotation | unchanged | `balance_as_of` decreases; may become overcommitted | alert |
| Date moved earlier | annotation | unchanged | recomputed | info |
| Moved to another Account | annotation | **stay** on the original Account | original loses capacity, new gains it | alert if overcommitted |
| Unlinked from its Account | annotation | stay | capacity decreases | alert if overcommitted |
| Deleted | `source_deleted`, snapshot kept | stay | recomputed | alert + "Release" option |
| Late historical entry | — (E4/E5/E6) | — | — | Income recorded normally |
| Duplicate trigger | replay (E10) | — | — | — |
| Technical failure | no row; event retried | — | — | `dead` visible |

---

## 16. Historical Import Provenance (F4)

### 16.1 Owner and form

Provenance belongs to the **events module**. It is set by the module that
performs the canonical mutation, at mutation time, in the same transaction.
`income.source` (salary/…/refund) is **not** overloaded, and VF-020 adds **no**
column to `income`. VF-021 adds its own import-link record (imported event →
canonical record, sync run, batch) carrying the same classification.

- `origin` ∈ {`manual`, `receipt`, `import`, `system`}
- `ingestion_mode` ∈ {`live`, `historical`, `correction`}

The provenance of an Income is the `origin` / `ingestion_mode` of its unique
`income.created` event. An Income created before VF-020 has no creation event
and is treated as `historical`: never eligible.

### 16.2 Classification

| Situation | origin / mode | AUTO-eligible |
|---|---|---|
| Manual Income with `received_at ≥ created_date − 7 days` (future dates included, deferred) | manual / live | yes (E1–E10) |
| Manual Income with `received_at < created_date − 7 days` | manual / historical | **no** |
| Correction of an existing Income | manual / correction (`income.updated`) | first eligibility only per §15.2 |
| Live import (incremental sync, VF-021) | import / live | yes, only through the canonical Income and only if the import posting policy allows (P23) |
| Historical backfill / reconnect (VF-021) | import / historical | **no** |
| Duplicate provider delivery | no canonical change → **no event** | — |
| Pending → booked (VF-021) | import / correction, or a match to an existing record | no new execution |
| Reclassification Expense → Income (VF-021) | import / correction | **no** (PROPOSED) |
| Receipt-derived record | receipt (creates an Expense, not Income) | not a trigger in v1 |
| Reconciliation with an existing manual record | evidence link, no new canonical record | — |

For VF-021, classification comes from the import provenance (sync run type,
batch), never from timestamps alone (P51).

### 16.3 Guarantees

An old transaction imported today is not a new economic event. Reconnects,
duplicates and reclassifications do not re-run rules. A manual historical entry
does not become eligible merely because it was just created. `received_at` and
`created_at` keep their meaning; Income and Financial Overview semantics do not
change.

---

## 17. Budgets Integration (P40 EST)

- Budgets are the **only** source of spending limits; rules store no limits and
  no periods.
- `BUDGET_ALERT` uses the same computation as
  `GET /api/v1/analytics/budget-status` (`budget_metrics`), preserving the
  weekly/monthly/yearly semantics.
- It fires on transitions to `watch`, `at_risk` or `exceeded` per
  `(budget_id, period_start)`; deduplicated per level per period
  (`rule_alerts` unique key); only escalations re-alert.
- Alerts are evaluated during drains, manual evaluation and periodic recovery:
  detection happens at the next evaluation, not in real time.
- Optional internal guard on allocation rules ("skip if the selected Budget is
  `exceeded`"): PROPOSED, may be deferred.
- **An alert never blocks an Expense.**

---

## 18. Goal, Account and Rule Lifecycle

| Object | Action | Contract |
|---|---|---|
| Goal | create / edit | under L0; currency validation hardened (G1) |
| Goal | archive | allowed; `priority_rank = NULL`; new contributions → 409 (P10); withdrawals and releases allowed; rules targeting it → `blocked` |
| Goal | complete | manual status; no restrictions (P11) |
| Goal | delete | only without history (EST); also 409 if referenced by a rule target (P57) |
| Goal | currency | immutable once history exists (EST); composite FK as last line of defense |
| Account | archive | allowed; reservations kept; new linked contributions → 409; releases allowed; rules → `blocked` |
| Account | delete | pre-checks: ledger history (EST), planned Transfers (EST), goal references, rule references → 409 |
| Account | currency | pre-checks: history, planned Transfers, goal and rule references → 409 |
| Rule | create / edit | under L0; validation; an edit increments `version` and cancels open proposals |
| Rule | enable | `active_since = now()`; preview required for `AUTO` |
| Rule | pause / disable | events processed without it; proposals → `cancelled (rule_inactive)` |
| Rule | delete | only without executions; otherwise disable (P57) |
| Income | create / update / delete | unchanged behavior + one outbox event in the same transaction |
| Transfer | planned / post / delete | unchanged; affects capacity per §8 (P49) |

---

## 19. Database Schema Candidates (not approved migrations)

### 19.1 `goals` (VF-020B; rank in VF-020D)

`uq(id, user_id)`, `uq(id, user_id, currency)`;
`CHECK status IN ('active','completed','archived')`;
`CHECK currency ~ '^[A-Z]{3}$'`; `priority_rank INT NULL`;
`description VARCHAR(255) NULL` (PROPOSED).

### 19.2 `goal_transactions` (VF-020B/C)

Columns per §7.3. FKs: `(goal_id, user_id, currency)` → `goals` RESTRICT
(closes G3); `(account_id, user_id, currency)` → `accounts` RESTRICT;
`(rule_execution_id, user_id)` → `rule_executions` RESTRICT. The
`opening_balance` CHECK; partial `UNIQUE(user_id, client_request_id)`; partial
index `(account_id) WHERE account_id IS NOT NULL`.

### 19.3 New tables (each with the Supabase Data API REVOKE)

| Table | Key fields |
|---|---|
| `financial_events` | `id`, `user_id`, `event_type`, `aggregate_type`, `aggregate_id` (soft reference), `origin`, `ingestion_mode`, snapshot (`snap_amount NUMERIC(12,2)`, `snap_currency`, `snap_received_at`, `snap_account_id`, `snap_income_source`, `snap_aggregate_updated_at`), `occurred_at`, `status`, `not_before`, `attempts`, `next_attempt_at`, `lease_expires_at`, `last_error_code`, `processed_at`, `outcome_summary JSONB` (codes only). Partial `UNIQUE(aggregate_id) WHERE event_type = 'income.created'`; partial index `(user_id, occurred_at, id)` on non-terminal statuses; index `(status, not_before, next_attempt_at)`; CHECKs on enumerations |
| `financial_rules` | `id`, `user_id`, `name`, `rule_type`, `status`, `execution_mode`, `execution_order`, `version`, `active_since`, `effective_from`, `source_account_id` (composite FK to accounts), `policy`, `percent`, `cap_at_target`, `allow_partial`, `income_sources text[]` (CHECK subset), `floor_amount NUMERIC(12,2)` (floor type only; per-type CHECK), timestamps; `uq(id, user_id)` |
| `financial_rule_goal_targets` | `rule_id`, `user_id`, `goal_id` (composite FKs to rule and Goal), `amount_or_cap NUMERIC(12,2) NULL`, `position` |
| `rule_executions` | `id`, `user_id`, `rule_id` (composite FK RESTRICT), `rule_version`, parameter snapshot, `source_type`, `source_id` (**soft reference**: Income CRUD is never blocked and history survives deletion), `triggering_event_id`, source snapshot, capacity snapshot (`reservable`, `floor`, `holds`), `status`, `reason_code`, `hold_sequence BIGINT` (identity), `expires_at`, `decided_at`, timestamps; `UNIQUE(user_id, rule_id, source_type, source_id)`; `uq(id, user_id)` |
| `rule_execution_items` | `execution_id`, `user_id`, `goal_id`, `account_id`, `position`, `planned_amount`, `applied_amount NULL`, `goal_transaction_id NULL UNIQUE` |
| `rule_execution_audit` | `id`, `execution_id`, `user_id`, `code`, `actor` (system/user), `related_event_id`, `details` (codes), `created_at`; append-only |
| `rule_alerts` | `user_id`, `rule_id`, `subject_type`, `subject_id`, `period_key`, `level`, `created_at`, `acknowledged_at`; `UNIQUE(rule_id, subject_type, subject_id, period_key, level)` |

### 19.4 Migration principles

Before any constraint migration: a **read-only production verification**, with
explicit authorization, of valid currency codes, valid statuses and
goal-owner = transaction-owner. A mismatch is a data incident: stop. Then
backup, migration plan and approval (G3). The only data operation is the
`currency` copy. Applied migrations are never rewritten.

---

## 20. API Contracts (candidates)

### 20.1 Goals

- `POST /api/v1/goals/{id}/transactions`: `type`, `amount`, `description?`,
  `account_id?`, `effective_date?`, `client_request_id?`. Responses: 201
  created; 200 replay; 404 not owned or missing; 409 partition, capacity,
  archived Goal/Account, idempotency conflict; 422 currency, future
  `effective_date`, `effective_date ≠ today` for a linked row (P58), missing key
  where required. A manual reservation that leaves `reservable` below the floor
  succeeds with a warning field (P56).
- `GET /api/v1/goals`, `PATCH /api/v1/goals/{id}`: + `priority_rank`,
  `tracked_amount`, `linked_amount`, `allocations[]`,
  `monthly_contribution_estimate` (backend-computed, ROUND_UP 0.01, PROPOSED).
- `PUT /api/v1/goals/priorities`.

### 20.2 Idempotency transition (P14 APPROVED; cutover timing P59 PROPOSED)

1. VF-020B: `client_request_id` optional for tracked operations (requests
   without a key behave as today, **without** an exactly-once guarantee),
   required for linked operations; the updated mobile client always sends it.
2. After all supported clients send it: required for every operation (422
   without it), timing per P59.

### 20.3 Accounts

`GET /api/v1/accounts` adds `balance_as_of_today`, `scheduled_outflows`,
`planned_transfer_outflows`, `reserved_amount`, `unallocated_amount`,
`reservable_amount`, `allocation_status`, `negative_balance`, and
`proposal_holds_amount` (informational). `current_balance` is unchanged.

### 20.4 Rules

- `POST/GET/PATCH/DELETE /api/v1/financial-rules`;
  `POST /api/v1/financial-rules/{id}/enable|pause|disable`.
- `POST /api/v1/financial-rules/{id}/preview`: dry run, writes nothing.
- `POST /api/v1/financial-rules/evaluate`: drains **only the caller's** due
  events (bounded) and evaluates alerts; idempotent; returns a summary; never
  scans historical Income.
- `GET /api/v1/rule-proposals`, `POST /api/v1/rule-proposals/{id}/confirm`,
  `POST /api/v1/rule-proposals/{id}/reject`.
- `GET /api/v1/rule-executions` (items and audit, paginated).
- `GET /api/v1/rule-alerts`, `POST /api/v1/rule-alerts/{id}/acknowledge`.

### 20.5 Dispatcher

No public cross-user endpoint. The periodic dispatcher (P50) runs as a backend
module invoked by the verified scheduled mechanism.

### 20.6 Conventions

Bearer JWT; 401 unauthenticated; 404 for anything not owned; 409 domain
conflict; 422 invalid input; decimals as strings; pagination; bounded queries.

---

## 21. Mobile UX (VF-020 v1)

Expo SDK 57; everything works in **Expo Go**; no new native dependencies.

- **Goals:** rank, progress, tracked/linked amounts, deadline, monthly estimate, rule badges.
- **Goal detail:** history by partition; contribute and release with partition
  selection (existing `account-picker.tsx`); reorder; floor warning on manual
  reservations.
- **Accounts:** recorded balance, balance as of today, reserved, unallocated,
  reservable, overcommitted / scheduled-shortfall badges.
- **Rules:** create, preview, AUTO/CONFIRM, enable/pause, history, failures.
- **Inbox:** proposals with their expiry (confirm/reject with revalidation
  messages), alerts, results, `dead` events.
- **Drain:** `POST /api/v1/financial-rules/evaluate` on `AppState` → active and
  when the Inbox opens; on reported changes, invalidate the families below.
- **Texts:** "Tracked (not linked to an account)" vs "Reserved in <Account>";
  "Unallocated" is never presented as money guaranteed to be available at the
  bank. Without the periodic dispatcher, AUTO copy says rules run "after you
  record income, or the next time you open the app".

| After | Invalidate |
|---|---|
| tracked goal transaction | `["goals",uid]`, `["goals","transactions",uid,id]`, `["analytics","goal-progress",uid]` |
| linked goal transaction | the above + `["accounts",uid]` |
| priority reorder | `["goals",uid]`, `["financial-rules",uid]` |
| rule changes | `["financial-rules",uid]`, `["rule-proposals",uid]`, `["accounts",uid]` (holds) |
| confirm / reject / drain with changes | `["rule-proposals",uid]`, `["rule-executions",uid]`, `["rule-alerts",uid]` + linked-transaction families |
| Income create/update/delete | existing families + `["accounts",uid]` + rule families |
| Expense / Transfer (incl. planned) / adjustment | existing families + `["accounts",uid]` + `["rule-alerts",uid]` |

Financial Overview is **not** invalidated by reservations or holds. Not in v1:
push notifications, scheduled rules, wallets, bank redirects (§22.2).

---

## 22. VF-021 Connections and Import (separate milestone)

Independent of the VF-020 sequence; discovery may proceed in parallel; no
integration code before G2 and G5.

### 22.1 Consent and connections (EXT)

Disclosure: provider, institution, data categories, accounts, purpose,
retention, expiry, disconnect. Consent record: `user_id`, provider, external
reference, scope, sources, `authorized_at`, expiry, state, revocation, policy
version; credentials stored separately and encrypted. States: `initiated`,
`authorization_pending`, `active`, `reauthorization_required`,
`temporarily_unavailable`, `revoked`, `expired`, `failed`; a revoked connection
fetches nothing. Read-only access initially; provider-approved flows; PKCE,
state/nonce; verified webhooks; least privilege. Regulation (P20): AISP model
or regulated partner, PSD2 and national rules, GDPR basis, processor
agreements, cross-border processing, DPIA.

### 22.2 Platforms (P22, EXT)

No universal Apple Wallet or Google Wallet transaction access is claimed.
FinanceKit requires an entitlement, an eligible region and a development build
(not Expo Go). Google Pay is not a purchase-history source. Payment apps each
need their own assessment. Production bank redirects need a unique app scheme
or universal links. No scraping, private APIs or credential collection.

### 22.3 Account mapping and balances

`ExternalAccountMapping` to an existing internal Account; never a silent merge;
exact currency match. A provider balance is an observation with a difference
and a status (P26); no synthetic adjustments.

### 22.4 Pipeline

Fetch → minimized evidence → normalize → deduplicate → reconcile → classify →
canonical posting (P23) → ledger → analytics invalidation → `financial_events`
with provenance (§16) → rules → audit.

### 22.5 Reconciliation

| Pair | Outcome |
|---|---|
| Manual record ↔ import | candidate match; review when ambiguous; user data preserved; counted once |
| Receipt-confirmed Expense ↔ import | link to the existing Expense |
| Pending ↔ booked (different id and amount) | one economic event; a correction, not a new record |
| Reconnect / overlapping sync | stable references → no new records; fallback → review |
| Two owned legs | one AccountTransfer (same currency); never Income + Expense |
| One owned leg | review |
| Several providers for one account | one mapping; conflict → review |

REC-1: one economic event ↔ at most one canonical record. REC-2: an imported
event links to at most one canonical record. REC-3: a canonical record may have
several pieces of evidence. REC-4: user annotations are never overwritten
without a defined rule.

### 22.6 Unsupported instruments (P38, P39)

Card liabilities and card FX settlement are research topics; such events stay in
`requires_review`. Synthetic Income or Expense is **never** created for
unmodeled activity.

### 22.7 Synchronization and completeness

Backfill, cursors, pagination, overlapping windows, duplicates, rate limits;
at-least-once delivery with idempotent processing. Visible: last sync, missing
accounts, unmatched and failed events, staleness. `AUTO` is blocked while
required data is incomplete (P32).

### 22.8 Disconnect and retention

Disconnect stops retrieval, revokes the token, disables credentials and cancels
syncs. Retention of imported data: P27 (EXT). Manual data is never deleted.
**The previously incomplete secret rotation must be finished before storing
third-party banking tokens.** Every new table follows the Data API privilege
restrictions.

---

## 23. Security, Privacy and Regulatory Gates

| Gate | Condition |
|---|---|
| G1 Financial contract | approved decisions recorded (this document) |
| G2 Provider and regulatory (VF-021) | legal review: access model, PSD2, GDPR, agreements, retention |
| G3 Database safety | migration plan, **read-only production verification**, backup, explicit approval |
| G4 Integration verification | deterministic allocation, outbox, concurrency and reconciliation tests green |
| G5 Security review | auth, ownership, L0/locks, tokens, logs, audit, Data API REVOKE on every new table; secret rotation finished before VF-021 |
| G6 Device acceptance | real-device verification, not static checks |
| G7 Publication | independent review, PR, CI; the user performs the merge |

Additionally: rules never run user code; `evaluate` is rate-limited per user;
logs and `outcome_summary` contain no amounts or personal data; ownership tests
use a foreign-user positive control.

---

## 24. Financial Scenario Matrix

Setup unless stated: today 2026-10-10; CHK (EUR) opening 2,000.00 dated
2026-10-01; G1/G2/G3 in EUR with ranks 1/2/3. B = balance as of today,
R = reserved, U = unallocated, RS = reservable.

| # | Scenario | Result | Refs |
|---|---|---|---|
| S1 | Reserve 500 for G1 on CHK | B 2,000; R 500; U 1,500; RS 1,500; no AccountTransaction; Overview unchanged | P02, FIN-004 |
| S2 | G1: 300 tracked + 500 linked | G1 total 800; assets 2,000 | FIN-002 |
| S3 | G1 500 + G2 800 | R 1,300; U 700 | — |
| S4 | Release 200 from G1 (after S3) | R 1,100; U 900; B 2,000 | P07, FIN-004 |
| S5 | Reserve 800 when RS = 700 | 409; nothing changes | P04 |
| S6 | G1 300 tracked + 500 linked; withdraw 400 from tracked | 409; withdraw 400 from linked(CHK): OK, linked 100 | P07 |
| S7 | (after S1) linked Income 1,000 dated 10-15 | current 3,000; B 2,000; RS 1,500 (future credit adds nothing); reserving 1,800 → 409; the Income's event is deferred to 10-15 | P36, §12 |
| S8 | (after S1) linked Expense 1,200 dated 10-20 | current 800; B 2,000; U 1,500; scheduled 1,200; RS 300 | P36 |
| S9 | (after S3) Expense 1,000 today | B 1,000; U −300 → overcommitted; Goals unchanged; Overview +1,000; Expense **not** blocked | P05 |
| S10 | (after S1) posted Transfer CHK→SAV 1,800 | CHK B 200; U −300 overcommitted; SAV +1,800 | P05, INV-08 |
| S11 | Goal in USD, CHK in EUR | linked → 422; tracked allowed | P06 |
| S12 | CHK archived, R 500 | new reservation → 409; release 200 → R 300; delete → 409 | P09 |
| S13 | SAV: only a linked Income 1,000; reserve 600; Income deleted | SAV B 0; R 600; U −600; delete SAV → **409**, not 500 | §8.3 |
| S14 | RS 1,000; G1 700 and G2 600 concurrently | serialized: first OK, second 409; replay of the same key → 200 | P04, P14 |
| S15 | Legacy: opening 1,000 + contribution 200 | tracked 1,200; withdrawal 150 without account → 1,050 | P12 |
| S16 | Rule example A (§10.7), AUTO | G1 300 / G2 200 / G3 100; R 1,100; U 3,900 | P44, P48 |
| S17 | Rule example A, CONFIRM | proposal 300/200/100 with a hold of 600; nothing written until confirmed | P01, P55 |
| S18 | Rule example B (floor 4,200) | `skipped`; with `allow_partial`: G1 300 | P29, P56 |
| S19 | Rule example C (7 % of 3,333.33) | 233.33; remainder unallocated | P44, P45 |
| S20 | After S16: salary 3,000 → 2,000 | reservations unchanged; B 4,000; U 2,900; `source_changed`; alert | P47 |
| S21 | After S16: salary deleted | B 2,000; R 1,100; U 900 < floor 1,000 → floor alert (not overcommitted); `source_deleted` | P47 |
| S22 | After S16: salary moved to SAV | CHK B 2,000, U 900; SAV +3,000; reservations stay on CHK | P47 |
| S23 | Rule active since 10-05 (`effective_from` 10-05); on 10-10 a salary dated 10-07 is entered | manual/live (10-07 ≥ 10-03), E5 ✓ → eligible. A salary dated 09-28 → manual/historical, E5 ✗ | P46, P51 |
| S24 | Same Income event processed twice | one execution; replay | §13 |
| S25 | RS 600; R1 500 (order 1), R2 400 (order 2), FIXED | R1 500; R2 `skipped`; with partial on R2: 100 | P29, P48 |
| S26 | CONFIRM proposal 600 → Expense 4,000 → confirm | B 1,000; R 500; U 500; confirmation capacity −500 → 409; `cancelled (stale)`; no writes | §11 |
| S27 | Contribution to an archived Goal | 409 (P10; currently allowed → regression test) | P10 |
| S28 | Income commits; the API crashes before dispatch | event stays `pending`; processed at the next drain or by the periodic dispatcher; one execution; no invented money | F1 |
| S29 | Crash in AUTO after staging writes for three targets | rollback: no goal rows, no execution row; lease expires → retry → exactly one set of rows; nothing partial presented as success | F1, F2 |
| S30 | The same event delivered three times | one financial effect; one execution id; replays visible in the outcome | F2 |
| S31 | Two rules compete for 600 concurrently (§14.3) | R1 500, R2 skipped, on every run | F3 |
| S32 | (VF-021) rule enabled 10-01; bank connected 10-10; a 10-08 transaction arrives in backfill | Income created and counted in Overview; provenance import/historical → **no AUTO** | F4, P46 |
| S33 | (VF-021) pending P1 50.00 → booked B1 48.50 | one canonical record (correction); no duplicate record; no second execution | F4, REC-1 |
| S34 | Income deleted after an executed allocation | reservation unchanged; `source_deleted`; capacity recomputed; warning; no compensation | P47 |
| S35 | Proposal created with capacity; an Expense then reduces it | confirmation revalidates → 409, `cancelled (stale)`; no partial writes | §11 |
| S36 | (after S1) planned Transfer CHK→SAV 800, `planned_date` 10-20 | no ledger rows: current 2,000; B 2,000; U 1,500; planned out 800; **RS 700**; SAV RS unchanged (planned incoming ignored). After posting on 10-20: CHK B 1,200, planned out 0, U 700, RS 700 (no double subtraction) | P49 |
| S37 | AUTO active since 10-01; on 10-10 a salary dated 09-20 is entered | manual/historical (09-20 < 10-03) and E5 ✗ → no execution; Income recorded normally and counted in Overview | P46, P51 |
| S38 | RS 600, floor 0; one event: R1 (order 1, CONFIRM) FIXED G1 500, R2 (order 2, AUTO) FIXED G3 400 | proposal X with hold 500; R2 sees 100 → `skipped`. Confirm X: 600 − 0 (no earlier holds) ≥ 500 → executed; R 500; hold ended; own hold not double-counted | P55, P48 |
| S39 | As S38 before confirmation; the user manually reserves 300 for G2 | allowed (holds do not block manual): RS 300. Confirm X: 300 < 500 → 409, `cancelled (stale)`; nothing written | P55 |
| S40 | RS 1,500, floor 1,000; manual reservations | 800 → allowed with a floor warning (RS 700 < floor); 1,600 → 409 (exceeds reservable; the floor override never creates money) | P56, P04 |
| S41 | Proposal created 10-10, expires 10-17; confirm on 10-18 | `expired` returned; no GoalTransaction; the hold stopped counting at 10-17 | P54 |
| S42 | Manual Income created 10-10 | `received_at` 10-03 → manual/live (inclusive boundary); 10-02 → manual/historical | P51 |
| S43 | Income committed; after-response task lost; user inactive for 3 days | without the periodic dispatcher: AUTO runs at the next drain, against capacity at that time; with it: within the configured cadence (target ≈ 10 min) | P50 |

---

## 25. Test and Acceptance Strategy

All tests run only against the verified `valor_test` database. Expected values
are independent literals, never copies of production formulas.

| Area | Tests |
|---|---|
| Decimal | ROUND_DOWN allocations; remainders; percentage on `Income.amount` vs `base_amount` (P44); no float |
| Partitions | each partition ≥ 0; §7.2 formulas; legacy totals identical |
| Ownership | foreign Goal/Account/rule/proposal → 404; composite FKs reject cross-user rows |
| Currency | 422 for linked reservations; composite FK |
| Idempotency | goal keys (replay / conflict); executions; repeated confirm |
| Rollback | fault injection in AUTO and in confirmation |
| Outbox | Income + event atomic; Income rollback → no event; deferral by `not_before` |
| Replay / crash | S28–S30; lease expiry; attempts and backoff; `dead` |
| Periodic dispatcher | readiness checks for the chosen mechanism; cross-user batches; bounded queries (S43) |
| Concurrency | CT-01 S31 with two workers (repeat N times); CT-02 S31 + concurrent manual reservation; CT-03 two events of one user (FIFO, no duplicates); CT-04 confirmation vs dispatcher; CT-05 Income update vs processing of the same Income; CT-06 Expense/Transfer vs reservation; CT-07 Account delete / currency change vs reservation (409 or success, never 500); CT-08 reorder vs dispatcher; CT-09 rule edit vs dispatcher (no surviving old-version proposal); CT-10 two users in parallel; CT-11 manual reservation vs confirmation (S39); CT-12 planned Transfer create/post vs reservation |
| Priority | S25/S31 deterministic; reorder |
| Income CRUD | every row of §15.3 |
| Provenance | S23, S32, S33, S37, S42; reclassification; Income without a creation event |
| Proposals | expiry (S41), stale (S26/S35/S39), superseded, source_changed; holds (S38) incl. no self double counting |
| Capacity | future credits/debits (S7/S8); planned Transfers (S36) incl. no double subtraction after posting; date rollover; floor strict for rules, warning for manual (S18/S40) |
| Lifecycle | archived Goal (P10 regression), archived Account, delete or currency change with references (S13) |
| Budgets | transitions, deduplication, no duplicated limits |
| No double counting / Overview | Overview unchanged by reservations and holds; Goal totals not counted as assets |
| API compatibility | existing goal tests; additive fields |
| Database permissions | Data API REVOKE on every new table |
| Mobile | typecheck/lint; invalidation per §21; device acceptance (G6) |

Acceptance: gates G1–G7, full backend regression, CI green, documentation
matching the implemented state, the user performs the merge.

---

## 26. Decision Register P01–P48

| ID | Decision | Status |
|---|---|---|
| P01 | AUTO + CONFIRM, internal only | **APPROVED** |
| P02 | Model B + C | **APPROVED** |
| P03 | Per-transaction linking | **APPROVED** |
| P04 | 409 above capacity | **APPROVED** |
| P05 | Spending not blocked; overcommitted shown | **APPROVED** |
| P06 | Exact currency match | **APPROVED** |
| P07 | Explicit partition, each ≥ 0 | **APPROVED** |
| P08 | Reservation move = release + reserve; atomic move deferred | PROPOSED |
| P09 | Archived Account rules | **APPROVED** |
| P10 | Archived Goal rules | **APPROVED** |
| P11 | Completed Goal rules | **APPROVED** |
| P12 | Legacy history unchanged | **APPROVED** (also EST) |
| P13 | `effective_date` | **APPROVED** (refinement P58 PROPOSED) |
| P14 | Idempotency + transition | **APPROVED** (cutover timing P59 PROPOSED) |
| P15 | Terminology | **APPROVED** (`scheduled_shortfall` PROPOSED) |
| P16 | No external money movement | **APPROVED** |
| P17 | Expense → Goal attribution | PROPOSED (deferred) |
| P18 | Goals hardening first | **APPROVED** |
| P19 | Database integrity | **APPROVED** (no migration approved) |
| P20 | Open Banking access model | EXT |
| P21 | Provider / region | EXT |
| P22 | Wallets | EXT |
| P23 | Automatic import posting | UDR (VF-021) |
| P24 | Review of ambiguous imports | PROPOSED |
| P25 | Matching manual / receipt records | PROPOSED |
| P26 | Bank vs ledger balance | PROPOSED |
| P27 | Retention after disconnect | EXT |
| P28 | Tie-break between rules | PROPOSED (subordinate to P48) |
| P29 | Partial allocation, default false | **APPROVED** |
| P30 | v1 timezone = server date | PROPOSED |
| P31 | One source Account per rule | PROPOSED |
| P32 | AUTO blocked on incomplete data | PROPOSED |
| P33 | In-app notification defaults | PROPOSED |
| P34 | Reversal after a trigger change | **SUPERSEDED by P47** |
| P35 | Income eligibility | **APPROVED** |
| P36 | As-of capacity, conservative | **APPROVED** |
| P37 | Invalid rule → blocked | PROPOSED |
| P38 | Liabilities outside VF-020 | PROPOSED / EXT research |
| P39 | Card FX settlement | EXT |
| P40 | Spending limits = Budgets | EST |
| P41 | User timezone | PROPOSED (deferred) |
| P42 | v1 triggers: Income events + outbox + drain | PROPOSED |
| P43 | In-app channel | PROPOSED |
| P44 | Percentage basis = `Income.amount` | **APPROVED** |
| P45 | ROUND_DOWN | **APPROVED** |
| P46 | No retroactive execution | **APPROVED** |
| P47 | Corrections without reversal | **APPROVED** |
| P48 | Precedence | **APPROVED** |

---

## 27. Additional Decisions (P49+)

| ID | Decision | Content | Status |
|---|---|---|---|
| P49 | Planned Transfers in capacity | planned outgoing Transfers reduce `reservable`; planned incoming ignored; read model only; no ledger rows invented | **APPROVED** |
| P50 | Durable periodic dispatcher | required before unattended AUTO is presented as guaranteed; mechanism selected and verified in VF-020E; target cadence ≈ 10 min (5–15) | **APPROVED** (mechanism: technical verification) |
| P51 | Live manual Income window | N = 7 days, inclusive; older manual entries historical; no override in v1 | **APPROVED** |
| P52 | Per-user FIFO with head-of-line blocking | strict FIFO, bounded by `max_attempts`; to be finalized during dispatcher implementation and review | PROPOSED |
| P53 | Event retention | keep processed events as provenance until the user's data is deleted; VF-021 per legal review | PROPOSED / EXT |
| P54 | Proposal expiry | 7 days; lazy expiry | **APPROVED** |
| P55 | Soft capacity hold | holds reduce later rule capacity only; not reserved; never block real operations or manual reservations; full revalidation at confirmation | **APPROVED** |
| P56 | Floor for manual reservations | warning-only for manual, strict for rules; never overrides P04 or hard invariants | **APPROVED** |
| P57 | Lifecycle references | Goal deletion referenced by a rule → 409; rule deletion only without executions | PROPOSED |
| P58 | `effective_date` of linked rows | today only; tracked rows may be backdated | PROPOSED |
| P59 | Mandatory `client_request_id` for all clients | after all supported clients send it | PROPOSED |

---

## 28. Dependency-Ordered Roadmap

### VF-020 Smart Goals & Rules

| Stage | Scope | Depends on |
|---|---|---|
| VF-020A Contract | this document; product-requirements and roadmap updates | — (complete when merged) |
| VF-020B Goals Hardening | G1–G6; P10; P13 column; P14 keys; composite owner FK; `currency` copy | VF-020A; G3 (authorized read-only production check, migration approval) |
| VF-020C Goal Account Allocations | partitions; as-of model incl. P49; capacity; floor warning (P56); Account lifecycle pre-checks; API and minimal mobile surface | VF-020B; G3, G4 |
| VF-020D Goal Priorities | rank, reorder, L0 | VF-020C |
| VF-020E Rules Engine / Outbox / AUTO / CONFIRM | outbox; dispatcher drains (a)+(b); periodic dispatcher (c) with verified mechanism (P50); executions; holds (P55); expiry (P54); eligibility and provenance (P51); alerts; Inbox | VF-020D; G4, G5; P52 finalized |
| VF-020F Mobile & Acceptance | complete mobile UX, device acceptance, documentation, independent review | VF-020E; G6, G7 |

Each stage requires its own implementation authorization.

### VF-021 Financial Connections & Import (separate strategic stream)

1. Provider and legal discovery (P20–P22, P27, P38, P39) — may run in parallel with VF-020.
2. Consent and connection architecture.
3. Provider adapters (sandbox).
4. Import normalization.
5. Reconciliation.
6. Canonical integration (P23–P26) and events with provenance.
7. Analytics and mobile.
8. Security and acceptance.

No integration code before G2 and G5.

### Documentation maintenance

- `docs/architecture.md`, `docs/api-contract.md`, `docs/database-schema.md`,
  `README.md` and the module list in `CLAUDE.md` change with each implemented
  stage, not with this contract.
- `docs/roadmap.md` keeps "Goals are currently not connected to Accounts" until
  VF-020C ships.
- `docs/modules/account-transfers.md` ("Transfers must not interact with
  Goals") stays valid: VF-020 involves no Transfer ↔ Goal movement; P49 only
  reads planned Transfers. Any future money-movement model requires a dated
  amendment preserving the original decision.
- `docs/modules/financial-overview.md` needs no change.
- `docs/modules/financial-connections.md` is created when VF-021 discovery starts.

---

## 29. Implementation Readiness and Release Gates

| Stage | Ready to plan | Release gates |
|---|---|---|
| VF-020A | complete with this document | review of the documentation diff |
| VF-020B | yes; needs an authorized read-only production check | G3, G4, G5, G7 |
| VF-020C | yes, after VF-020B | G3, G4, G5, G6, G7 |
| VF-020D | yes, after VF-020C | G4, G7 |
| VF-020E | yes, after VF-020D; P52 finalized and P50 mechanism verified during the stage | G4, G5, G6, G7; **GA of unattended AUTO only with the periodic dispatcher in place** |
| VF-020F | after VF-020E | G6, G7 |
| VF-021 | discovery yes; code no | G2 and G5 first |

"Ready to plan" is not implementation authorization.

---

## 30. Contract Self-Review

| Check | Result |
|---|---|
| Financial invariants consistent across §6–§8, §24 | PASS |
| One capacity model; no double subtraction of future debits and planned Transfers; posted Transfers counted only via ledger | PASS (§8.1, S36) |
| Planned incoming Transfers and future credits never add capacity | PASS |
| Goal and Account money never double-counted | PASS (FIN-002, §7.2, §7.5) |
| Soft hold never presented as a reservation | PASS (§8.1, §11.3) |
| Own hold not counted at confirmation | PASS (§11.3, S38) |
| Manual floor override cannot bypass P04 | PASS (§10.6, S40) |
| Historical Income cannot become AUTO-eligible | PASS (E4/E5/E6, §16, S32/S37/S42) |
| P50 not hard-coded to one hosting provider | PASS (§12.5) |
| AUTO unattended guarantee depends on a real periodic dispatcher | PASS (§11.1, §12.5, §29) |
| CONFIRM not presented as guaranteed execution | PASS (§11.2) |
| Scheduled rules, push, wallets, bank connections not presented as implemented | PASS (§5, §10.1, §21, §22) |
| No invented Income status; Budgets not duplicated | PASS |
| No contradiction with AccountTransfer semantics (planned = no ledger rows) | PASS (§8, INV-08) |
| No contradiction with Financial Overview semantics | PASS (FIN-012) |
| No unapproved decision labeled APPROVED (P52, P53, P57–P59 PROPOSED; VF-021 UDR/EXT) | PASS |
| No migration, production access or implementation authorized | PASS |
| Requirements traceable to tests | PASS (§24 ↔ §25) |
| Implementation sequence valid | PASS |

---

## 31. Readiness Verdict

1. **Contract status:** APPROVED FOR DOCUMENTATION / IMPLEMENTATION PLANNING. No
   user decision blocks the VF-020 product semantics.
2. **Approved decisions:** P01–P07, P09–P16, P18, P19, P29, P35, P36, P44–P51,
   P54, P55, P56 (P34 superseded by P47).
3. **Remaining non-approved items:** PROPOSED technical refinements (P08, P17,
   P24–P26, P28, P30–P33, P37, P41–P43, P52, P53, P57–P59) finalized within
   their stages; P23 UDR for VF-021.
4. **External / legal gates:** P20, P21, P22, P27, P38 research, P39; G2 and G5
   for VF-021; finishing the secret rotation before storing banking tokens;
   technical verification of the periodic dispatcher mechanism (P50).
5. **Implementation authorization:** not granted by this document. Each stage,
   each migration and any production-data access requires explicit approval.
