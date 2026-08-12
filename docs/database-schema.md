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

ON DELETE SET NULL

A deleted category does not delete the budget.

Constraints

Positive budget limit:

ck_budgets_limit_amount_positive

limit_amount > 0

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

expenses
   │
   └──< receipts.expense_id

Delete behavior:

Category deleted
    ↓
Expense.category_id = NULL
Budget.category_id  = NULL

Expense deleted
    ↓
Receipt.expense_id = NULL

No dependent financial records are automatically deleted through these relationships.

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

These constraints protect data even if an application-layer validation path is bypassed.

11. Application-Enforced Invariants

Some rules require business context and are currently enforced by Pydantic/service logic rather than directly by PostgreSQL.

Examples:

Goal.current_amount <= Goal.target_amount

Budget.end_date >= Budget.start_date

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
│   ├── FK category_id → categories
│   └── UNIQUE user_id + name + period + start_date
│
├── goals
│   └── PK id
│
└── receipts
    ├── PK id
    └── FK expense_id → expenses

This document should be updated whenever the persisted schema, constraints, relationships, or migration strategy changes.