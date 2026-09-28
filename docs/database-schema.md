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
account_transfers
income
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

    INCOME {
        UUID id PK
        UUID user_id
        NUMERIC amount
        VARCHAR currency
        DATE received_at
        VARCHAR source
        VARCHAR description
        TIMESTAMPTZ created_at
        TIMESTAMPTZ updated_at
    }

    ACCOUNT_TRANSFERS {
        UUID id PK
        UUID user_id
        UUID client_request_id
        UUID source_account_id FK
        UUID destination_account_id FK
        NUMERIC amount
        VARCHAR currency
        VARCHAR status
        DATE planned_date
        DATE effective_date
        VARCHAR description
        TIMESTAMPTZ posted_at
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

This table still has no account_id column, even though an Expense can
now be linked to an Account (VF-017E). Expense is the canonical record;
its link to an Account is represented entirely by an AccountTransaction
row (kind="expense") in account_transactions whose expense_id points
back here - see 7.1 Account Transactions above, mirroring Income's own
VF-017D design exactly. Storing account_id on both sides would create
two independently-writable copies of the same fact; the public API's
account_id (see docs/api-contract.md) is derived from that projection at
read time, never persisted on expenses itself.

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

uq_expenses_id_user_id (VF-017E)

Rule:

UNIQUE(id, user_id) - composite-unique FK target, not a business-rule
constraint by itself. Lets account_transactions carry a
(expense_id, user_id) -> expenses(id, user_id) foreign key, so a
cross-user Expense<->Account link is impossible to construct at the
database level, not only the service level (see 7.1 above).

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

Account linkage (VF-017E): allowed only when Expense.currency exactly
matches Account.currency, after normalization - no FX conversion happens
between Expense and Account, and the ledger always uses Expense.amount,
never base_amount (base_amount is base-currency analytics truth, not the
amount that actually left an Account). Linking is rejected (409, reusing
the existing AccountArchivedError) when it would add NEW activity to an
archived Account - creating, attaching, or moving INTO one - but
amount/expense_date corrections to an Expense already linked to an
Account archived afterward, and detaching/deleting/moving OUT of an
archived Account, remain allowed; see 7.1 above for the exact locking
order (Expense locked first, then the required Account row(s)) and
docs/api-contract.md for the full PATCH semantics. Pure linkage
operations (attach/detach/move/account_id-only PATCH) never call the FX
provider and never touch the FX snapshot - including for a legacy
unresolved Expense, whose snapshot stays fully NULL through any number
of linkage changes; only a genuine monetary field change (amount,
currency, or expense_date - the same pre-existing rule described above,
completely independent of account_id) can ever trigger FX resolution.

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
source - see 13. Application-Enforced Invariants) and from a Goal (an
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

uq_accounts_id_user_id

UNIQUE(id, user_id) (VF-017D) - composite FK target for
account_transactions

uq_accounts_id_user_id_currency

UNIQUE(id, user_id, currency) (VF-018B) - composite FK target for
account_transfers' currency-bearing source/destination foreign keys (see
7.2 below)

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
Independently, an Account referenced by any account_transfers row
(planned or posted) cannot change currency at the database level: the
transfer's composite foreign keys include currency (VF-018B, see 7.2
below). A planned transfer has no ledger rows, so the application-level
history check above does not see it; the controlled 409 for Accounts
referenced by planned transfers is part of VF-018C and is not implemented
yet - no public endpoint can create a transfer before VF-018C.

Safe deletion: an Account with any transaction history cannot be
hard-deleted through the application (account_service.delete_account
rejects it before attempting the delete). An Account with no transaction
history deletes normally. This is an application-level control, not a
database constraint - see 7.1 below for the FK that backs it as
defense-in-depth. An Account referenced by any account_transfers row is
also protected by that table's ON DELETE RESTRICT foreign keys (VF-018B,
see 7.2 below).

Archiving: PATCH status="archived" remains possible regardless of
transaction history. An archived Account's balance and full history stay
fully readable, but a new manual adjustment transaction into it is
rejected at the application level (see 7.1 below). Reactivating (PATCH
status="active") allows new adjustments again.

7.1 Account Transactions

Table:

account_transactions

Purpose:

Ledger of balance-affecting events for an Account. VF-017B shipped two
direct kinds: opening_balance (recorded once, at account creation, to
represent a real pre-existing balance) and adjustment (a direct manual
correction/reconciliation entry). VF-017D added a third, source-backed
kind: income - a synchronized projection of an Income row (see the
income_id column below and 8. Income above). VF-017E adds a fourth,
source-backed kind: expense - a synchronized projection of an Expense
row (see the expense_id column below and 4. Expenses above), symmetric
to income but always a debit. VF-018B adds a fifth, source-backed kind:
transfer - one of the two projections of a posted AccountTransfer (see
the transfer_id column below and 7.2 Account Transfers): a debit on the
source Account or a credit on the destination Account. As of VF-018B the
transfer schema and repository foundation exist, but no public endpoint
creates transfers yet (VF-018C/D).

This table is the only persisted source of an Account's balance: the
accounts table has no balance column at all (see 7 above). Every public
current_balance value - returned by POST/GET/PATCH /api/v1/accounts - is
computed from this table at read time (SUM of credit amounts minus debit
amounts). See account_service._build_account_response and
account_transaction_repository.get_ledger_balances_for_user.
GET /api/v1/accounts/{account_id}/transactions reads rows from this same
table too, but returns transaction history, not an AccountResponse - it
does not itself return current_balance.

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

opening_balance, adjustment (VF-017B), income (VF-017D), expense
(VF-017E), or transfer (VF-018B)

direction

VARCHAR(10)

no

credit or debit - kept separate from kind (unlike GoalTransaction, where
type implies direction) so income and expense could reuse the same
direction concept without restructuring this column. Every income-kind
row is a credit and every expense-kind row is a debit, both enforced by
ck_account_transactions_source_linkage_valid below. A transfer-kind row
may be either: the source-side projection is the debit and the
destination-side projection the credit.

amount

NUMERIC(12,2)

no

Always positive; direction carries the sign. For an income-backed row,
always synchronized to equal the source Income's own amount; for an
expense-backed row, always synchronized to equal the source Expense's
own amount (never Expense.base_amount).

transaction_date

DATE

no

The date this event actually happened. For an income-backed row, always
synchronized to equal the source Income's received_at; for an
expense-backed row, always synchronized to equal the source Expense's
own expense_date.

description

VARCHAR(500)

yes

Optional free-text note. Always NULL for an income-backed or
expense-backed row - the source record's own description/title/source
remain the single canonical copy of that text (see 4. Expenses / 8.
Income); the ledger row identifies its source via income_id/expense_id
instead of duplicating mutable text that would need its own
synchronization.

income_id

UUID

yes

If this row is an Income projection, the source Income's id (VF-017D).
NULL for direct opening_balance/adjustment rows and for expense-backed
rows.

expense_id

UUID

yes

If this row is an Expense projection, the source Expense's id
(VF-017E). NULL for direct opening_balance/adjustment rows and for
income-backed rows.

transfer_id

UUID

yes

If this row is an AccountTransfer projection, the source transfer's id
(VF-018B). NULL for every other kind. For a transfer-kind row, amount
always equals the transfer's amount, transaction_date its
effective_date, and description is NULL (the transfer's own description
is the single canonical copy).

created_at

TIMESTAMPTZ

no

Server timestamp. For an income- or expense-backed row, this is the
projection's own creation time and is never reset when the row is later
synchronized (an amount/date sync, or a move between Accounts, updates
the existing row in place).

Constraints

ck_account_transactions_amount_positive

amount > 0

ck_account_transactions_kind_valid

kind IN ('opening_balance','adjustment','income','expense','transfer')

ck_account_transactions_direction_valid

direction IN ('credit','debit')

ck_account_transactions_source_linkage_valid

(VF-017E, replaces VF-017D's income-only ck_account_transactions_income_linkage_valid;
VF-018B adds the transfer branch)

(kind = 'income' AND income_id IS NOT NULL AND expense_id IS NULL AND
transfer_id IS NULL AND direction = 'credit') OR (kind = 'expense' AND
expense_id IS NOT NULL AND income_id IS NULL AND transfer_id IS NULL AND
direction = 'debit') OR (kind = 'transfer' AND transfer_id IS NOT NULL
AND income_id IS NULL AND expense_id IS NULL) OR (kind IN
('opening_balance','adjustment') AND income_id IS NULL AND expense_id IS
NULL AND transfer_id IS NULL) - the single constraint that makes income,
expense, transfer, and direct rows mutually exclusive: since kind is a
single scalar value, a row can satisfy at most one of the four branches,
so "more than one source id populated" and every other invalid
combination is structurally impossible. The transfer branch leaves
direction free, since each posted transfer has one debit and one credit
projection.

uq_account_transactions_one_opening_balance_per_account

Partial unique index on account_id WHERE kind = 'opening_balance' -
at most one opening_balance row per account, enforced at the database
level

uq_account_transactions_income_id

UNIQUE(income_id) (VF-017D) - at most one AccountTransaction projection
per Income, enforced at the database level. NULLs never collide, so
every direct row is unaffected.

uq_account_transactions_expense_id

UNIQUE(expense_id) (VF-017E) - at most one AccountTransaction projection
per Expense, enforced at the database level. NULLs never collide, so
every direct row and every income-kind row is unaffected.

uq_account_transactions_transfer_id_direction

UNIQUE(transfer_id, direction) (VF-018B) - at most one debit and at most
one credit projection per transfer. NULL transfer_id values never
collide, so every non-transfer row is unaffected. This does NOT by itself
guarantee that a posted transfer has exactly two projections (nor that a
planned one has none) - see 7.2 below.

fk_account_transactions_account_id_user_id

FOREIGN KEY (account_id, user_id) REFERENCES accounts(id, user_id) ON
DELETE RESTRICT (VF-017D). Composite ownership FK: account_id must
belong to the SAME user_id as this row, at the database level, not only
the service level. Kept alongside the pre-existing plain
account_id -> accounts.id FK (defense-in-depth), not replacing it.

fk_account_transactions_income_id_user_id

FOREIGN KEY (income_id, user_id) REFERENCES income(id, user_id) ON
DELETE CASCADE (VF-017D). Composite ownership FK: income_id must belong
to the SAME user_id as this row - this is what makes a cross-user
Income<->Account link impossible at the database level, not only the
service level. ON DELETE CASCADE is deliberate and is the opposite
choice from account_id's RESTRICT: RESTRICT protects a record's own
deletion when it has dependent history (accounts, goals); here the
relationship is inverted - Income is canonical and owns its projection,
so the projection must vanish with its source rather than block it.

fk_account_transactions_expense_id_user_id

FOREIGN KEY (expense_id, user_id) REFERENCES expenses(id, user_id) ON
DELETE CASCADE (VF-017E). Composite ownership FK: expense_id must belong
to the SAME user_id as this row - this is what makes a cross-user
Expense<->Account link impossible at the database level, not only the
service level. Exactly symmetric to fk_account_transactions_income_id_user_id
(same CASCADE direction, same canonical-owns-its-projection rationale).
Receipt's own, entirely independent expense_id -> expenses.id ON DELETE
SET NULL FK (see 9. Receipts) is unaffected by this: both FK actions
fire from the same Expense DELETE statement with no ordering conflict,
since they target two different child tables.

fk_account_transactions_transfer_id_user_id

FOREIGN KEY (transfer_id, user_id) REFERENCES account_transfers(id,
user_id) ON DELETE CASCADE (VF-018B). Composite ownership FK: transfer_id
must belong to the SAME user_id as this row, at the database level. ON
DELETE CASCADE follows the Income/Expense precedent: the canonical
transfer owns its projections, so deleting a posted transfer removes
both of them in the same statement.

Indexes

user_id
(account_id, transaction_date) - per-account transaction history,
ordered access, and future balance aggregation
(transfer_id, direction) - via uq_account_transactions_transfer_id_direction
(VF-018B)

Immutability: direct rows (opening_balance, adjustment) are append-only -
there is no UPDATE/DELETE path or endpoint for either. Corrections are
made with compensating adjustment entries, never edits - identical
philosophy to GoalTransaction. Income-backed rows (kind="income") and
expense-backed rows (kind="expense") are the deliberate exceptions this
section's earlier VF-017B text already anticipated: each is a
synchronized projection of its source Income/Expense row, and may be
created/updated/deleted ONLY through income_service/expenses_service
respectively, atomically with the source row itself (see 4. Expenses /
8. Income) - never through a public AccountTransaction endpoint, which
still exposes no PATCH/DELETE at all, for any kind of row. See
account_transaction_repository.py's create_income_projection/
update_income_projection/delete_income_projection and their exact
expense-projection counterparts (create_expense_projection/
update_expense_projection/delete_expense_projection) - narrowly-scoped
primitives that exist so no code path can accidentally make a direct row
(or the wrong source's projection) mutable by reusing something meant
only for a different source's projections. Each pair is guarded by its
own internal validation helper
(_validate_income_projection_for_mutation /
_validate_expense_projection_for_mutation) that raises before any
mutation or delete if the given row is not genuinely that source's
projection. Transfer-backed rows (kind="transfer", VF-018B) can be
created ONLY through account_transaction_repository.
create_transfer_projections, which creates both sides of a posted
transfer in one call, derives every value from the canonical transfer,
and refuses (ValueError, _validate_transfer_for_projection_creation) a
transfer that is not posted. There is no update or delete primitive for
transfer rows at all: they are removed only by ON DELETE CASCADE when
the canonical transfer is deleted.

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

Income<->Account operations (VF-017D) lock the Income row FIRST
(income_repository.get_income_by_id_for_update), then resolve its
current projection, then lock whichever Account row(s) the resulting
final state requires - one Account for attach/detach/stay, two (in
ascending UUID order, to avoid deadlocking against a concurrent
opposite-direction move) for a move between Accounts. Reading "which
Account is this Income currently linked to" before locking Income would
be a stale-read TOCTOU window, since that fact is itself derived from a
projection a concurrent request could change - hence Income is always
locked first here, the reverse of the Account-only lock order every
other Account lifecycle operation uses. This does not create a lock-
ordering cycle with those Account-only operations, since none of them
ever also lock an Income row. FX resolution (which may perform real
network I/O against ECB/NBU) always happens before any Account lock is
acquired, in both create and update - an Account row lock must never be
held across a network call. See income_service.py.

Expense<->Account operations (VF-017E) follow the exact same discipline,
substituting Expense for Income throughout: the Expense row is locked
FIRST (expenses_repository.get_expense_by_id_for_update - a genuinely
new lock this table introduces, since update_expense/delete_expense had
no row lock at all before this slice), its current projection is
resolved only after that lock is held, and only then are the required
Account row(s) locked (ascending UUID order for a move). FX resolution
happens before any Account lock in exactly the same way, and - the
Expense-specific addition - pure linkage operations (attach/detach/move/
account_id-only PATCH) never trigger FX resolution at all, since
account_id is deliberately never a member of the monetary-fields set
that decides whether the FX provider is called; this holds even for a
legacy unresolved Expense, whose snapshot stays fully NULL through any
number of linkage changes. See expenses_service.py.

Opening-balance creation: unlike goal_transactions' migration-time
backfill (a one-time historical event), account_transactions' single
opening_balance row per account is created at normal application runtime,
atomically with the Account row itself, whenever a client provides a
non-zero opening_balance on POST /api/v1/accounts. No migration backfill
exists for this table - accounts is a brand-new table with no
pre-existing balance to migrate from.

7.2 Account Transfers

Table:

account_transfers

Purpose:

Canonical record of money moving between two Accounts owned by the same
user, in the same currency (VF-018B; approved contract in
docs/modules/account-transfers.md). A transfer is not Income or Expense
and never inflates either. It is either planned (expected in the future,
no ledger effect) or posted (happened, reflected in the ledger by two
account_transactions projections - see 7.1 above).

Scope as of VF-018B: this table, its constraints, the ledger linkage in
7.1, and the repository primitives exist. The public Transfer API (create,
list, post, delete), the create idempotency algorithm, and the Account
lifecycle protections for planned references are NOT implemented yet
(VF-018C/D) - no client path can create a transfer today.

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

Owner of the transfer and of both Accounts. Denormalized, no FK

client_request_id

UUID

no

Client-generated create idempotency key, unique per user

source_account_id

UUID

no

Account the money leaves. Composite FK with user_id and currency (see
Constraints)

destination_account_id

UUID

no

Account the money enters. Always different from source_account_id

amount

NUMERIC(12,2)

no

Always positive

currency

VARCHAR(3)

no

Shared currency of both Accounts, server-derived. Same-currency only
(no FX transfers)

status

VARCHAR(10)

no

planned or posted. No server default - always set by the service

planned_date

DATE

yes

Original expected date. Set only when the transfer was created as
planned; never changes, including after posting

effective_date

DATE

yes

Accounting date on which the money is considered actually moved - the
transaction_date of both ledger projections. Set when posted

description

VARCHAR(500)

yes

Optional note. The single canonical copy of the text (projections keep
description NULL)

posted_at

TIMESTAMPTZ

yes

Technical timestamp of the change to posted (not an accounting date)

created_at

TIMESTAMPTZ

no

Server timestamp

updated_at

TIMESTAMPTZ

no

Updated automatically

There is no persisted transfer_date column: the future create request's
single transfer_date field is classified by the service into either
planned_date (future) or effective_date (today or past).

Constraints

ck_account_transfers_amount_positive

amount > 0

ck_account_transfers_distinct_accounts

source_account_id <> destination_account_id

ck_account_transfers_status_valid

status IN ('planned','posted')

ck_account_transfers_lifecycle_consistent

(status = 'planned' AND planned_date IS NOT NULL AND effective_date IS
NULL AND posted_at IS NULL) OR (status = 'posted' AND effective_date IS
NOT NULL AND posted_at IS NOT NULL) - planned_date is deliberately
unconstrained for posted rows, so both an immediately posted transfer
(planned_date NULL) and a planned-then-posted transfer (planned_date
kept) are valid

uq_account_transfers_id_user_id

UNIQUE(id, user_id) - composite FK target for
account_transactions.(transfer_id, user_id)

uq_account_transfers_user_id_client_request_id

UNIQUE(user_id, client_request_id) - at most one transfer per client
request per user; the database foundation for create idempotency. The
same key used by two different users does not collide

fk_account_transfers_source_account

FOREIGN KEY (source_account_id, user_id, currency) REFERENCES
accounts(id, user_id, currency) ON DELETE RESTRICT

fk_account_transfers_destination_account

FOREIGN KEY (destination_account_id, user_id, currency) REFERENCES
accounts(id, user_id, currency) ON DELETE RESTRICT

Both foreign keys reference the same transfer.currency column, so source,
destination, and transfer currencies can never diverge, both Accounts
must belong to the transfer's user, a referenced Account cannot be
deleted, and a referenced Account's currency cannot change (NO ACTION on
referenced-key update) - all at the database level.

Indexes

source_account_id
destination_account_id
(user_id, client_request_id) - via the unique constraint above; also
serves list-by-user queries

Ledger relationship: a planned transfer has zero account_transactions
rows and never affects current Account balances. A posted transfer has
exactly two: a kind="transfer" debit on source_account_id and a
kind="transfer" credit on destination_account_id, both with the
transfer's amount and transaction_date = effective_date. The database
guarantees at most one debit and one credit per transfer
(uq_account_transactions_transfer_id_direction) and correct linkage
(ck_account_transactions_source_linkage_valid, composite ownership FK).
"Exactly two rows when posted, none when planned" cannot be expressed
without triggers (none are used) and is a service-level atomicity
invariant: create_transfer_projections is the only way to create
transfer rows, creates both at once, and refuses a planned transfer;
the service paths that call it (posted create, manual post) arrive in
VF-018C/D.

Deletion: deleting a transfer removes its projections via ON DELETE
CASCADE (see 7.1). Transfers use hard delete - no reversal entity.

Security: account_transfers is the first business table created after
VF-SEC-01; its creation migration (1edb74dc96d8) also explicitly revokes
all privileges on it from the Supabase Data API roles - see 10.1.

8. Income

Table:

income

Purpose:

Stores money the user received - salary, freelance payment, refund,
gift, or other. Income does not have its own category table; `source`
(below) is the only classification this domain provides.

This table still has no account_id column, even though Income can now
be linked to an Account (VF-017D). Income is the canonical record; its
link to an Account is represented entirely by an AccountTransaction row
(kind="income") in account_transactions whose income_id points back here
- see 7.1 Account Transactions above. Storing account_id on both sides
would create two independently-writable copies of the same fact; the
public API's account_id (see docs/api-contract.md) is derived from that
projection at read time, never persisted on income itself.

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

amount

NUMERIC(12,2)

no

Amount received, in currency. Never revalued.

currency

VARCHAR(3)

no

Default EUR

received_at

DATE

no

Date the money was actually received

source

VARCHAR(20)

no

salary, freelance, refund, gift, or other

description

VARCHAR(500)

yes

Optional free-text note

base_amount

NUMERIC(12,2)

yes

amount converted to the user's base currency, using the historical rate
in effect on received_at. Backend-derived only.

base_currency

VARCHAR(3)

yes

The base currency base_amount is denominated in

fx_rate

NUMERIC(18,8)

yes

units of base_currency per 1 unit of currency; base_amount = amount *
fx_rate

fx_rate_date

DATE

yes

The actual published rate date used - may differ from received_at
(weekends/holidays), never later than it

fx_source

VARCHAR(30)

yes

'identity' | 'ecb' | 'nbu'

created_at

TIMESTAMPTZ

no

Server timestamp

updated_at

TIMESTAMPTZ

no

Updated automatically

Constraints

ck_income_amount_positive

amount > 0

ck_income_source_valid

source IN ('salary','freelance','refund','gift','other')

ck_income_base_amount_positive

base_amount IS NULL OR base_amount > 0

ck_income_fx_rate_positive

fx_rate IS NULL OR fx_rate > 0

ck_income_fx_snapshot_all_or_none

The five FX columns (base_amount, base_currency, fx_rate, fx_rate_date,
fx_source) must be either all NULL or all NOT NULL together - identical
technique to ck_expenses_fx_snapshot_all_or_none

uq_income_id_user_id

UNIQUE(id, user_id) (VF-017D) - composite-unique FK target, not a
business-rule constraint by itself. Lets account_transactions carry a
(income_id, user_id) -> income(id, user_id) foreign key, so a cross-user
Income<->Account link is impossible to construct at the database level,
not only the service level (see 7.1 above).

Indexes

user_id
received_at

FX architecture: this table reuses the exact same FX resolution
infrastructure Expense established in 81d194a3e0ff/0e300e8d7162
(app.modules.fx, financial_settings.get_base_currency) - not a new FX
implementation. Unlike expenses, income has no legacy-unresolved rows:
every Income row is created after this FX logic exists, so all five FX
columns are always populated together for every row (the all-or-none
CHECK still exists at the database level as the same structural
guarantee Expense has, but in practice the "all NULL" branch is never hit
for Income). Currency identity (currency == base currency) resolves
instantly to fx_rate = 1, fx_source = "identity", with no network call. A
foreign-dated future income is rejected before any resolution is
attempted - see docs/api-contract.md's Income section for the exact
public error message, which is deliberately distinct from Expense's own
message even though the underlying detection logic is fully shared.

Account linkage (VF-017D): allowed only when Income.currency exactly
matches Account.currency, after normalization - no FX conversion happens
between Income and Account (base_amount above is never used for Account
balance; that is a separate, unrelated FX concern). Linking is rejected
(409, reusing the existing AccountArchivedError) when it would add NEW
activity to an archived Account - creating, attaching, or moving INTO
one - but amount/received_at corrections to an Income already linked to
an Account archived afterward, and detaching/deleting/moving OUT of an
archived Account, remain allowed; see 7.1 above for the exact locking
order (Income locked first, then the required Account row(s)) and
docs/api-contract.md for the full PATCH semantics.

No production/backfill logic exists for this table - income is a
brand-new table with no pre-existing data to migrate. The account_id
linkage columns/constraints added by VF-017D live entirely on
account_transactions (7.1 above), not on this table.

9. Receipts

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

9.1 User Financial Settings

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

10. Ownership Model

All main entities contain:

user_id UUID NOT NULL

The current schema intentionally does not use:

FOREIGN KEY user_id → users.id

because authentication identity is handled outside these domain tables.

Application queries must therefore enforce ownership explicitly:

WHERE id = :resource_id
AND user_id = :authenticated_user_id

This rule is part of the security model.

10.1 Supabase Data API Posture (VF-SEC-01)

FastAPI is the only business-data gateway. Every business read/write in
this application goes:

mobile → Supabase Auth (bearer token) → FastAPI → SQLAlchemy → PostgreSQL

never:

mobile/anything → Supabase Data API (PostgREST) → business tables

The FastAPI backend connects to PostgreSQL directly via SQLAlchemy/
psycopg2 and never depends on Supabase's Data API for any of its own
reads or writes, so this posture does not change backend behavior.

As of migration edcfdf3f7114 (VF-SEC-01), the Supabase Data API roles -
anon, authenticated, and service_role - have no table privileges at all
on the 12 application-owned public tables that existed at that migration
(the 11 business tables of that time plus alembic_version;
account_transfers, added later, is covered below). Data API access to any of them now
requires an explicit future security review and an explicit, narrowly-
scoped GRANT - never a blanket re-opening.

Supabase Auth and Supabase Storage are structurally independent systems
from the Data API/PostgREST layer and both remain fully enabled and
unaffected: Auth is verified per-request against Supabase's `/auth/v1/
user` endpoint; Storage (used only for receipt files, only when
RECEIPT_STORAGE_DRIVER=supabase) is accessed via Supabase's `/storage/
v1/object/...` HTTP API with a backend-only secret key, authorized
through Storage's own bucket policies rather than `public` schema table
grants.

New Alembic-created public tables are private by default going forward:
this migration also strips the postgres role's default privileges for
future tables/sequences/functions from anon/authenticated/service_role,
so a new table does not silently inherit broad Data API access the way
existing tables previously did.

account_transfers (VF-018B, migration 1edb74dc96d8) is the first
business table created after VF-SEC-01. Rather than relying only on the
inherited default-privilege change, its creation migration explicitly
revokes all privileges on public.account_transfers from anon,
authenticated, and service_role, using the same pg_roles-guarded
statements as VF-SEC-01 (a no-op on local/CI PostgreSQL, where those
roles do not exist). Verifying has_table_privilege for those roles in
production is part of the VF-018B deployment checklist and has not been
performed as part of local development.

Row-Level Security (RLS) is deliberately NOT enabled as part of this
posture: once these roles hold no table privileges, the tables are
already unreachable via Data API regardless of RLS, so it is not the
current authorization boundary. RLS remains available as a future
defense-in-depth layer if direct Data API access to any table is ever
intentionally reintroduced.

None of this changes the application-layer ownership rule in §10 above -
every FastAPI-layer `user_id` scoping check remains mandatory regardless
of database-level Data API privileges, since Data API exposure and
FastAPI's own authorization are independent, layered defenses.

alembic_version is migration metadata, not business data, and is
included in the same revoke: it must never be directly readable or
writable by anon/authenticated/service_role, since a client-writable
migration-tracking row is a schema-integrity risk in its own right.

Operational note: Supabase Dashboard → Data API → "Default privileges
for new entities" should also be verified OFF during production
rollout, as a platform-level confirmation alongside this migration's
own default-privilege changes.

11. Relationship Summary

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
   ├──< account_transactions.account_id
   │
   ├──< account_transfers.source_account_id       (VF-018B)
   │
   └──< account_transfers.destination_account_id  (VF-018B)

account_transfers
   │
   └──< account_transactions.transfer_id  (VF-018B)

income
   │
   └──< account_transactions.income_id  (VF-017D)

expenses
   │
   ├──< account_transactions.expense_id  (VF-017E)
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
RESTRICT, VF-017B) - including account_transactions rows created by
linking an Income (VF-017D) or an Expense (VF-017E);
has_transactions_for_account is kind-agnostic, so this happens
automatically with no Income/Expense-specific code. Also rejected at the
database level if any account_transfers row references the account as
source or destination (ON DELETE RESTRICT, VF-018B) - including a planned
transfer, which has no account_transactions rows. The controlled
application-level 409 for that case arrives in VF-018C.

AccountTransfer deleted
    ↓
Its account_transactions projection rows (two for a posted transfer,
none for a planned one) are deleted with it (ON DELETE CASCADE,
VF-018B) - the transfer is canonical and owns its projections.

Income deleted
    ↓
Its account_transactions projection row (if any) is deleted with it
(ON DELETE CASCADE, VF-017D) - the inverse of Account/Goal's RESTRICT:
Income is canonical and owns its projection, so the projection vanishes
with its source rather than blocking Income's own deletion.

Expense deleted
    ↓
Its account_transactions projection row (if any) is deleted with it
(ON DELETE CASCADE, VF-017E) - exactly symmetric to Income's own
CASCADE. Independently, and from the same DELETE statement:
Receipt.expense_id = NULL (ON DELETE SET NULL, unchanged since before
VF-017E) - both FK actions fire together with no ordering conflict,
since they target two different child tables.

No dependent financial records are automatically deleted through these relationships, except a budget's own version history (deleted with it), an Income's or Expense's own AccountTransaction projection (deleted with it), and an AccountTransfer's own projections (deleted with it). A Goal or an Account with transaction history cannot be deleted at all, and an Account referenced by any transfer cannot be deleted either.

12. Database-Enforced Invariants

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

Income.amount > 0
Income.source is one of salary/freelance/refund/gift/other
Income.base_amount > 0 when present
Income.fx_rate > 0 when present
Income's five FX snapshot columns are all NULL or all NOT NULL together

At most one AccountTransaction with a given income_id (UNIQUE(income_id),
VF-017D) - one Income can create at most one ledger projection

At most one AccountTransaction with a given expense_id
(UNIQUE(expense_id), VF-017E) - one Expense can create at most one
ledger projection

An income-kind AccountTransaction always has income_id set, expense_id
NULL, and direction = credit; an expense-kind AccountTransaction always
has expense_id set, income_id NULL, and direction = debit; a direct
(opening_balance/adjustment) row always has both income_id and
expense_id NULL (VF-017E, single combined CHECK constraint,
ck_account_transactions_source_linkage_valid, replacing VF-017D's
income-only version) - the three branches are mutually exclusive by
construction since kind is a single scalar value

An AccountTransaction's account_id must belong to the same user_id as the
row itself (composite FK, VF-017D) - a cross-user Account link is
impossible to construct at the database level

An AccountTransaction's income_id, when set, must belong to the same
user_id as the row itself (composite FK, VF-017D) - a cross-user Income
link is impossible to construct at the database level

An AccountTransaction's expense_id, when set, must belong to the same
user_id as the row itself (composite FK, VF-017E) - a cross-user Expense
link is impossible to construct at the database level

A transfer-kind AccountTransaction always has transfer_id set and
income_id/expense_id NULL, and every income, expense, and direct row has
transfer_id NULL (VF-018B, same combined CHECK)

At most one debit and at most one credit AccountTransaction per transfer
(UNIQUE(transfer_id, direction), VF-018B)

An AccountTransaction's transfer_id, when set, must belong to the same
user_id as the row itself (composite FK, VF-018B)

AccountTransfer.amount > 0
AccountTransfer.source_account_id <> destination_account_id
AccountTransfer.status is one of planned/posted
AccountTransfer status/date consistency: planned has planned_date and no
effective_date/posted_at; posted has effective_date and posted_at
(VF-018B, ck_account_transfers_lifecycle_consistent)

At most one AccountTransfer per (user_id, client_request_id) (VF-018B)

An AccountTransfer's source and destination Accounts must belong to the
transfer's user_id and have the transfer's currency (composite FKs
including currency, VF-018B) - cross-user and cross-currency transfers
are impossible to construct at the database level, and a referenced
Account's currency cannot change

A category still referenced by a budget cannot be deleted (ON DELETE RESTRICT)

A goal still referenced by a goal_transactions row cannot be deleted (ON DELETE RESTRICT)

An account still referenced by an account_transactions row cannot be deleted (ON DELETE RESTRICT)

An account still referenced by an account_transfers row cannot be deleted (ON DELETE RESTRICT, VF-018B)

These constraints protect data even if an application-layer validation path is bypassed.

13. Application-Enforced Invariants

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

Linking an Income to an Account requires an exact currency match, after
normalization (VF-017D) - no FX conversion happens between Income and
Account; Income's own base-currency FX snapshot is untouched by linking.
No silent auto-detach: a currency change that would leave an Income
linked to a now-mismatched Account is rejected outright, never resolved
by detaching on the client's behalf.

Linking an Income to an Account is rejected only when it would add NEW
activity to an archived Account - creating, attaching, or moving INTO
one (VF-017D, reuses AccountArchivedError). Amount/received_at
corrections to an Income already linked to an Account archived
afterward, and detaching/deleting/moving OUT of an archived Account,
remain allowed - that is maintenance of existing history, not new
activity.

Updating or deleting a linked Income locks the Income row first
(get_income_by_id_for_update), then the required Account row(s) - the
reverse of every other Account lifecycle operation's lock order, and
necessary because "which Account is this Income currently linked to" is
itself derived from a projection a concurrent request could change
(VF-017D).

Linking an Expense to an Account requires an exact currency match, after
normalization (VF-017E) - no FX conversion happens between Expense and
Account, and the ledger uses Expense.amount, never base_amount. No
silent auto-detach: a currency change that would leave an Expense linked
to a now-mismatched Account is rejected outright.

Linking an Expense to an Account is rejected only when it would add NEW
activity to an archived Account - creating, attaching, or moving INTO
one (VF-017E, reuses AccountArchivedError). Amount/expense_date
corrections to an Expense already linked to an Account archived
afterward, and detaching/deleting/moving OUT of an archived Account,
remain allowed.

Updating or deleting a linked Expense locks the Expense row first
(get_expense_by_id_for_update - a genuinely new lock this table
introduces, VF-017E), then the required Account row(s) - the same
reversed lock order Income uses, for the identical TOCTOU-avoidance
reason.

Pure Expense<->Account linkage operations (attach/detach/move/
account_id-only PATCH) never trigger FX resolution - account_id is
deliberately never a member of the monetary-fields set that decides
whether the FX provider is called (VF-017E). This holds even for a
legacy unresolved Expense (pre-VF-014B5C, all five FX snapshot columns
NULL): its snapshot stays fully NULL through any number of linkage
changes, and only a genuine monetary field change (amount, currency, or
expense_date - the pre-existing rule, unrelated to linkage) can ever
resolve it.

A planned AccountTransfer has zero ledger projections and a posted one
has exactly two (source debit, destination credit) - a service-level
atomicity invariant, not a database constraint (VF-018B). Its
foundation exists: create_transfer_projections creates both rows at
once and refuses a planned transfer. The service paths that create and
post transfers (VF-018C/D) do not exist yet.

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

A foreign-currency Income dated in the future is rejected outright (no
estimated rate is ever persisted as if it were historical fact) - a
base-currency (identity) Income has no such restriction, since identity
conversion needs no historical rate at all. Mirrors Expense's identical
rule exactly, reusing the same fx_service logic, but surfaces its own
distinct public error message (see docs/api-contract.md).

This separation is intentional:

Database
    ↓
protects structural/data invariants

Application
    ↓
protects contextual business rules

14. Transactions

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

15. Migration Strategy

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

16. Design Principles

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

17. Current Schema

PostgreSQL
│
├── categories
│   ├── PK id
│   └── UNIQUE user_id + lower(name)
│
├── expenses
│   ├── PK id
│   ├── FK category_id → categories
│   └── UNIQUE id + user_id (VF-017E, composite FK target)
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
│   ├── PK id
│   ├── UNIQUE id + user_id (VF-017D, composite FK target)
│   └── UNIQUE id + user_id + currency (VF-018B, composite FK target)
│
├── account_transactions
│   ├── PK id
│   ├── FK account_id → accounts (ON DELETE RESTRICT)
│   ├── FK (account_id, user_id) → accounts (id, user_id) (ON DELETE RESTRICT, VF-017D)
│   ├── FK (income_id, user_id) → income (id, user_id) (ON DELETE CASCADE, VF-017D)
│   ├── FK (expense_id, user_id) → expenses (id, user_id) (ON DELETE CASCADE, VF-017E)
│   ├── FK (transfer_id, user_id) → account_transfers (id, user_id) (ON DELETE CASCADE, VF-018B)
│   ├── UNIQUE income_id (VF-017D)
│   ├── UNIQUE expense_id (VF-017E)
│   └── UNIQUE transfer_id + direction (VF-018B)
│
├── account_transfers (VF-018B)
│   ├── PK id
│   ├── FK (source_account_id, user_id, currency) → accounts (id, user_id, currency) (ON DELETE RESTRICT)
│   ├── FK (destination_account_id, user_id, currency) → accounts (id, user_id, currency) (ON DELETE RESTRICT)
│   ├── UNIQUE id + user_id (composite FK target)
│   └── UNIQUE user_id + client_request_id
│
├── income
│   ├── PK id
│   └── UNIQUE id + user_id (VF-017D, composite FK target)
│
├── receipts
│   ├── PK id
│   └── FK expense_id → expenses
│
└── user_financial_settings
    └── PK user_id

This document should be updated whenever the persisted schema, constraints, relationships, or migration strategy changes.