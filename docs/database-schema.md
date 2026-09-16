🗄 Database Schema — Valor Finis

This document describes the current PostgreSQL schema used by the Valor Finis backend.

The database layer is managed with SQLAlchemy and Alembic.

1. Overview

Main application tables:

categories
expenses
budgets
goals
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
        NUMERIC current_amount
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

Constraint

ck_expenses_amount_positive

Rule:

amount > 0

Indexes

user_id
category_id
expense_date

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

current_amount

NUMERIC(12,2)

no

Default 0

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

ck_goals_current_amount_non_negative

current_amount >= 0

Indexes

user_id
target_date

The rule:

current_amount <= target_amount

is currently enforced by the application/service validation layer rather than by a PostgreSQL check constraint.

7. Receipts

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

7.1 User Financial Settings

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

8. Ownership Model

All main entities contain:

user_id UUID NOT NULL

The current schema intentionally does not use:

FOREIGN KEY user_id → users.id

because authentication identity is handled outside these domain tables.

Application queries must therefore enforce ownership explicitly:

WHERE id = :resource_id
AND user_id = :authenticated_user_id

This rule is part of the security model.

9. Relationship Summary

categories
   │
   ├──< expenses.category_id
   │
   └──< budgets.category_id

budgets
   │
   └──< budget_versions.budget_id

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

Expense deleted
    ↓
Receipt.expense_id = NULL

No dependent financial records are automatically deleted through these relationships, except a budget's own version history, which is deleted with it.

10. Database-Enforced Invariants

PostgreSQL currently protects these important rules directly:

Expense.amount > 0

Budget.limit_amount > 0

Goal.target_amount > 0
Goal.current_amount >= 0

Receipt.status is valid
Receipt.total_amount_detected > 0 when present

Category names are unique per user case-insensitively

Budget user/name/period/start_date combinations are unique

Budget.period is one of weekly/monthly/yearly

BudgetVersion.limit_amount > 0
BudgetVersion.effective_until >= effective_from when present
BudgetVersion.change_reason is valid

A category still referenced by a budget cannot be deleted (ON DELETE RESTRICT)

These constraints protect data even if an application-layer validation path is bypassed.

11. Application-Enforced Invariants

Some rules require business context and are currently enforced by Pydantic/service logic rather than directly by PostgreSQL.

Examples:

Goal.current_amount <= Goal.target_amount

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

12. Transactions

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

13. Migration Strategy

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

14. Design Principles

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

15. Current Schema

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
├── receipts
│   ├── PK id
│   └── FK expense_id → expenses
│
└── user_financial_settings
    └── PK user_id

This document should be updated whenever the persisted schema, constraints, relationships, or migration strategy changes.