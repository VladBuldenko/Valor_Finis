🗄 Database Schema — Valor Finis

This document describes the current PostgreSQL schema used by the Valor Finis backend.

The database layer is managed with SQLAlchemy and Alembic.

1. Overview

Main application tables:

categories
expenses
budgets
goals
accounts
receipts

Valor Finis does not currently store application users in a local users table.

User ownership is represented by:

user_id UUID

The authenticated user identity comes from the authentication layer.

2. Entity Relationships

erDiagram
    CATEGORIES ||--o{ EXPENSES : categorizes
    CATEGORIES ||--o{ BUDGETS : scopes
    EXPENSES ||--o{ RECEIPTS : linked_from

    CATEGORIES {
        UUID id PK
        UUID user_id
        VARCHAR name
        VARCHAR color
        VARCHAR icon
        BOOLEAN is_default
        TIMESTAMPTZ created_at
        TIMESTAMPTZ updated_at
    }

    EXPENSES {
        UUID id PK
        UUID user_id
        UUID category_id FK
        VARCHAR title
        NUMERIC amount
        VARCHAR currency
        DATE expense_date
        VARCHAR description
        VARCHAR source
        TIMESTAMPTZ created_at
        TIMESTAMPTZ updated_at
    }

    BUDGETS {
        UUID id PK
        UUID user_id
        UUID category_id FK
        VARCHAR name
        NUMERIC limit_amount
        VARCHAR currency
        VARCHAR period
        DATE start_date
        DATE end_date
        TIMESTAMPTZ created_at
        TIMESTAMPTZ updated_at
    }

    GOALS {
        UUID id PK
        UUID user_id
        VARCHAR name
        NUMERIC target_amount
        VARCHAR currency
        DATE target_date
        VARCHAR status
        TIMESTAMPTZ created_at
        TIMESTAMPTZ updated_at
    }

    RECEIPTS {
        UUID id PK
        UUID user_id
        UUID expense_id FK
        VARCHAR file_url
        VARCHAR storage_path
        VARCHAR status
        TEXT ocr_text
        VARCHAR merchant_detected
        NUMERIC total_amount_detected
        VARCHAR currency_detected
        DATE purchase_date_detected
        TIMESTAMPTZ created_at
        TIMESTAMPTZ updated_at
    }

    ACCOUNTS {
        UUID id PK
        UUID user_id
        VARCHAR name
        VARCHAR type
        VARCHAR currency
        VARCHAR status
        TIMESTAMPTZ created_at
        TIMESTAMPTZ updated_at
    }

3. Categories

Table:

categories

Purpose:

Stores user-owned expense and budget categories.

Column

Type

Nullable

Notes

id

UUID

no

Primary key

user_id

UUID

no

Resource owner

name

VARCHAR(80)

no

Category name

color

VARCHAR(20)

yes

Optional UI color

icon

VARCHAR(50)

yes

Optional UI icon

is_default

BOOLEAN

no

Default false

created_at

TIMESTAMPTZ

no

Server timestamp

updated_at

TIMESTAMPTZ

no

Updated automatically

Indexes

user_id

Case-insensitive unique index:

uq_categories_user_id_name_lower

Equivalent rule:

UNIQUE (user_id, lower(name))

This prevents the same user from creating categories such as:

Food
food
FOOD

as separate records.

4. Expenses

Table:

expenses

Purpose:

Stores user financial expense records.

Column

Type

Nullable

Notes

id

UUID

no

Primary key

user_id

UUID

no

Resource owner

category_id

UUID

yes

FK → categories.id

title

VARCHAR(120)

no

Expense name

amount

NUMERIC(12,2)

no

Expense amount

currency

VARCHAR(3)

no

Default EUR

expense_date

DATE

no

Date of expense

description

VARCHAR(500)

yes

Optional note

source

VARCHAR(30)

no

Default manual

base_amount

NUMERIC(12,2)

yes

VF-014B5C. amount converted to the user's base currency, using the
historical rate in effect on expense_date. Backend-derived only, never
client-supplied. Nullable only for a legacy foreign expense created
before VF-014B5C, whose snapshot has not been resolved yet - every
expense created after VF-014B5C always has this populated.

base_currency

VARCHAR(3)

yes

VF-014B5C. The base currency base_amount is denominated in (currently
always EUR - see VF-014B5B). Nullable together with base_amount.

fx_rate

NUMERIC(18,8)

yes

VF-014B5C. Units of base_currency per 1 unit of currency:
base_amount = amount * fx_rate. Nullable together with base_amount.

fx_rate_date

DATE

yes

VF-014B5C. The actual published rate date used - may differ from
expense_date (weekends/holidays, bounded lookback), never later than it.
Nullable together with base_amount.

fx_source

VARCHAR(30)

yes

VF-014B5C. "identity" (currency == base_currency, no external call),
"ecb" (European Central Bank reference rate), or "nbu" (National Bank of
Ukraine reference rate, used only for UAH - ECB does not publish it).
Nullable together with base_amount.

created_at

TIMESTAMPTZ

no

Server timestamp

updated_at

TIMESTAMPTZ

no

Updated automatically

Foreign Key

expenses.category_id
    ↓
categories.id

Delete behavior:

ON DELETE SET NULL

Deleting a category does not delete historical expenses.

Instead:

category_id = NULL

Constraints

ck_expenses_amount_positive

Rule:

amount > 0

ck_expenses_base_amount_positive (VF-014B5C)

Rule:

base_amount IS NULL OR base_amount > 0

ck_expenses_fx_rate_positive (VF-014B5C)

Rule:

fx_rate IS NULL OR fx_rate > 0

ck_expenses_fx_snapshot_all_or_none (VF-014B5C)

Rule:

The five FX snapshot columns (base_amount, base_currency, fx_rate,
fx_rate_date, fx_source) are either all NULL or all NOT NULL. A partial
snapshot (e.g. base_amount present but fx_rate_date missing) can never
be stored.

Indexes

user_id
category_id
expense_date

FX snapshot semantics (VF-014B5C):

amount/currency keep their original meaning - the transaction exactly as
it happened, never revalued using a later rate. base_amount/fx_rate are
resolved once, at expense create/update time, from an official source
(ECB or NBU) and persisted as a historical snapshot; analytics never
calls a provider and never recomputes these using today's rate. A
foreign-currency expense dated in the future is rejected outright (no
rate exists yet for it) rather than estimated. Existing rows already in
EUR before VF-014B5C were backfilled as identity snapshots
(fx_rate = 1, fx_source = 'identity'); existing rows in another currency
were left fully unresolved (all five columns NULL) rather than guessing
a rate or assuming EUR.

General spending analytics (monthly-summary, category-summary - VF-014B5D)
sum base_amount for every resolved Expense (base_amount is not null) and
treat currency correctly: a legacy row with no snapshot yet (base_amount
NULL) is excluded from monetary totals and separately counted, never
treated as zero-valued; a resolved row is only summed when its persisted
base_currency matches the user's current base_currency, otherwise it is
excluded and counted the same way an unresolved row is. Budget Status
(VF-014B3/B4) is unaffected by this - it still evaluates using
expense.amount against the Budget's own currency, not base_amount; see
"Budgets" below.

5. Budgets

Table:

budgets

Purpose:

Stores user spending limits.

Column

Type

Nullable

Notes

id

UUID

no

Primary key

user_id

UUID

no

Resource owner

category_id

UUID

yes

FK → categories.id

name

VARCHAR(120)

no

Budget name

limit_amount

NUMERIC(12,2)

no

Spending limit

currency

VARCHAR(3)

no

Default EUR

period

VARCHAR(20)

no

Default monthly

start_date

DATE

no

Budget start

end_date

DATE

yes

Optional budget end

created_at

TIMESTAMPTZ

no

Server timestamp

updated_at

TIMESTAMPTZ

no

Updated automatically

Foreign Key

budgets.category_id
    ↓
categories.id

Delete behavior:

ON DELETE RESTRICT

A category still referenced by a budget cannot be deleted (changed from
SET NULL in VF-014B2 - SET NULL previously allowed a category-scoped
budget to silently become an all-expenses budget when its category was
deleted). The service layer also rejects this with a 409
(CategoryInUseByBudgetError) before the database constraint would fire;
hiding the category (is_visible = false) is the supported alternative.

Constraints

Positive budget limit:

ck_budgets_limit_amount_positive

limit_amount > 0

Valid period:

ck_budgets_period_valid

period IN ('weekly', 'monthly', 'yearly')

Duplicate protection:

uq_budgets_user_id_name_period_start_date

Equivalent rule:

UNIQUE (
    user_id,
    name,
    period,
    start_date
)

Indexes

user_id
category_id
start_date

5.1 Budget Versions

Table:

budget_versions

Purpose:

Append-only history of a budget's limit_amount and category_id over
time (VF-014B2). budgets.limit_amount/category_id changed meaning in
VF-014 from "the whole budget" to "the current period's recurring
value" - they are mutable in place, so editing them mid-lifecycle would
otherwise silently rewrite the meaning of already-completed periods.
Period windows themselves are not persisted here; they stay dynamically
resolved by budget_period.py (VF-014B1).

Column

Type

Nullable

Notes

id

UUID

no

Primary key

budget_id

UUID

no

FK → budgets.id, ON DELETE CASCADE

user_id

UUID

no

Resource owner (denormalized, no FK, matching every other table)

effective_from

DATE

no

First period start this version applies to

effective_until

DATE

yes

NULL = open-ended (every VF-014 write is open-ended)

limit_amount

NUMERIC(12,2)

no

The limit in effect from effective_from

category_id

UUID

yes

FK → categories.id, ON DELETE RESTRICT. The scope in effect from
effective_from

change_reason

VARCHAR(30)

no

One of: initial, user_edit, category_change

created_at

TIMESTAMPTZ

no

Tie-break when two versions share effective_from

Constraints

ck_budget_versions_limit_amount_positive: limit_amount > 0
ck_budget_versions_effective_range: effective_until IS NULL OR effective_until >= effective_from
ck_budget_versions_change_reason_valid: change_reason IN ('initial', 'user_edit', 'category_change')

Indexes

budget_id
user_id
(budget_id, effective_from) - the lookup path for resolving which
version applied to a given period

Resolution rule: for a period [period_start, period_end], the version
with the greatest effective_from <= period_start where
effective_until IS NULL OR effective_until >= period_end applies,
tie-broken by created_at DESC.

6. Goals

Table:

goals

Purpose:

Stores user financial goals and progress.

Column

Type

Nullable

Notes

id

UUID

no

Primary key

user_id

UUID

no

Resource owner

name

VARCHAR(150)

no

Goal name

target_amount

NUMERIC(12,2)

no

Target amount

currency

VARCHAR(3)

no

Default EUR

target_date

DATE

yes

Optional target date

status

VARCHAR(30)

no

Default active

created_at

TIMESTAMPTZ

no

Server timestamp

updated_at

TIMESTAMPTZ

no

Updated automatically

Constraints

ck_goals_target_amount_positive

target_amount > 0

Indexes

user_id
target_date

The Goal's balance is not stored on this table at all (removed in
VF-016G): it is computed at read time from goal_transactions (see 6.1
below), never accepted on POST/PATCH /api/v1/goals(/{goal_id}) request
bodies, and returned to clients as the read-only GoalResponse.current_amount
field (see api-contract.md). There is no "balance <= target_amount" rule:
overfunding above target_amount is a valid, allowed state.

Prior to VF-016G, goals.current_amount existed as transitional compatibility
storage: every transaction write synchronized it, but no read path trusted
it. That column and its ck_goals_current_amount_non_negative constraint
were dropped by migration 220b12b15adc; goal_transactions is now the only
persisted source of a Goal's balance.

Currency immutability (VF-016E): currency is editable only while a Goal
has no transaction history - once any GoalTransaction row exists for a
Goal (any type, any resulting balance), an actual currency change is
rejected at the application level (see 6.1 below). This is enforced in
goal_service.update_goal, not by a PostgreSQL constraint: there is no
CHECK or trigger tying goals.currency to goal_transactions' existence.

Safe deletion (VF-016E): a Goal with any transaction history cannot be
hard-deleted through the application (goal_service.delete_goal rejects it
before attempting the delete). A Goal with no transaction history deletes
normally. This is an application-level control, not a database constraint
- see 6.1 below for the FK that backs it as defense-in-depth.

6.1 Goal Transactions

Table:

goal_transactions

Purpose:

Append-only ledger of balance-affecting events for a Goal: opening_balance
(migration-created historical balance), contribution, and withdrawal.
Introduced in VF-016B; VF-016C wired up the write path (POST
/api/v1/goals/{goal_id}/transactions inserts a contribution/withdrawal
row). VF-016D wired up the read path: this table has been authoritative
for both writes and reads since then. Every public Goal balance -
POST/GET/PATCH /api/v1/goals and GET /api/v1/analytics/goal-progress -
is computed from this table at read time (opening_balance + contribution -
withdrawal). As of VF-016G, this is the ONLY persisted source of a Goal's
balance: the goals table has no balance column at all (see 6 above), so
there is no legacy storage left to drift out of sync or to remove in a
later migration. See goal_service._build_goal_response and
goal_transaction_repository.get_ledger_balances_for_user.

Concurrency: every balance-changing write locks the owned Goal row with
SELECT ... FOR UPDATE before calculating the ledger balance, in the same
database transaction as the ledger insert. This serializes concurrent
writes against the same Goal at the PostgreSQL level - two simultaneous
withdrawal requests can never both validate against the same stale
balance, so the balance can never go negative even under a race. The lock
serializes the write regardless of whether anything on the Goal row
itself changes (as of VF-016G, nothing does). See
goal_repository.get_goal_by_id_for_update and
goal_service.create_goal_transaction.

VF-016E extends this same row-lock discipline to currency changes and
deletion: goal_service.update_goal and goal_service.delete_goal both
acquire the owned Goal row lock (get_goal_by_id_for_update) *before*
checking goal_transaction_repository.has_transactions_for_goal, in the
same database transaction as the check and the resulting write. This
serializes a currency change or a delete against the Goal's first
transaction - whichever operation's lock is acquired (and commits) first
determines the outcome the other one observes; a currency change or delete
can never see a stale "no history yet" state while a concurrent first
transaction is also in flight. has_transactions_for_goal is a plain
existence check (first matching row only) - it never uses a ledger balance
calculation as a proxy for "has history", since a Goal can have real
transaction history and a 0.00 balance at the same time (e.g. a
contribution immediately followed by an equal withdrawal).

Column

Type

Nullable

Notes

id

UUID

no

Primary key

goal_id

UUID

no

FK → goals.id, ON DELETE RESTRICT (not CASCADE - a Goal's financial
history must not silently disappear if the Goal row is deleted). As of
VF-016E, goal_service.delete_goal already rejects a history-bearing Goal
at the application level before attempting the delete, so this FK is now
defense-in-depth (it should never actually fire in normal operation), not
the primary mechanism - the application never lets a raw IntegrityError
from this constraint reach a client.

user_id

UUID

no

Resource owner (denormalized, no FK, matching every other table)

type

VARCHAR(20)

no

One of: opening_balance, contribution, withdrawal. opening_balance is
reserved for migration/system backfill; public APIs must never let a
client create one.

amount

NUMERIC(12,2)

no

Always positive; direction is carried by type, not sign

description

VARCHAR(255)

yes

Optional free-text note

created_at

TIMESTAMPTZ

no

For backfilled opening_balance rows, set to the source Goal's own
created_at, not migration execution time

Constraints

ck_goal_transactions_amount_positive: amount > 0
ck_goal_transactions_type_valid: type IN ('opening_balance', 'contribution', 'withdrawal')

Indexes

user_id
(goal_id, created_at) - per-goal transaction history, ordered access, and
future balance aggregation

Immutability: rows are append-only. No UPDATE/DELETE path exists or is
planned; corrections are made with compensating entries, never edits.

Opening-balance backfill: every pre-existing Goal with current_amount > 0
received exactly one opening_balance row (amount = that current_amount,
created_at = the Goal's own created_at) when this table was introduced.
Goals with current_amount == 0 received no row - no money is manufactured.
See alembic/versions/e90a257f987b_add_goal_transactions_and_backfill.py.

7. Accounts

Table:

accounts

Purpose:

Stores real-world places a user's money is held: a checking account, a
savings account, or cash. VF-017B scope only - credit cards, debt/
liability accounts, and investment accounts are explicitly out of scope.
An Account is distinct from a Budget (a spending limit, never a cash
source - see 12. Application-Enforced Invariants) and from a Goal (an
aspirational target, not yet connected to any cash source in this
slice).

Column

Type

Nullable

Notes

id

UUID

no

Primary key

user_id

UUID

no

Resource owner

name

VARCHAR(120)

no

Not unique - a user may have multiple similarly named accounts

type

VARCHAR(20)

no

checking, savings, or cash

currency

VARCHAR(3)

no

Default EUR

status

VARCHAR(20)

no

active or archived, default active

created_at

TIMESTAMPTZ

no

Server timestamp

updated_at

TIMESTAMPTZ

no

Updated automatically

Constraints

ck_accounts_type_valid

type IN ('checking','savings','cash')

ck_accounts_status_valid

status IN ('active','archived')

Indexes

user_id

The Account's balance is not stored on this table at all: it is
computed at read time from account_transactions (see 7.1 below), never
accepted on POST/PATCH /api/v1/accounts(/{account_id}) request bodies,
and returned to clients as the read-only AccountResponse.current_balance
field (see api-contract.md). Unlike Goal, there is no non-negativity
constraint anywhere in this domain: an Account is a descriptive
financial record, not a payment-authorization system, so its
ledger-derived balance may be negative.

Currency immutability: currency is editable only while an Account has no
transaction history - once any AccountTransaction row exists, an actual
currency change is rejected at the application level (see 7.1 below).
This mirrors Goal's currency-immutability rule exactly and for the same
reason: AccountTransaction rows do not store their own currency.

Safe deletion: an Account with any transaction history cannot be
hard-deleted through the application (account_service.delete_account
rejects it before attempting the delete). An Account with no transaction
history deletes normally. This is an application-level control, not a
database constraint - see 7.1 below for the FK that backs it as
defense-in-depth.

Archiving: PATCH status="archived" remains possible regardless of
transaction history. An archived Account's balance and full history stay
fully readable, but a new manual adjustment transaction into it is
rejected at the application level (see 7.1 below). Reactivating (PATCH
status="active") allows new adjustments again.

7.1 Account Transactions

Table:

account_transactions

Purpose:

Ledger of balance-affecting events for an Account. VF-017B ships exactly
two kinds: opening_balance (recorded once, at account creation, to
represent a real pre-existing balance) and adjustment (a direct manual
correction/reconciliation entry). income, expense, and transfer kinds are
intentionally deferred to a later slice, not part of this migration.

This table is the only persisted source of an Account's balance: the
accounts table has no balance column at all (see 7 above). Every public
Account balance - POST/GET/PATCH /api/v1/accounts and GET
/api/v1/accounts/{account_id}/transactions - is computed from this table
at read time (SUM of credit amounts minus debit amounts). See
account_service._build_account_response and
account_transaction_repository.get_ledger_balances_for_user.

Column

Type

Nullable

Notes

id

UUID

no

Primary key

account_id

UUID

no

FK accounts.id ON DELETE RESTRICT

user_id

UUID

no

Denormalized owner, no FK

kind

VARCHAR(20)

no

opening_balance or adjustment (VF-017B)

direction

VARCHAR(10)

no

credit or debit - kept separate from kind (unlike GoalTransaction, where
type implies direction) so a future income/expense/transfer kind can
reuse the same direction concept without restructuring this column

amount

NUMERIC(12,2)

no

Always positive; direction carries the sign

transaction_date

DATE

no

The date this event actually happened

description

VARCHAR(500)

yes

Optional free-text note

created_at

TIMESTAMPTZ

no

Server timestamp

Constraints

ck_account_transactions_amount_positive

amount > 0

ck_account_transactions_kind_valid

kind IN ('opening_balance','adjustment')

ck_account_transactions_direction_valid

direction IN ('credit','debit')

uq_account_transactions_one_opening_balance_per_account

Partial unique index on account_id WHERE kind = 'opening_balance' -
at most one opening_balance row per account, enforced at the database
level

Indexes

user_id
(account_id, transaction_date) - per-account transaction history,
ordered access, and future balance aggregation

Immutability: opening_balance and adjustment rows are append-only - there
is no UPDATE/DELETE path or endpoint for either. Corrections are made
with compensating adjustment entries, never edits - identical philosophy
to GoalTransaction. A future slice that links income/expense source rows
to this table will introduce a different, explicitly-scoped correction
model for those specific rows only (kept in sync with their mutable
source row) - not part of this migration; opening_balance and adjustment
rows stay immutable regardless of that future change.

Concurrency: every write that can race against a lifecycle change (a new
transaction, a currency change, a delete, an archive) locks the owned
Account row with SELECT ... FOR UPDATE first, in the same database
transaction as the write. This mirrors Goal's row-lock discipline
exactly, but the lock here is never used to validate a balance - an
Account's ledger-derived balance has no floor, so two simultaneous debit
adjustments can both succeed without either being rejected; the lock only
serializes the lifecycle-state races (currency-change-vs-first-transaction,
delete-vs-first-transaction, archive-vs-new-transaction), never a
balance check. See account_repository.get_account_by_id_for_update and
account_service.py.

Opening-balance creation: unlike goal_transactions' migration-time
backfill (a one-time historical event), account_transactions' single
opening_balance row per account is created at normal application runtime,
atomically with the Account row itself, whenever a client provides a
non-zero opening_balance on POST /api/v1/accounts. No migration backfill
exists for this table - accounts is a brand-new table with no
pre-existing balance to migrate from.

8. Receipts

Table:

receipts

Purpose:

Stores receipt metadata, OCR results, processing state, and an optional link to the expense created from the receipt.

Column

Type

Nullable

Notes

id

UUID

no

Primary key

user_id

UUID

no

Resource owner

expense_id

UUID

yes

FK → expenses.id

file_url

VARCHAR(1000)

yes

Optional external file URL

storage_path

VARCHAR(1000)

yes

Optional internal file path

status

VARCHAR(30)

no

Default uploaded

ocr_text

TEXT

yes

Raw OCR result

merchant_detected

VARCHAR(120)

yes

OCR merchant

total_amount_detected

NUMERIC(12,2)

yes

OCR amount

currency_detected

VARCHAR(3)

yes

OCR currency

purchase_date_detected

DATE

yes

OCR purchase date

created_at

TIMESTAMPTZ

no

Server timestamp

updated_at

TIMESTAMPTZ

no

Updated automatically

Foreign Key

receipts.expense_id
    ↓
expenses.id

Delete behavior:

ON DELETE SET NULL

Deleting an expense preserves the receipt record.

Status Constraint

ck_receipts_status_valid

Allowed values:

uploaded
processing
processed
confirmed
failed

OCR Amount Constraint

ck_receipts_total_amount_detected_positive

Rule:

total_amount_detected IS NULL
OR
total_amount_detected > 0

Indexes

user_id
expense_id
status

The requirement that a receipt must have either:

file_url

or:

storage_path

is currently enforced by the application schema rather than by a PostgreSQL constraint.

8.1 User Financial Settings

Table:

user_financial_settings

Purpose:

Stores the single authoritative financial-domain setting owned by each
user: their base currency (VF-014B5B). One row per user. user_id is the
primary key directly - this is an inherent one-to-one, user-owned row, so
no surrogate id column exists.

Column

Type

Nullable

Notes

user_id

UUID

no

Primary key. No FK - matches the denormalized, Supabase-owned-identity
pattern used by every other table.

base_currency

VARCHAR(3)

no

Default EUR (both application-level and DB server_default)

created_at

TIMESTAMPTZ

no

Server timestamp

updated_at

TIMESTAMPTZ

no

Updated automatically

Indexes

None beyond the primary key - all access is by user_id.

Lazy bootstrap:

There is no local users table and no signup hook in this backend
(Supabase owns identity), so this row does not exist until a user's first
financial-settings access. `financial_settings_repository.get_or_create_
financial_settings` creates it on demand using a target-less
`INSERT ... ON CONFLICT DO NOTHING` followed by a `SELECT`, the same
race-safe first-use pattern already established for default categories
(`categories/repository.py:ensure_default_categories`) - two concurrent
first-access requests cannot raise a duplicate-key error.

Mutation surface:

None yet. VF-014B5B does not expose any public API to read or change
base_currency. It is an internal domain seam only, consumed directly by
later VF-014B5 slices (Expense FX conversion). Base currency is therefore
effectively immutable for now - changing it after financial data exists
is a deliberately deferred, unresolved product decision (see the VF-014B5
architecture discovery report), not something this table's shape commits
to either way.

9. Ownership Model

All main entities contain:

user_id UUID NOT NULL

The current schema intentionally does not use:

FOREIGN KEY user_id → users.id

because authentication identity is handled outside these domain tables.

Application queries must therefore enforce ownership explicitly:

WHERE id = :resource_id
AND user_id = :authenticated_user_id

This rule is part of the security model.

10. Relationship Summary

categories
   │
   ├──< expenses.category_id
   │
   └──< budgets.category_id

budgets
   │
   └──< budget_versions.budget_id

goals
   │
   └──< goal_transactions.goal_id

accounts
   │
   └──< account_transactions.account_id

expenses
   │
   └──< receipts.expense_id

Delete behavior:

Category deleted
    ↓
Expense.category_id = NULL
Budget.category_id  = rejected if any budget references the category
                       (ON DELETE RESTRICT, changed from SET NULL in
                       VF-014B2)

Budget deleted
    ↓
BudgetVersion rows for that budget = deleted (ON DELETE CASCADE)

Goal deleted
    ↓
Rejected if any goal_transactions reference the goal (ON DELETE RESTRICT,
VF-016B)

Account deleted
    ↓
Rejected if any account_transactions reference the account (ON DELETE
RESTRICT, VF-017B)

Expense deleted
    ↓
Receipt.expense_id = NULL

No dependent financial records are automatically deleted through these relationships, except a budget's own version history, which is deleted with it. A Goal or an Account with transaction history cannot be deleted at all.

11. Database-Enforced Invariants

PostgreSQL currently protects these important rules directly:

Expense.amount > 0

Budget.limit_amount > 0

Goal.target_amount > 0

Receipt.status is valid
Receipt.total_amount_detected > 0 when present

Category names are unique per user case-insensitively

Budget user/name/period/start_date combinations are unique

Budget.period is one of weekly/monthly/yearly

BudgetVersion.limit_amount > 0
BudgetVersion.effective_until >= effective_from when present
BudgetVersion.change_reason is valid

GoalTransaction.amount > 0
GoalTransaction.type is valid

Account.type is one of checking/savings/cash
Account.status is one of active/archived

AccountTransaction.amount > 0
AccountTransaction.kind is valid
AccountTransaction.direction is one of credit/debit
At most one AccountTransaction with kind = 'opening_balance' per account
(partial unique index)

A category still referenced by a budget cannot be deleted (ON DELETE RESTRICT)

A goal still referenced by a goal_transactions row cannot be deleted (ON DELETE RESTRICT)

An account still referenced by an account_transactions row cannot be deleted (ON DELETE RESTRICT)

These constraints protect data even if an application-layer validation path is bypassed.

12. Application-Enforced Invariants

Some rules require business context and are currently enforced by Pydantic/service logic rather than directly by PostgreSQL.

Examples:

A GoalTransaction withdrawal cannot exceed the Goal's current
ledger-derived balance (VF-016C) - that balance is allowed to exceed
Goal.target_amount (overfunding), so there is no amount relationship
enforced between the two at all. The Goal row itself has no balance
column to relate target_amount to in the first place (VF-016G).

Goal.currency cannot actually change once the Goal has any transaction
history (VF-016E) - resending the same normalized currency is allowed;
this is checked under the same SELECT ... FOR UPDATE lock used for
balance-changing writes, so it cannot race against the Goal's first
transaction.

A Goal with any transaction history cannot be hard-deleted (VF-016E) -
checked under the same row lock as above; the underlying FK RESTRICT
remains only as defense-in-depth.

Account.currency cannot actually change once the Account has any
transaction history (VF-017B) - resending the same normalized currency is
allowed; this is checked under the same SELECT ... FOR UPDATE lock used
for transaction-creating writes, so it cannot race against the Account's
first transaction. Unlike GoalTransaction withdrawals, there is
deliberately NO equivalent "insufficient funds" rule for AccountTransaction
debits anywhere in this domain - an Account's ledger-derived balance may
be negative, zero, or positive with no floor.

An Account with any transaction history cannot be hard-deleted (VF-017B) -
checked under the same row lock as above; the underlying FK RESTRICT
remains only as defense-in-depth.

A new AccountTransaction cannot be created against an archived Account
(VF-017B) - checked under the same row lock, so it cannot race against a
concurrent archive.

Budget.end_date >= Budget.start_date

Budget.end_date cannot be set to a date before today (VF-014B2)

Budget.currency cannot be changed

Budget.period and Budget.start_date cannot be changed once the budget's
first period has completed (a short typo-fix window remains open before then)

Receipt has file_url or storage_path

Receipt state transitions are valid

Receipt confirmation is allowed only from processed state

Default categories cannot be modified/deleted

Referenced category belongs to authenticated user

Referenced expense belongs to authenticated user

This separation is intentional:

Database
    ↓
protects structural/data invariants

Application
    ↓
protects contextual business rules

13. Transactions

The most important multi-entity transaction is receipt confirmation.

BEGIN
   │
   ├── create Expense
   │
   ├── update Receipt.expense_id
   │
   └── update Receipt.status = confirmed
   │
COMMIT

If any operation fails:

ROLLBACK

The database must never contain a partially confirmed receipt workflow.

14. Migration Strategy

Schema changes are managed only through Alembic.

Migration flow:

SQLAlchemy model change
        ↓
Alembic migration
        ↓
review migration
        ↓
alembic upgrade head
        ↓
PostgreSQL

Important rules:

never modify production schema manually;

every schema change requires a versioned migration;

migrations must work from an empty database;

migration order must preserve foreign-key dependencies;

CI applies all migrations before running integration tests.

Current schema can be reconstructed from an empty PostgreSQL database through the Alembic migration chain.

15. Design Principles

Database design follows these rules:

UUIDs are used for public resource identifiers.

Financial values use NUMERIC, not floating-point types.

Foreign keys preserve referential integrity.

Historical records are preserved with SET NULL where appropriate.

Important invariants are enforced in PostgreSQL when practical.

Business-context rules stay in the application layer.

User ownership is always enforced by authenticated user_id.

Schema evolution is handled exclusively through Alembic.

Indexes should support real query patterns.

Data integrity takes priority over convenience.

16. Current Schema

PostgreSQL
│
├── categories
│   ├── PK id
│   └── UNIQUE user_id + lower(name)
│
├── expenses
│   ├── PK id
│   └── FK category_id → categories
│
├── budgets
│   ├── PK id
│   ├── FK category_id → categories (ON DELETE RESTRICT)
│   └── UNIQUE user_id + name + period + start_date
│
├── budget_versions
│   ├── PK id
│   ├── FK budget_id → budgets (ON DELETE CASCADE)
│   └── FK category_id → categories (ON DELETE RESTRICT)
│
├── goals
│   └── PK id
│
├── accounts
│   └── PK id
│
├── account_transactions
│   ├── PK id
│   └── FK account_id → accounts (ON DELETE RESTRICT)
│
├── receipts
│   ├── PK id
│   └── FK expense_id → expenses
│
└── user_financial_settings
    └── PK user_id

This document should be updated whenever the persisted schema, constraints, relationships, or migration strategy changes.