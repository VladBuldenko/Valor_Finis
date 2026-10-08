🔌 API Contract — Valor Finis

This document defines the public HTTP contract of the current Valor Finis backend.

It is intentionally concise. FastAPI Swagger remains the detailed interactive schema reference:

http://localhost:8000/docs

1. Base URL

Local API:

http://localhost:8000

Versioned API prefix:

/api/v1

Example:

GET http://localhost:8000/api/v1/expenses

2. Authentication

All business endpoints require an authenticated user.

Development mode

AUTH_MODE=development

Use:

X-User-Id: <UUID>

Example:

X-User-Id: c78a119f-8f95-4316-88cc-97c555a01e65

Supabase mode

AUTH_MODE=supabase

Use:

Authorization: Bearer <access_token>

The backend resolves the user ID from authentication data. Clients do not provide user_id in resource creation payloads.

3. Common Conventions

Content types

JSON endpoints use:

Content-Type: application/json

Receipt upload uses:

Content-Type: multipart/form-data

Identifiers

Resource identifiers are UUID values.

Ownership

All user-owned resources are scoped to the authenticated user.

A resource that does not exist for the current user is treated as unavailable to that user.

PATCH requests

PATCH endpoints accept partial updates.

Empty update bodies are rejected.

Fields that are required by the resource cannot normally be explicitly changed to null.

Delete responses

Successful deletes return:

204 No Content

4. System Endpoints

GET /

Returns basic API metadata.

Response: 200 OK

Example:

{
  "service": "Valor API",
  "version": "0.1.0",
  "status": "running",
  "docs": "/docs",
  "health": "/health"
}

GET /health

Health check for the API process.

Response: 200 OK

{
  "status": "ok",
  "service": "valor-api",
  "version": "0.1.0"
}

5. Categories

Base path:

/api/v1/categories

Endpoints

Method

Path

Success

POST

/api/v1/categories

201

GET

/api/v1/categories

200

GET

/api/v1/categories/{category_id}

200

PATCH

/api/v1/categories/{category_id}

200

DELETE

/api/v1/categories/{category_id}

204

Create Category

POST /api/v1/categories

Request:

{
  "name": "Food",
  "color": "#22C55E",
  "icon": "shopping-cart"
}

Fields:

Field

Required

Notes

name

yes

1–80 characters; whitespace is normalized

color

no

optional UI value, max 20 characters

icon

no

optional UI value, max 50 characters

is_default is controlled by the backend and is not accepted from the client.

Category names are unique per user case-insensitively.

Update Category

PATCH /api/v1/categories/{category_id}

Example:

{
  "name": "Groceries",
  "color": "#16A34A"
}

At least one editable field is required.

Default categories cannot be modified or deleted.

Category Response

{
  "id": "<uuid>",
  "user_id": "<uuid>",
  "name": "Food",
  "color": "#22C55E",
  "icon": "shopping-cart",
  "is_default": false,
  "created_at": "<datetime>",
  "updated_at": "<datetime>"
}

6. Expenses

Base path:

/api/v1/expenses

Endpoints

Method

Path

Success

POST

/api/v1/expenses

201

GET

/api/v1/expenses

200

PATCH

/api/v1/expenses/{expense_id}

200

DELETE

/api/v1/expenses/{expense_id}

204

Account linkage (VF-017E): an Expense may optionally be linked to an
Account via `account_id` on POST/PATCH. Expense remains the canonical
record - linking it creates a synchronized AccountTransaction ledger
projection (kind="expense", direction="debit") in the linked Account,
which is how that Account's balance comes to reflect it (Account balance
is always SUM(credits) - SUM(debits) over its account_transactions rows
- see the Accounts section below). `account_id` has NO database column
on expenses at all: the value returned on ExpenseResponse is derived
from that projection at read time, never persisted on the Expense row
itself. Linking is allowed only when Expense.currency exactly matches
Account.currency (after normalization) - there is no FX conversion
between Expense and Account, and the ledger always uses Expense.amount,
never base_amount (base_amount is base-currency analytics truth, not the
amount that actually left an Account). Attaching/detaching/moving an
Expense's Account linkage never resolves or touches the Expense's own FX
snapshot (below) - including for a legacy unresolved Expense, whose
snapshot stays fully NULL through any number of linkage changes; only a
genuine monetary field change (amount, currency, or expense_date, the
pre-existing rule below) can ever trigger FX resolution.

Create Expense

POST /api/v1/expenses

Request:

{
  "category_id": null,
  "title": "Groceries",
  "amount": "35.50",
  "currency": "EUR",
  "expense_date": "2026-08-09",
  "description": "Weekly shopping",
  "source": "manual",
  "account_id": null
}

Fields:

Field

Required

Notes

category_id

no

UUID or null

title

yes

1–120 characters

amount

yes

greater than 0, up to 12 digits with 2 decimal places (NUMERIC(12,2):
at most 9999999999.99); more decimal places or digits are rejected with
422, never rounded

currency

no

3 characters, default EUR. Normalized to uppercase; must be exactly 3
alphabetic characters.

expense_date

yes

date

description

no

optional or null, max 500 characters (longer is rejected with 422)

source

no

max 30 characters, default manual

account_id

no

optional Account to link this Expense to; the Account must belong to the
authenticated user, must not be archived, and its currency must exactly
match this Expense's currency

If category_id is provided, the category must belong to the authenticated user.

VF-014B5C: the server resolves a base-currency FX snapshot for every
create/update from amount/currency/expense_date - see "Expense Response"
below. base_amount, base_currency, fx_rate, fx_rate_date, and fx_source
are never accepted on create or update; the request schema uses
extra="forbid", so submitting any of them is rejected with 422. A
foreign-currency expense (currency different from the user's base
currency) dated in the future is rejected with 422 - no rate exists for
a future date.

Update Expense

PATCH /api/v1/expenses/{expense_id}

Example:

{
  "amount": "42.00",
  "description": "Updated amount"
}

At least one field is required.

amount and description follow the same limits as on create (amount up to
12 digits with 2 decimal places; description max 500 characters);
description may be set to null to clear it.

category_id may be set to null to make the expense uncategorized.

`account_id` has three-state PATCH semantics (VF-017E), matching
category_id's own convention exactly: absent from the request leaves the
current linkage untouched; a UUID attaches (if currently unlinked) or
moves (if already linked elsewhere); explicit `null` detaches. The PATCH
is evaluated against its FINAL resulting state, not field-by-field in
isolation - e.g. changing `currency` and `account_id` together in one
request is validated against the combination that results, so an EUR
Expense on an EUR Account can move to a USD Account while also changing
to USD in the same request, as long as the final currency matches the
final Account. There is no silent auto-detach: a currency change that
would leave the Expense linked to a now-mismatched Account is rejected
outright (422), never resolved by detaching on the client's behalf.

Archived-Account rule: rejected only when the PATCH would add NEW
activity to an Account - attaching, or moving INTO an archived Account
(409, the existing "Archived account cannot receive new transactions."
message). Amount/expense_date corrections to an Expense already linked
to an Account that was archived afterward are allowed (this is
maintaining existing history, not new activity), as is detaching from,
deleting from, or moving OUT of an archived Account.

Expense Response

{
  "id": "<uuid>",
  "user_id": "<uuid>",
  "category_id": null,
  "title": "Groceries",
  "amount": "35.50",
  "currency": "EUR",
  "expense_date": "2026-08-09",
  "description": "Weekly shopping",
  "source": "manual",
  "account_id": null,
  "base_amount": "35.50",
  "base_currency": "EUR",
  "fx_rate": "1.00000000",
  "fx_rate_date": "2026-08-09",
  "fx_source": "identity",
  "created_at": "<datetime>",
  "updated_at": "<datetime>"
}

account_id is read-only and fully derived (VF-017E): Expense has no
account_id database column at all, so this value is resolved from the
AccountTransaction projection at read time - null means unlinked.

FX snapshot fields (VF-014B5C, all read-only, optional, added by the
server - never accepted as input):

Field

Notes

base_amount

amount converted to the user's base currency (VF-014B5B), using the
historical rate for expense_date, quantized to 2 decimal places.

base_currency

the base currency base_amount is denominated in.

fx_rate

units of base_currency per 1 unit of currency:
base_amount = amount * fx_rate.

fx_rate_date

the actual published rate date used. May be earlier than expense_date
(weekends/holidays, bounded lookback); never later than it.

fx_source

"identity" (currency already equals the base currency), "ecb", or
"nbu".

All five fields are null together only for a legacy expense created
before VF-014B5C whose snapshot has not yet been resolved (resolution
happens automatically the next time the expense receives a monetary
update). Every expense created after VF-014B5C always has them
populated.

7. Budgets

Base path:

/api/v1/budgets

Endpoints

Method

Path

Success

POST

/api/v1/budgets

201

GET

/api/v1/budgets

200

PATCH

/api/v1/budgets/{budget_id}

200

DELETE

/api/v1/budgets/{budget_id}

204

Create Budget

POST /api/v1/budgets

Request:

{
  "category_id": null,
  "name": "Monthly groceries",
  "limit_amount": "400.00",
  "currency": "EUR",
  "period": "monthly",
  "start_date": "2026-08-01",
  "end_date": "2026-08-31"
}

Fields:

Field

Required

Notes

category_id

no

UUID or null

name

yes

1–120 characters

limit_amount

yes

greater than 0

currency

no

default EUR; normalized to uppercase

period

no

weekly, monthly, or yearly; default monthly

start_date

yes

date

end_date

no

must not be before start_date

Duplicate budgets are rejected for the same user, name, period, and start date.

Update Budget

PATCH /api/v1/budgets/{budget_id}

At least one field is required.

category_id and end_date may be set to null.

Budget Response

Returns the create fields plus:

id
user_id
created_at
updated_at

8. Goals

Base path:

/api/v1/goals

Endpoints

Method

Path

Success

POST

/api/v1/goals

201

GET

/api/v1/goals

200

PATCH

/api/v1/goals/{goal_id}

200

DELETE

/api/v1/goals/{goal_id}

204

POST

/api/v1/goals/{goal_id}/transactions

201

GET

/api/v1/goals/{goal_id}/transactions

200

Funding model (VF-016):

current_amount is READ-ONLY on every Goal endpoint. It is not accepted by
POST /api/v1/goals or PATCH /api/v1/goals/{goal_id} - sending it is
rejected (extra fields are forbidden). A Goal always starts at 0 and can
only be funded or drawn down afterward through
POST /api/v1/goals/{goal_id}/transactions.

Balance source (VF-016D, storage removed in VF-016G): every current_amount
value returned by this API - from POST /api/v1/goals, GET /api/v1/goals,
PATCH /api/v1/goals/{goal_id}, and GET /api/v1/analytics/goal-progress - is
computed directly from the goal_transactions ledger at read time
(opening_balance + contribution - withdrawal). The Goal row has no balance
column at all: goal_transactions is the only persisted source of a Goal's
balance.

Create Goal

POST /api/v1/goals

Request:

{
  "name": "Vacation",
  "target_amount": "2000.00",
  "currency": "EUR",
  "target_date": "2026-12-31",
  "status": "active"
}

Fields:

Field

Required

Notes

name

yes

1–150 characters

target_amount

yes

greater than 0

currency

no

default EUR; trimmed; must contain only ASCII characters; normalized to
uppercase; must then be exactly three ASCII letters A-Z (VF-020B1)

target_date

no

optional date

status

no

active, completed, archived; default active; never auto-derived

Every new Goal is created with current_amount = 0.00. Sending
current_amount in this request is rejected (422).

Goal currency validation (VF-020B1): "eur" is accepted and stored as
"EUR". Any value that is not exactly three ASCII letters after trimming
and uppercasing - for example "EU", "EURO", "12$", "E1R" or "ÉUR" - is
rejected with 422. Input containing any non-ASCII character is rejected
before uppercasing, so values such as "ıNR" or "uſd" are also 422 even
though uppercasing would turn them into "INR" or "USD". A value with surrounding whitespace that is longer
than three characters (for example " EUR") fails the three-character
length check and is also rejected with 422. The same rule applies to
currency in PATCH /api/v1/goals/{goal_id}.

Update Goal

PATCH /api/v1/goals/{goal_id}

At least one field is required.

target_date may be set to null.

Sending current_amount in this request is rejected (422).

Overfunding is allowed: target_amount may be lowered below the Goal's
current ledger-derived balance at any time. There is no amount business
rule to satisfy - the old "current_amount <= target_amount" rule was
removed along with current_amount's client-writability. status is never
auto-changed based on balance/target comparisons; it remains a manual
field.

Currency immutability (VF-016E): currency may be freely changed while the
Goal has no transaction history. As soon as any GoalTransaction exists for
the Goal - opening_balance, contribution, or withdrawal, regardless of the
Goal's current ledger balance - an actual currency change is rejected with
409 Conflict ("Goal currency cannot be changed after transaction history
exists."). Resending the Goal's current currency (normalized, any casing)
is not an actual change and is always allowed, even with history. This
exists because every GoalTransaction amount is expressed in its Goal's
currency (since VF-020B3 each new row also stores a copy of it):
changing Goal.currency after history exists would reinterpret every
historical ledger amount in a different currency, which is invalid. All
other fields - name, target_amount, target_date, status - remain freely
editable regardless of transaction history.

Every balance-changing and metadata-changing write on a Goal (contribution/
withdrawal creation, and now currency-affecting PATCH/DELETE) locks the
owned Goal row with SELECT ... FOR UPDATE before checking transaction
history, so a currency change or deletion can never race against the
Goal's first transaction and see a stale "no history" state.

Goal Response

Returns the goal fields plus:

id
user_id
created_at
updated_at

current_amount is always present in the response (backward compatible),
computed from the goal_transactions ledger as described above and never
persisted on the Goal row itself. It may exceed target_amount -
overfunding is a valid, representable state.

Partitions (VF-020C2), all read-only and ledger-derived:

tracked_amount - net amount of the unlinked partition (rows without an
Account).

linked_amount - net amount reserved against Accounts (linked contributions
minus linked withdrawals, all Accounts). current_amount = tracked_amount +
linked_amount.

allocations - array of { "account_id", "amount" } with the Goal's CURRENT
non-zero Account partitions, ordered by account_id. It is a summary, not an
audit history: released (zero) partitions are not listed. The Goal's
transaction history is the audit trail; each transaction exposes a nullable
account_id. These fields appear on every Goal response (list, create,
PATCH). GET /api/v1/goals/{id}/progress and analytics goal progress are
unchanged and keep using current_amount.

Delete Goal

DELETE /api/v1/goals/{goal_id}

Safe deletion (VF-016E): a Goal with no transaction history is hard-
deleted (204). A Goal with any transaction history - opening_balance,
contribution, or withdrawal, regardless of the Goal's current ledger
balance (a fully-withdrawn 0.00-balance Goal still counts) - cannot be
hard-deleted: the request is rejected with 409 Conflict ("Goal with
transaction history cannot be deleted. Archive it instead."), and the Goal
and its full transaction history remain unchanged. There is no separate
archive endpoint: PATCH /api/v1/goals/{goal_id} with
{"status": "archived"} is the mechanism for retiring a history-bearing
Goal a user no longer wants to use, and it continues to work regardless of
transaction history. Status is never changed automatically by either
endpoint.

The 409 is a controlled application-level check (the owned Goal row is
locked and its transaction history checked before any delete is
attempted), not a caught database error - the existing
goal_transactions.goal_id foreign key (ON DELETE RESTRICT) remains in
place underneath purely as defense-in-depth and must never surface to a
client as a raw error or a 500.

Create Goal Transaction

POST /api/v1/goals/{goal_id}/transactions

Request:

{
  "type": "contribution",
  "amount": "100.00",
  "description": "Payday transfer",
  "client_request_id": "5f0c6a8e-3d2b-4c1a-9e7f-2b8d4a6c1e90"
}

Fields:

Field

Required

Notes

type

yes

"contribution" or "withdrawal" only - "opening_balance" is
system/migration-only and is rejected here (422)

amount

yes

greater than 0, up to 12 digits with 2 decimal places

description

no

optional, max 255 characters

effective_date

no

business date of the transaction, a calendar date "YYYY-MM-DD"
(VF-020B3). Omitted or null means the server date. Today and past dates
are accepted; on a new request a future date is rejected with 422 ("Goal
transaction effective date cannot be in the future.") - a replay of an
already used client_request_id is resolved by the Idempotency rules below
instead. Datetime strings, timestamps and other formats are rejected with
422, so no timezone can change the recorded day.

client_request_id

no

UUID create idempotency key (VF-020B3), see Idempotency below. Optional
for tracked requests so older clients keep working; the mobile app always
sends one. Required when account_id is set (VF-020C2).

account_id

no

UUID of an Account of the same user (VF-020C2). Omitted or null: tracked
partition. Set: linked partition of that Account, see Account-linked
operations below. Requires client_request_id.

currency is not a request field: the transaction's currency is always
copied from the Goal and a client-sent currency is rejected (422).

Business rules:

A Goal's balance can never become negative: a withdrawal whose amount
exceeds the Goal's current ledger-derived balance is rejected with 409
Conflict ("Withdrawal exceeds the current goal balance.").

Overfunding above target_amount is allowed for contributions - there is no
upper bound on a Goal's balance.

Account-linked operations (VF-020C2): the optional account_id selects the
partition the operation applies to. Omitted or null means the tracked
partition (everything above applies unchanged: the balance check of a
withdrawal is against the tracked partition only). An Account id means the
Goal's partition linked to that Account: a contribution is a reservation, a
withdrawal is a release. A reservation moves no money and writes no
AccountTransaction; the Account's current_balance does not change. A linked
request (contribution or withdrawal) MUST carry client_request_id (422
otherwise) and its effective_date must be omitted or equal to the server
date today (422 for a past or a future date); the stored date is always
today. Validation order for a NEW request (a key that already identifies a
stored transaction is resolved first, see Idempotency):

- linked contribution: schema (422) -> date (422) -> Goal (404) -> Account
  (404) -> archived Goal (409) -> archived Account (409) -> currency
  mismatch between Goal and Account (422, "Goal and Account currencies must
  match.") -> capacity (409, "Reservation exceeds the Account's reservable
  capacity."): the Account's reservable_amount must be positive and at
  least the amount;
- linked withdrawal: schema (422) -> date (422) -> Goal (404) -> Account
  (404) -> currency mismatch (422) -> amount greater than the Goal's
  partition for that Account (409, "Withdrawal exceeds the goal amount
  reserved against this account."). Archived Goals and Accounts still allow
  releases; no capacity check applies;
- tracked: unchanged (future date 422 -> Goal 404 -> archived contribution
  409 -> tracked-partition shortfall 409 with the existing message).

A missing and another user's Goal or Account are indistinguishable (both
404). Locks are taken in the order Goal -> Account (a linked contribution
locks the Account row; a linked withdrawal only reads it), so concurrent
reservations against one Account can never exceed its capacity, while
reservations against different Accounts do not serialize.

Archived goals (VF-020B1): a contribution to a Goal whose status is
archived is rejected with 409 Conflict ("Archived goal cannot receive
contributions.") and nothing is written. Withdrawals from an archived Goal
remain allowed under the same balance rule (a withdrawal above the balance
is still 409). Active and completed Goals accept both contributions and
withdrawals. Existing transactions of an archived Goal are never changed.

Every write locks the owned Goal row (SELECT ... FOR UPDATE) before
checking the Goal's status and calculating the balance from transaction
history, so two concurrent requests against the same Goal are serialized
and can never both validate against the same stale balance. Archiving a
Goal (PATCH status="archived") takes the same row lock, so a contribution
and a concurrent archive are serialized: either the contribution commits
first and the archive follows, or the archive commits first and the
contribution is rejected with 409.

Transactions are append-only: there is no PATCH or DELETE for an existing
transaction. A correction is represented later by a new, opposite
transaction (a compensating entry), never by editing history.

Every new transaction stores currency = the Goal's currency (read from the
locked Goal row) and an effective_date (the request value, or the server
date when omitted). Rows written before VF-020B3 keep NULL in these
columns; they are never backfilled from created_at.

Idempotency (VF-020B3): client_request_id is unique per user across all of
the user's Goals (the database constraint
uq_goal_transactions_user_id_client_request_id).

- First request with a key: 201, exactly one transaction is created and
  stores the key.
- Exact replay (same key, same payload): 200 with the originally stored
  transaction; nothing new is written.
- Same key, different payload: 409 Conflict ("client_request_id has
  already been used for a different goal transaction."); nothing is
  written and the original is not revealed or changed.
- Payload comparison: goal_id (from the path), type, amount as a decimal
  value ("10" equals "10.00"), and description exactly as stored (it is
  never normalized, so null and "" differ). effective_date is compared
  only when the replay request states one: an omitted (or null)
  effective_date is ignored, so a retry after midnight still replays the
  original transaction with its original date instead of conflicting with
  a recomputed "today".
- A key is resolved before the Goal's current state is checked: an exact
  replay returns 200 even if the Goal has since been archived or its
  balance can no longer cover the original withdrawal. A new key follows
  the normal rules (archived contribution 409, insufficient balance 409).
- The lookup is always scoped to the authenticated user: another user's
  keys are never visible and never match. When the request has no key, or
  the user has not used the key yet, the normal Goal rules apply - a
  missing Goal or another user's Goal is 404. When the user's own key is
  already bound to one of the user's transactions, the request is
  resolved against that transaction before any Goal lookup: a different
  goal_id (including a missing or another user's Goal id) or any other
  payload difference is a 409 conflict. That 409 depends only on the
  user's own stored transaction and reveals nothing about the target
  Goal.
- Concurrent requests with the same key create exactly one transaction:
  the others resolve as replay (200) or conflict (409) - through the
  Goal row lock and, for different Goals, through the unique constraint
  (the losing insert is rolled back and resolved against the winner) -
  never as a raw database error or 500.
- A bound key is resolved first: a replay stating a different
  effective_date is a 409 even when that date is in the future. The
  future-date check (422) applies only to new requests (no key, or a key
  not used yet) and runs before the Goal lookup, so for them it takes
  precedence over 404 and the archived/balance 409s.

Without client_request_id every request creates a new transaction (201)
and the stored key is NULL; no key is generated by the server.

Response: 201 with the created transaction, or 200 with the original
transaction for an idempotent replay (see Goal Transaction Response
below).

List Goal Transactions

GET /api/v1/goals/{goal_id}/transactions

Returns the Goal's full transaction history, newest first
(created_at DESC, id DESC). Includes migration-created opening_balance
entries alongside contribution/withdrawal entries. Another user's Goal
behaves as not found (404), the same as every other Goal endpoint.

Goal Transaction Response

Field

Notes

id

transaction identifier

goal_id

owning Goal identifier

user_id

owner (denormalized, always the Goal's owner)

type

"opening_balance", "contribution", or "withdrawal" - GET history can
return opening_balance even though POST can never create one

amount

always positive; direction is carried by type

description

optional, may be null

created_at

for opening_balance entries created by migration backfill, this is the
original Goal's created_at, not the migration's run time

currency

the Goal's currency, stored with every transaction (NOT NULL in the
database since VF-020B4). The response field is still declared optional so
a server running this code keeps serializing rows correctly before that
migration is applied to its database; once applied it is never null.

effective_date

business date "YYYY-MM-DD" (VF-020B3); null only for history recorded
before VF-020B3 - clients display created_at for it

client_request_id

the create request's idempotency key, or null when none was sent (and for
all earlier history)

9. Receipts

Base path:

/api/v1/receipts

Endpoints

Method

Path

Success

POST

/api/v1/receipts

201

POST

/api/v1/receipts/upload

201

POST

/api/v1/receipts/{receipt_id}/process

200

POST

/api/v1/receipts/{receipt_id}/confirm

200

GET

/api/v1/receipts

200

GET

/api/v1/receipts/{receipt_id}

200

PATCH

/api/v1/receipts/{receipt_id}

200

DELETE

/api/v1/receipts/{receipt_id}

204

Receipt Status

uploaded
processing
processed
confirmed
failed

Upload Receipt

Preferred file-upload endpoint:

POST /api/v1/receipts/upload

Request type:

multipart/form-data

Form field:

file

The backend validates the file, stores it, and creates a receipt record.

Create Receipt Metadata

POST /api/v1/receipts

Request:

{
  "file_url": null,
  "storage_path": "receipts/user-id/receipt.jpg"
}

At least one of these must be provided:

file_url
storage_path

Process Receipt

POST /api/v1/receipts/{receipt_id}/process

Starts OCR processing for a stored receipt.

Allowed starting states:

uploaded
failed

Typical successful transition:

uploaded
   ↓
processing
   ↓
processed

OCR failure transitions the receipt to:

failed

Processed data may include:

ocr_text
merchant_detected
total_amount_detected
currency_detected
purchase_date_detected

Confirm Receipt

POST /api/v1/receipts/{receipt_id}/confirm

Request fields are optional corrections to OCR output, plus an optional Account link for the created expense:

{
  "category_id": null,
  "title": "LIDL",
  "amount": "24.99",
  "currency": "EUR",
  "expense_date": "2026-08-09",
  "description": "Created from receipt",
  "account_id": null
}

account_id (optional, create semantics):

omitted or null → the created expense is unlinked
UUID            → the created expense is linked to that account

The account rules are the same as for POST /api/v1/expenses with account_id:

- the account must belong to the authenticated user (otherwise 404 "Account not found.")
- the account must be active (otherwise 409 "Archived account cannot receive new transactions.")
- the account currency must exactly match the expense's final currency (otherwise 422 "Expense currency must match the account's currency to link them.")

A linked confirmation also creates the expense's debit account transaction (kind "expense", direction "debit"). The receipt stores no account reference; the response's expense.account_id reports the link.

For confirmation, the final resolved values must contain:

title
amount
currency
expense_date

Each value can come either from OCR-detected data or from the confirmation request.

Successful confirmation:

processed receipt
      ↓
create expense
      ↓
optional account debit (when account_id is set)
      ↓
link expense to receipt
      ↓
receipt status = confirmed

Expense creation, the optional account debit, and receipt confirmation are one atomic transaction: if any step fails (for example an account or FX error), no expense, no account transaction, and no receipt change are saved, and the receipt stays processed.

Confirmation locks the receipt row before checking its status, so concurrent confirmations of the same receipt are serialized: exactly one succeeds and the other is rejected as already confirmed.

Response:

{
  "receipt": {
    "...": "ReceiptResponse"
  },
  "expense": {
    "...": "ExpenseResponse"
  }
}

A confirmed receipt cannot be confirmed again.

Update Receipt

PATCH /api/v1/receipts/{receipt_id}

The current API supports partial updates to receipt metadata, status, OCR fields, and expense linkage.

At least one field is required.

If expense_id is provided, the linked expense must belong to the authenticated user.

Receipt Response

Main fields:

{
  "id": "<uuid>",
  "user_id": "<uuid>",
  "expense_id": null,
  "file_url": null,
  "storage_path": "uploads/receipts/...",
  "status": "processed",
  "ocr_text": "...",
  "merchant_detected": "LIDL",
  "total_amount_detected": "24.99",
  "currency_detected": "EUR",
  "purchase_date_detected": "2026-08-09",
  "created_at": "<datetime>",
  "updated_at": "<datetime>"
}

10. Analytics

Base path:

/api/v1/analytics

Analytics endpoints are read-only and scoped to the authenticated user.

Monthly Summary

GET /api/v1/analytics/monthly-summary?year=2026&month=8

Query parameters:

Parameter

Required

Validation

year

yes

2000–2100

month

yes

1–12

Response:

{
  "total_spent": "250.75",
  "expenses_count": 12,
  "base_currency": "EUR",
  "unresolved_expenses_count": 0
}

VF-014B5D: total_spent is BASE-currency spending, summed from each
matching Expense's already-persisted base_amount (VF-014B5C) - never the
original mixed-currency amount, and never recomputed at read time (no
amount * fx_rate here, no ECB/NBU call). base_currency is the user's
authoritative base currency (VF-014B5B), from financial_settings, not
derived from whichever Expense happens to appear first; it is still
returned with zero Expenses. expenses_count counts only resolved
Expenses (base_amount is not null) included in total_spent.
unresolved_expenses_count counts matching legacy Expenses whose FX
snapshot has not been resolved yet (base_amount is null) - these are
excluded from total_spent but are never silently treated as zero-valued;
expenses_count + unresolved_expenses_count is the total number of
matching Expenses for the period.

Category Summary

GET /api/v1/analytics/category-summary

Response item:

{
  "category_id": "<uuid-or-null>",
  "category_name": "Food",
  "total_spent": "120.50",
  "expenses_count": 5,
  "base_currency": "EUR",
  "unresolved_expenses_count": 0
}

VF-014B5D: total_spent/expenses_count/base_currency/
unresolved_expenses_count follow the same base-currency rules as Monthly
Summary above, applied per category. A category whose matching Expenses
are all unresolved is still returned (never silently omitted), with
total_spent 0, expenses_count 0, and unresolved_expenses_count > 0.

Spending Trend

GET /api/v1/analytics/spending-trend?period=month&count=6

VF-015B: a bounded historical base-currency spending time series, distinct
from Budget Status (per-Budget, original-currency, current-period-only)
and from Monthly/Category Summary (single period only). Always calculated
against the server's current date - there is no public as_of parameter.

Query parameters:

Parameter

Required

Validation

period

yes

one of "day", "week", "month"

count

no

integer >= 1; defaults to 30/12/6 for day/week/month when omitted;
rejected with 422 if it exceeds the per-period maximum: 366 (day), 104
(week), 24 (month)

Calendar boundaries: day buckets are a single date; week buckets run
Monday through Sunday; month buckets run the 1st through the last day of
the month (leap years handled correctly). The returned series always ends
with the bucket containing today, and always contains exactly `count`
buckets - a period with no Expenses is still emitted as an explicit zero
bucket (total_spent "0.00"), never omitted.

Response:

{
  "base_currency": "EUR",
  "period": "month",
  "count": 6,
  "as_of": "2026-09-17",
  "buckets": [
    {
      "period_start": "2026-04-01",
      "period_end": "2026-04-30",
      "effective_end": "2026-04-30",
      "is_complete": true,
      "total_spent": "100.00",
      "expenses_count": 2,
      "unresolved_expenses_count": 0
    }
  ],
  "period_over_period": {
    "current_period_start": "2026-08-01",
    "current_period_end": "2026-08-31",
    "previous_period_start": "2026-07-01",
    "previous_period_end": "2026-07-31",
    "current_total_spent": "150.00",
    "previous_total_spent": "100.00",
    "absolute_change": "50.00",
    "percent_change": "50.00",
    "direction": "up"
  }
}

- total_spent per bucket is BASE-currency spending, summed from each
  resolved Expense's persisted base_amount (VF-014B5C) - never the
  original mixed-currency amount, never recomputed from fx_rate. The same
  resolved/unresolved rule as Monthly/Category Summary applies per
  bucket: a legacy Expense with no FX snapshot yet, or a resolved Expense
  whose persisted base_currency no longer matches the user's current
  base_currency, is excluded from total_spent and counted in
  unresolved_expenses_count instead - never treated as zero-valued.
- effective_end = min(period_end, as_of). is_complete = period_end <
  as_of. The bucket containing today is therefore always incomplete
  until its calendar period fully elapses; a future-dated Expense can
  never appear in it.
- period_over_period compares the two most recent COMPLETE buckets in
  the returned series - never the current, in-progress bucket against a
  finished one. It is null when fewer than two complete buckets exist in
  the requested range (e.g. count=1, or a brand-new range with only the
  current period so far).
- percent_change is null when previous_total_spent is 0 - percentage
  change is mathematically undefined there, never reported as infinity,
  100, or 0. absolute_change and direction are always populated
  regardless.
- direction is "up" when absolute_change > 0, "down" when < 0,
  "unchanged" when exactly 0. This is a fixed comparison rule, not a
  "stable" threshold band - period_over_period never buckets a small
  change into "unchanged" the way a future trend-direction feature might.
- Never performs an FX/network call - reads only already-persisted
  base_amount, exactly like Monthly/Category Summary.

Category Trend

GET /api/v1/analytics/category-trend?period=month&count=6

VF-015C: bounded historical base-currency spending trends broken down by
category - Spending Trend above, split per category, with each category
getting its own bucket series and its own period_over_period comparison.
Always calculated against the server's current date - there is no public
as_of parameter.

Query parameters:

Parameter

Required

Validation

period

yes

one of "day", "week", "month"

count

no

same defaults/maximums as Spending Trend: 30/12/6 default and 366/104/24
maximum for day/week/month respectively

category_id

no

must be a category owned by the authenticated user; 404 if it does not
exist or belongs to another user (the response never distinguishes the
two cases). Omit to get every category with matching Expenses in range.
There is no separate sentinel value for Uncategorized - it is included
automatically whenever a matching Expense has category_id null.

Response:

{
  "base_currency": "EUR",
  "period": "month",
  "count": 6,
  "as_of": "2026-09-17",
  "categories": [
    {
      "category_id": "<uuid-or-null>",
      "category_name": "Food",
      "buckets": [
        {
          "period_start": "2026-04-01",
          "period_end": "2026-04-30",
          "effective_end": "2026-04-30",
          "is_complete": true,
          "total_spent": "100.00",
          "expenses_count": 2,
          "unresolved_expenses_count": 0
        }
      ],
      "period_over_period": { "...": "same shape as Spending Trend above" }
    }
  ]
}

- Bucket fields, effective_end/is_complete semantics, the resolved/
  unresolved-FX rule, and period_over_period semantics are all identical
  to Spending Trend above, applied per category instead of to the user's
  overall spending.
- categories only includes a category when it has at least one matching
  Expense in the requested range - including when every matching Expense
  is unresolved/incompatible-currency, so a category is never silently
  hidden just because none of its data has resolved yet. A category
  configured by the user but with zero Expenses anywhere in the range is
  not returned, unless category_id explicitly requested it - in that
  case it is always returned, with every bucket at "0.00".
- Uncategorized: any matching Expense with category_id null is grouped
  under category_id: null, category_name: "Uncategorized" - the same
  fallback Category Summary already uses.
- Deleted-category limitation: deleting a Category sets
  Expense.category_id to NULL (the foreign key is ON DELETE SET NULL).
  Expenses that belonged to a since-deleted category therefore appear
  under Uncategorized from that point on - there is no historical record
  of the deleted category's name, and this endpoint does not attempt to
  recover or reconstruct one.
- categories is ordered by category_name case-insensitive ascending, with
  category_id as a deterministic tie-breaker - never by spending amount.
  Ranking categories by spend is a separate, not-yet-built concern.
- Never performs an FX/network call - reads only already-persisted
  base_amount, exactly like Spending Trend.

Spending Forecast

GET /api/v1/analytics/spending-forecast

VF-015D: a deterministic projection of the authenticated user's TOTAL
base-currency spending for the CURRENT calendar month, using a simple
current-pace model. This is CURRENT-MONTH SPENDING PACE PROJECTION only -
it is not a cash-flow, income, savings, or net-worth forecast, and it
does not use previous months, seasonality, or any history at all. Takes
no query parameters - period is always the calendar month containing
today; there is no as_of, history-length, or model-selection parameter.

Response (available):

{
  "base_currency": "EUR",
  "method": "linear_run_rate",
  "forecast_status": "available",
  "period_start": "2026-09-01",
  "period_end": "2026-09-30",
  "as_of": "2026-09-17",
  "days_in_month": 30,
  "days_elapsed": 17,
  "spent_to_date": "500.00",
  "expenses_count": 8,
  "unresolved_expenses_count": 0,
  "average_daily_spending": "29.41",
  "projected_spending": "882.35"
}

Response (incomplete data):

{
  ...,
  "forecast_status": "incomplete_data",
  "average_daily_spending": null,
  "projected_spending": null
}

- method is always "linear_run_rate" today - exposed explicitly so a
  future model (e.g. a historical-baseline average) can be added later as
  an additional, separately-named option without implying today's single
  model is more sophisticated than it is. No historical/rolling-average/
  seasonal/hybrid model is implemented in VF-015D.
- Formula: average_daily_spending = spent_to_date / days_elapsed;
  projected_spending = average_daily_spending * days_in_month. Both use
  full Decimal precision internally and are quantized to money precision
  only once, separately, at the end - projected_spending is never
  computed from the already-rounded average_daily_spending value shown in
  the response (that would introduce real cent-level drift).
- days_elapsed is inclusive of today (the current, still-accumulating
  day) - a day-1-of-the-month projection is intentionally simple and can
  be volatile (a single early purchase extrapolates across the whole
  month); this is not dampened or smoothed. On the last day of the month,
  projected_spending equals spent_to_date exactly, after quantization.
- Only Expenses from the 1st of the current month through today
  (inclusive) are counted - a future-dated Expense (possible only for a
  base-currency expense; a foreign-currency one dated in the future is
  already rejected at creation) never affects the pace, and a previous
  month's Expenses are never included.
- spent_to_date sums each resolved Expense's persisted base_amount
  (VF-014B5C/B5D) directly - never the original mixed-currency amount,
  never recomputed from fx_rate. Never performs an FX/network call.
- forecast_status is "incomplete_data" - with average_daily_spending and
  projected_spending both null - when at least one matching current-month
  Expense is unresolved (base_amount is null) or persisted against an
  incompatible base_currency. A projection is never computed from known-
  incomplete monetary data, and unresolved rows are never silently
  ignored while still presenting a number. spent_to_date/expenses_count/
  unresolved_expenses_count are always populated regardless of
  forecast_status - they reflect resolved data only.
- A month with zero Expenses is "available" with spent_to_date, average_
  daily_spending, and projected_spending all "0.00" - this is a valid,
  meaningful result for a linear pace model, not an error or missing-data
  state.

Financial Overview

GET /api/v1/analytics/financial-overview?year=2026&month=9

VF-019B: Income, Expenses, Net (Income - Expenses), and savings rate for
one calendar month, in the user's base currency. The detailed rules and
decision record are in docs/modules/financial-overview.md.

Query parameters:

year   required integer, 2000..2100
month  required integer, 1..12

Out-of-range, missing, or non-integer values are 422. There is no public
as_of: "today" is always the server date.

Response:

{
  "income_total": "2500.00",
  "expense_total": "1830.40",
  "net_flow": "669.60",
  "savings_rate_percent": "26.78",
  "income_count": 2,
  "expense_count": 41,
  "unresolved_income_count": 0,
  "unresolved_expense_count": 1,
  "base_currency": "EUR",
  "period_start": "2026-09-01",
  "period_end": "2026-09-30",
  "as_of": "2026-10-02",
  "effective_end": "2026-09-30",
  "period_state": "complete",
  "data_status": "incomplete_data"
}

- Sources: only canonical Income and Expense records, Account-linked or
  not. Account ledger rows (opening balances, adjustments, and the
  projections of linked Income/Expenses), Account Transfers (planned or
  posted), and Goal contributions/withdrawals are never included, so a
  linked record is never counted twice. Income with source "refund" is
  income; it is never subtracted from Expenses.
- Dates: period_state "complete" (period_end < as_of) includes the whole
  month; "in_progress" (the month contains as_of, also on its last day)
  includes records through as_of inclusive, effective_end = as_of;
  "future" (period_start > as_of) is a valid 200 with zero totals and
  counts, savings_rate_percent null, and effective_end null.
  Future-dated records are never included. monthly-summary is unchanged
  and still counts its whole calendar month.
- Money: totals sum each resolved record's persisted base_amount snapshot
  (never the original mixed-currency amount, never re-resolved FX - reads
  make no FX/network call). All amounts are strings with two decimal
  places; an empty month is "0.00".
- net_flow = income_total - expense_total; it may be negative or zero.
  It is recorded income minus recorded expenses - NOT a bank-reconciled
  cash flow, an Account balance change, available cash, or net worth.
- savings_rate_percent = net_flow / income_total * 100, rounded to two
  decimal places with ROUND_HALF_EVEN; negative values are returned as-is
  (never clamped), and a rate that rounds to zero is "0.00", never
  "-0.00"; null exactly when income_total is zero. It is unrelated to Goal
  funding.
- A record is unresolved when base_amount is null or its snapshot
  base_currency differs from the user's base currency. It is excluded
  from its sum, counted in unresolved_income_count /
  unresolved_expense_count, and never treated as a known zero.
  data_status is "incomplete_data" when either unresolved count is
  greater than zero, otherwise "complete_data" (also for an empty month).
- income_count / expense_count count only the resolved records included
  in their totals.

Income-Expense Trend

GET /api/v1/analytics/income-expense-trend?count=6

VF-019B: the same figures as Financial Overview for `count` consecutive
calendar months, oldest first, ending with the month containing the
server's current date.

Query parameters:

count  optional integer, default 6, 1..24 (anything else, including a
       non-integer, is 422)

Response:

{
  "base_currency": "EUR",
  "as_of": "2026-10-02",
  "count": 6,
  "buckets": [
    {
      "income_total": "4500.00",
      "expense_total": "2500.00",
      "net_flow": "2000.00",
      "savings_rate_percent": "44.44",
      "income_count": 2,
      "expense_count": 30,
      "unresolved_income_count": 0,
      "unresolved_expense_count": 0,
      "period_start": "2026-05-01",
      "period_end": "2026-05-31",
      "effective_end": "2026-05-31",
      "is_complete": true
    }
  ]
}

(one bucket shown; the response always has exactly `count` buckets)

- Every month in the window is returned, including months with no
  records. No future month is ever returned.
- effective_end = min(period_end, as_of); is_complete = period_end <
  as_of, so the current month - including on its last day - is not
  complete and includes records through as_of only.
- Each bucket's figures are identical to Financial Overview's for the
  same month and date: same sources, money, savings-rate, unresolved,
  and count rules. There is no per-bucket data_status; a bucket with
  unresolved records has a non-zero unresolved count.

Budget Status

GET /api/v1/analytics/budget-status

Always calculated against the server's current date - there is no public
as_of parameter. Historical/arbitrary-date period browsing is intentionally
out of scope for VF-014B3 and belongs to VF-015's own, deliberately
designed API.

Status is calculated against the budget's current calendar period (VF-014B2/
B3): limit_amount and category_id are resolved from the BudgetVersion
applicable to that period, not necessarily the budget's live values, and
spent only counts same-currency expenses within the effective window.

VF-014B4 adds deterministic current-period pace metrics (days_in_period
through risk_status below). These are a simple linear projection over the
CURRENT period only - no previous periods, no moving averages, no
spending-pattern history. A large recurring expense early in a period can
make the projection overreact; improving that with historical data is
deliberately deferred to VF-015 Analytics & Forecasting v2.

- days_remaining includes today for an active budget
  (days_in_period - days_elapsed + 1) - today is both an elapsed day and
  still a day the user may spend on.
- projected_spending = (spent / days_elapsed) * days_in_period for an
  active budget, never capped at limit_amount; equals spent once a period
  has ended; null while not yet started (no observed pace exists yet) -
  projected_surplus/projected_deficit are null exactly when this is null.
- risk_status: "exceeded" whenever spent > limit_amount, regardless of
  lifecycle state; otherwise "healthy" for not_started/ended; for an
  active budget, projected utilization <=90% is "healthy", >90-100% is
  "watch", and >100% is "at_risk" (a fixed product rule, not a
  statistical model - 90.00% exactly is healthy, 100.00% exactly is watch).

Response item:

{
  "budget_id": "<uuid>",
  "budget_name": "Monthly groceries",
  "category_id": "<uuid-or-null>",
  "category_name": "Food",
  "period": "monthly",
  "period_start": "2026-09-01",
  "period_end": "2026-09-30",
  "effective_start": "2026-09-01",
  "effective_end": "2026-09-30",
  "period_state": "active",
  "is_partial_period": false,
  "limit_amount": "400.00",
  "spent": "250.00",
  "remaining": "150.00",
  "exceeded_amount": "0.00",
  "utilization_percent": "62.50",
  "is_exceeded": false,
  "days_in_period": 30,
  "days_elapsed": 16,
  "days_remaining": 15,
  "average_daily_spending": "15.63",
  "daily_spending_allowance": "10.00",
  "projected_spending": "468.75",
  "projected_surplus": "0.00",
  "projected_deficit": "68.75",
  "risk_status": "watch"
}

Goal Progress

GET /api/v1/analytics/goal-progress

current_amount here is ledger-derived (VF-016D), the same as every other
Goal read - see the Goals section's "Balance source" note. remaining_amount
is floored at 0; progress_percent is never capped at 100 - an overfunded
goal (current_amount > target_amount) reports progress_percent above 100.

Response item:

{
  "goal_id": "<uuid>",
  "name": "Vacation",
  "target_amount": "2000.00",
  "current_amount": "500.00",
  "remaining_amount": "1500.00",
  "progress_percent": "25.00",
  "status": "active",
  "target_date": "2026-12-31"
}

11. Accounts

Base path:

/api/v1/accounts

Endpoints

Method

Path

Success

POST

/api/v1/accounts

201

GET

/api/v1/accounts

200

PATCH

/api/v1/accounts/{account_id}

200

DELETE

/api/v1/accounts/{account_id}

204

POST

/api/v1/accounts/{account_id}/transactions

201

GET

/api/v1/accounts/{account_id}/transactions

200

An Account represents where real money is held - checking, savings, or
cash. Credit cards, debt/liability accounts, investment accounts, and
Goal <-> Account movement are not implemented. Income and Expense can
optionally be linked to an Account (VF-017D / VF-017E) - see the Income
and Expenses sections. Moving money between two of the user's Accounts
is a separate resource - see 11.1 Account Transfers. There is no
GET /api/v1/accounts/{account_id} endpoint - mobile detail screens
resolve a single account from the list response, matching the
established Goals pattern.

Account != Budget: a Budget is a spending limit/allocation and has no
relationship to Account cash, now or in any future slice. Whether an
Expense is linked to an Account never changes how it feeds Budget
analytics.

Balance model: current_balance is READ-ONLY on every Account endpoint. It
is not accepted by POST /api/v1/accounts or PATCH
/api/v1/accounts/{account_id} - sending it is rejected (extra fields are
forbidden). current_balance is computed at read time from the
account_transactions ledger (SUM of credit amounts minus debit amounts) -
the Account row has no balance column at all, matching the Goal ledger
architecture. Unlike Goal.current_amount, current_balance has NO floor:
an Account is a descriptive financial record, not a payment-authorization
system, so a debit larger than the current balance is always allowed and
the resulting balance may be negative, zero, or positive.

Opening balance: a real pre-existing account is onboarded by sending an
optional signed opening_balance (and optional opening_balance_date) on
POST /api/v1/accounts. A positive value creates one immutable credit
opening_balance transaction; a negative value creates one immutable debit
opening_balance transaction (the stored ledger amount itself is always
positive - direction carries the sign); omitted or exactly 0 creates no
transaction at all. The Account row and its opening_balance transaction
are created atomically in one database transaction. opening_balance is
create-input only - it is never returned as an Account field, and at most
one opening_balance transaction can ever exist per account.

Manual adjustments: POST /api/v1/accounts/{account_id}/transactions
accepts only direction, amount, transaction_date, and an optional
description - there is no kind field on this request at all. The backend
always creates kind="adjustment"; opening_balance is unreachable through
this endpoint (it is created exactly once, atomically, via
POST /api/v1/accounts). There is no PATCH or DELETE endpoint for an
individual account transaction: every direct transaction (opening_balance
and adjustment) is immutable once created. Corrections are made with a
compensating adjustment, never an edit.

Lifecycle rules:

Currency is editable only while an Account has no transaction history.
Once any AccountTransaction exists, an actual currency change is
rejected with 409 ("Account currency cannot be changed after transaction
history exists."). Resending the account's current currency (any casing)
is a no-op and is always allowed, even with history.

An Account with no transaction history deletes normally (204). An
Account with any transaction history cannot be deleted (409, "Account
with transaction history cannot be deleted. Archive it instead.") -
archive it instead via PATCH status="archived".

An Account referenced by any planned Account Transfer (VF-018C) cannot
be deleted and cannot actually change currency - both are rejected with
409 ("Account is referenced by planned transfers. Delete them first.").
A planned transfer has no ledger rows, so the transaction-history rules
above do not see it. Resending the same currency and archiving remain
allowed. An Account referenced by a posted transfer already has ledger
history, so the history rules above apply to it.

Archiving (PATCH status="archived") remains possible regardless of
transaction history or planned transfers, and an archived account's
balance and full history remain fully readable. A new manual adjustment into an archived account
is rejected with 409 ("Archived account cannot receive new
transactions."). Reactivating (PATCH status="active") allows new
adjustments again.

Create Account

POST /api/v1/accounts

Request:

{
  "name": "Main Checking",
  "type": "checking",
  "currency": "EUR",
  "opening_balance": "1000.00",
  "opening_balance_date": "2026-09-23"
}

Fields:

Field

Required

Notes

name

yes

1-120 characters, trimmed

type

yes

checking, savings, or cash

currency

no

default EUR; normalized to uppercase, 3 alphabetic characters

status

no

active or archived; default active

opening_balance

no

signed Decimal; converted into one immutable opening_balance ledger
transaction, never persisted as a field

opening_balance_date

no

defaults to today when opening_balance is non-zero and this is omitted

Account Response

Returns the account fields plus:

id
user_id
current_balance
created_at
updated_at

current_balance is always ledger-derived, never read from a stored
column, and may be negative.

Goal reservation read model (VF-020C2), read-only, on every Account
response (list, create, PATCH). D is the server date, resolved once per
request; all values are signed Decimal strings with two places and are
derived from SQL aggregates (no floats, no currency conversion):

balance_as_of_today - signed ledger sum of rows with transaction_date <= D.

scheduled_outflows - positive sum of debit rows with transaction_date > D.
Future credits are ignored (money that has not arrived is not reservable).

planned_transfer_outflows - sum of the amounts of planned AccountTransfers
whose source is this Account, whatever their planned_date. Posted transfers
are already in the ledger; planned incoming transfers add nothing.

reserved_amount - linked Goal contributions minus linked withdrawals over
all of the user's Goals (archived included).

unallocated_amount - balance_as_of_today - reserved_amount.

reservable_amount - unallocated_amount - scheduled_outflows -
planned_transfer_outflows (may be negative). A new reservation requires it
to be positive and at least the requested amount.

allocation_status - "overcommitted" when reserved_amount > 0 and
unallocated_amount < 0 (money was spent after it was reserved; existing
reservations are never rewritten), otherwise "normal".

negative_balance - true when balance_as_of_today < 0.

current_balance keeps its meaning (the whole ledger, future rows included).

Account delete and currency change (VF-020C2): an Account that any Goal
transaction was ever linked to cannot be deleted and its currency cannot be
actually changed - 409 "Account is referenced by Goal reservations and
cannot be deleted or have its currency changed." - even when the net
reservation is zero and whether or not the Goal is archived. Existing
errors keep precedence: ledger history first, then linked Goal history,
then planned transfers. A same-currency resend is a no-op. The database
foreign key (RESTRICT) is the backstop and surfaces as the same 409.

Account Transaction Response

{
  "id": "<uuid>",
  "account_id": "<uuid>",
  "user_id": "<uuid>",
  "kind": "adjustment",
  "direction": "credit",
  "amount": "50.00",
  "transaction_date": "2026-09-23",
  "description": null,
  "income_id": null,
  "expense_id": null,
  "transfer_id": null,
  "counterparty_account_id": null,
  "created_at": "2026-09-23T10:00:00Z"
}

`kind` is one of `opening_balance`, `adjustment`, `income`, `expense`,
or `transfer` (VF-017D added `income`, VF-017E `expense`, VF-018B/C
`transfer` - each an additive change to this Literal; clients that
switch exhaustively on `kind` must be updated to tolerate each new
value, it is not claimed to be transparent for every possible client).
`transfer_id` is non-null only on a `kind="transfer"` row - one of the
two projections of a posted Account Transfer (see 11.1) - and
`counterparty_account_id` is non-null only on such a row: the transfer's
destination Account on the source Account's debit row, and its source
Account on the destination Account's credit row. It is derived from the
transfer at read time, never stored. Planned transfers never appear in
Account history. `income_id` is non-null only on
a `kind="income"` row, and identifies the source Income this row is a
synchronized projection of. `expense_id` is non-null only on a
`kind="expense"` row, and identifies the source Expense this row is a
synchronized projection of. Both are null on every direct
`opening_balance`/`adjustment` row, and a row can never have both set at
once. There is still no PATCH/DELETE endpoint for an individual
transaction, for direct, Income-backed, or Expense-backed rows: an
`income`-kind row can be created/updated/deleted ONLY as a side effect
of the corresponding Income create/PATCH/DELETE (see the Income section
below), and an `expense`-kind row ONLY as a side effect of the
corresponding Expense create/PATCH/DELETE (see the Expenses section
above) - direct rows remain immutable exactly as before. A
`transfer`-kind row is created only by posting an Account Transfer and
removed only by deleting that transfer (see 11.1).

Transaction history is returned newest first, ordered by
transaction_date DESC, then created_at DESC, then id DESC for
deterministic output.

11.1 Account Transfers

Base path:

/api/v1/account-transfers

Endpoints

Method

Path

Success

POST

/api/v1/account-transfers

201 (created) or 200 (idempotent replay)

GET

/api/v1/account-transfers

200

DELETE

/api/v1/account-transfers/{transfer_id}

204

POST

/api/v1/account-transfers/{transfer_id}/post

200

An Account Transfer moves the user's own money from one of their
Accounts to another, in the same currency. It is not Income or Expense:
transfers never create Income/Expense rows and never affect expense-based
analytics or budgets. The approved domain contract is
docs/modules/account-transfers.md.

There is no GET /api/v1/account-transfers/{transfer_id} (clients resolve
a transfer from the list) and no PATCH (a correction is delete + create).
There is no automatic scheduler: a planned transfer stays planned until
it is posted manually (see Post Transfer below).

Lifecycle:

planned - an expected future transfer. It has no ledger rows, never
affects current Account balances, and does not appear in Account
history.

posted - a transfer that happened. It has exactly two ledger rows: a
debit on the source Account and a credit on the destination Account,
both dated effective_date (see Account Transaction Response above).

Create Transfer

POST /api/v1/account-transfers

Request:

{
  "client_request_id": "0f8c5f5e-6a38-4a8e-9b0e-2f7d0a6f1c11",
  "source_account_id": "<uuid>",
  "destination_account_id": "<uuid>",
  "amount": "300.00",
  "transfer_date": "2026-10-15",
  "description": "Move to savings"
}

Fields:

Field

Required

Notes

client_request_id

yes

UUID generated by the client; the create idempotency key (see below)

source_account_id

yes

Account the money leaves

destination_account_id

yes

Account the money enters; must differ from source_account_id (422)

amount

yes

Decimal > 0, max 12 digits, 2 decimal places (max 9999999999.99)

transfer_date

yes

date; classified by the server as described below

description

no

max 500 characters; stored as sent (no normalization)

user_id, currency, status, planned_date, effective_date, posted_at, and
kind are server-owned: sending any of them is rejected with 422 (extra
fields are forbidden). currency is derived from the Accounts.

Date classification (server date; not yet user-timezone aware):

transfer_date <= today - created as posted: planned_date = null,
effective_date = transfer_date, posted_at = now, and both ledger rows
are created in the same database transaction.

transfer_date > today - created as planned: planned_date =
transfer_date, effective_date = null, posted_at = null, no ledger rows.

Validation for a new transfer (both Accounts are locked first):

404 "Account not found." - either Account is missing or belongs to
another user (no existence is leaked).

409 "Archived account cannot receive new transactions." - either Account
is archived.

422 "Transfer source and destination accounts must use the same
currency." - the Accounts' currencies differ (no FX transfers).

There is no insufficient-funds check: a posted transfer may make the
source balance negative.

Idempotency:

201 - this request created a new transfer.

200 - client_request_id already identifies a transfer created from the
same payload (source, destination, amount compared as a decimal value so
"300" equals "300.00", original transfer_date, description compared
exactly). The transfer's CURRENT state is returned and nothing new is
created. Current Account state is not re-validated on a replay: if an
Account was archived after the original create, the replay still
returns 200.

409 "client_request_id has already been used for a different
transfer." - the same key with any different payload. The existing
transfer is not revealed.

Concurrent duplicate requests with the same key never create two
transfers: the database enforces UNIQUE(user_id, client_request_id) and
the losing request is resolved as 200 or 409 as above. After a transfer
is hard-deleted its client_request_id is free again, so reusing it
creates a new transfer (accepted MVP behavior).

Response (201 or 200):

{
  "id": "<uuid>",
  "user_id": "<uuid>",
  "client_request_id": "<uuid>",
  "source_account_id": "<uuid>",
  "destination_account_id": "<uuid>",
  "amount": "300.00",
  "currency": "EUR",
  "status": "planned",
  "planned_date": "2026-10-15",
  "effective_date": null,
  "description": "Move to savings",
  "posted_at": null,
  "created_at": "2026-09-29T10:00:00Z",
  "updated_at": "2026-09-29T10:00:00Z"
}

There is no transfer_date response field.

List Transfers

GET /api/v1/account-transfers

Returns the user's planned and posted transfers, ordered by the
transfer's own date - effective_date once posted, otherwise
planned_date - descending, then created_at DESC, then id DESC. No
filters or pagination. A planned transfer whose planned_date has passed
is returned as stored (still planned).

Post Transfer

POST /api/v1/account-transfers/{transfer_id}/post

Manually moves a planned transfer to posted (VF-018D). Success is 200
with the transfer's posted state.

Request body (optional):

{
  "effective_date": "2026-10-18"
}

The body may be omitted entirely, sent as {}, or carry effective_date
(null is treated as omitted). Any other field is rejected with 422.

effective_date is the accounting date on which the money actually moved;
it becomes the transaction_date of both ledger rows. When omitted it is
the server date. It may be before, on, or after the transfer's
planned_date - there is no "not yet due" rule - but never in the future.

Rules, in this order:

422 "Transfer effective date cannot be in the future." - effective_date
is after the server date. This is checked BEFORE the transfer is looked
up, so it takes precedence over 404/409 (even for a missing transfer).

404 "Account transfer not found." - missing or another user's transfer.

409 "Account transfer has already been posted." - the transfer is not
planned. Posting happens at most once and is not idempotent: a retried
post (e.g. after a lost response) gets 409, and the client refetches the
list to see the posted state. There is no client_request_id for posting.

409 "Archived account cannot receive new transactions." - the source or
destination Account is archived. The transfer stays planned with no
ledger rows; it can still be deleted, or posted after the Account is
reactivated.

On success, in one database transaction: status becomes posted,
effective_date and posted_at are set, planned_date keeps its original
value, and exactly two ledger rows are created (debit on the source
Account, credit on the destination Account). There is no insufficient-
funds check. Replaying the original create request of a transfer that was
posted this way returns 200 with its current posted state.

Delete Transfer

DELETE /api/v1/account-transfers/{transfer_id}

Hard delete, 204. A planned transfer is removed with no ledger effect. A
posted transfer is removed together with both of its ledger rows, so its
effect on both Account balances disappears. Archived Accounts never block
deletion. A missing or another user's transfer is 404 ("Account transfer
not found."). There is no reversal entry and no audit record of a
deleted transfer.

12. Income

Base path:

/api/v1/income

Endpoints

Method

Path

Success

POST

/api/v1/income

201

GET

/api/v1/income

200

PATCH

/api/v1/income/{income_id}

200

DELETE

/api/v1/income/{income_id}

204

Income represents money the user received - salary, freelance payment,
refund, gift, or other. There is no GET /api/v1/income/{income_id}
endpoint, matching the Goals/Accounts pattern. Income does not have its
own category - the `source` field (see below) is the only classification
this domain provides.

Account linkage (VF-017D): Income may optionally be linked to an
Account via `account_id` on POST/PATCH. Income remains the canonical
record - linking it creates a synchronized AccountTransaction ledger
projection (kind="income", direction="credit") in the linked Account,
which is how that Account's balance comes to reflect it (Account
balance is always SUM(credits) - SUM(debits) over its
account_transactions rows - see the Accounts section above). `account_id`
has NO database column on income at all: the value returned on
IncomeResponse is derived from that projection at read time, never
persisted on the Income row itself. Linking is allowed only when
Income.currency exactly matches Account.currency (after normalization) -
there is no FX conversion between Income and Account; Income's own
base-currency FX snapshot (below) is a completely separate, unrelated
concern untouched by linking.

Source values (closed set, DB-enforced via CHECK):

salary
freelance
refund
gift
other

FX snapshot model: base_amount, base_currency, fx_rate, fx_rate_date, and
fx_source are READ-ONLY on every Income endpoint - sending any of them on
POST /api/v1/income or PATCH /api/v1/income/{income_id} is rejected
(extra fields are forbidden). They reuse the exact same FX architecture
Expense already established (VF-014B5C): at create/update time, the
service resolves `currency` + `amount` + `received_at` into a historical
FX snapshot via the shared fx_service/financial_settings infrastructure
and persists it - analytics/read paths never recompute FX. When
`currency` equals the user's base currency, this resolves instantly and
deterministically to base_amount = amount, fx_rate = 1, fx_source =
"identity" (no network call). A foreign currency resolves the historical
official rate in effect on received_at, using the same bounded-lookback
provider logic Expense already uses. There is no legacy-unresolved case
for Income (unlike Expense, which has pre-FX rows): every Income row
always has a complete snapshot.

Future-dated foreign income: a foreign-currency Income dated after today
is rejected with 422 and the message "A foreign-currency income cannot be
dated in the future." - a distinct message from Expense's own
"A foreign-currency expense cannot be dated in the future.", both mapped
from their own domain-specific error class even though the underlying FX
resolution logic that detects this condition is fully shared,
unduplicated code. A future-dated identity (base-currency) income is
accepted - the future-date restriction only protects historical rate
lookups, which an identity conversion never needs.

PATCH FX re-resolution rules: when amount, currency, or received_at is
present in the request, the FX snapshot is recomputed - amount alone
reuses the existing resolved rate (only base_amount is recomputed);
currency and/or received_at changing triggers a full fresh resolution.
When only source and/or description change, the existing snapshot is
copied unchanged and the FX provider is never called.

Create Income

POST /api/v1/income

Request:

{
  "amount": "2500.00",
  "currency": "EUR",
  "received_at": "2026-09-23",
  "source": "salary",
  "description": "September salary",
  "account_id": null
}

Fields:

Field

Required

Notes

amount

yes

greater than 0

currency

no

default EUR; normalized to uppercase, 3 alphabetic characters

received_at

yes

date the money was actually received

source

yes

salary, freelance, refund, gift, or other

description

no

optional free-text note, up to 500 characters

account_id

no

optional Account to link this Income to; the Account must belong to the
authenticated user, must not be archived, and its currency must exactly
match this Income's currency

Update Income

PATCH /api/v1/income/{income_id}

`account_id` has three-state PATCH semantics, matching the existing
Expense.category_id convention exactly: absent from the request leaves
the current linkage untouched; a UUID attaches (if currently unlinked)
or moves (if already linked elsewhere); explicit `null` detaches. The
PATCH is evaluated against its FINAL resulting state, not field-by-field
in isolation - e.g. changing `currency` and `account_id` together in one
request is validated against the combination that results, so an
EUR Income on an EUR Account can move to a USD Account while also
changing to USD in the same request, as long as the final currency
matches the final Account. There is no silent auto-detach: a currency
change that would leave the Income linked to a now-mismatched Account is
rejected outright (422), never resolved by detaching on the client's
behalf.

Archived-Account rule: rejected only when the PATCH would add NEW
activity to an Account - attaching, or moving INTO an archived Account
(409, the existing "Archived account cannot receive new transactions."
message). Amount/received_at corrections to an Income already linked to
an Account that was archived afterward are allowed (this is maintaining
existing history, not new activity), as is detaching from, deleting from,
or moving OUT of an archived Account.

Income Response

Returns the income fields plus:

id
user_id
account_id
base_amount
base_currency
fx_rate
fx_rate_date
fx_source
created_at
updated_at

account_id is read-only and fully derived (VF-017D): Income has no
account_id database column at all, so this value is resolved from the
AccountTransaction projection at read time - null means unlinked.

base_amount/base_currency/fx_rate/fx_rate_date/fx_source are backend-
derived from the persisted historical FX snapshot at write time,
read-only, and never accepted as input. They are resolved and persisted
once at create/update time; read paths (GET /income, GET /income/{id}
equivalents) never recompute FX. This snapshot is unrelated to Account
linkage - "ledger-derived" describes Goal/Account balances (computed by
summing many rows); Income's own amount/currency are never revalued
through the Account link, only through this independent FX mechanism.

Income feeds analytics only through the dedicated VF-019B endpoints
GET /api/v1/analytics/financial-overview and
GET /api/v1/analytics/income-expense-trend (see Analytics), which sum the
persisted base_amount snapshots described above. Every pre-existing
analytics endpoint - including the Spending Forecast, which remains
expense-only and "never a cash-flow/income/savings/net-worth forecast" -
is unchanged: income-aware analytics were added as new endpoints, not as
a silent change to what any existing endpoint's numbers mean. There is
still no cash-flow reconciliation or net-worth surface.

13. Error Contract

Domain errors use a consistent JSON shape:

{
  "detail": "Human-readable error message."
}

Authentication

Typical authentication responses:

Status

Meaning

401

missing, invalid, or expired authentication

500

Supabase authentication configuration is missing

503

Supabase Auth is unavailable or returned an invalid response

Resource and Business Errors

Status

Typical Meaning

400

invalid business state/value

404

requested user-owned resource not found

409

duplicate resource or forbidden state transition

413

receipt file too large

415

unsupported receipt file type

422

request validation or receipt processing/confirmation data error

500

receipt file storage failure

Important current domain mappings include:

404  Category not found.
404  Expense not found.
404  Budget not found.
404  Goal not found.
404  Account not found.
404  Account transfer not found.
404  Income not found.
404  Receipt not found.
404  Linked expense not found.
404  Receipt file not found.

409  Category with this name already exists for this user.
409  Default category cannot be modified.
409  Default category cannot be deleted.
409  Budget with this name, period, and start date already exists for this user.
409  Account currency cannot be changed after transaction history exists.
409  Account with transaction history cannot be deleted. Archive it instead.
409  Archived account cannot receive new transactions.
409  Account is referenced by planned transfers. Delete them first.
409  client_request_id has already been used for a different transfer.
409  Account transfer has already been posted.
409  Receipt cannot be processed in its current status.
409  Receipt cannot be confirmed in its current status.
409  Receipt has already been confirmed.

413  Receipt file is too large.
415  Receipt file type is not supported.

422  A foreign-currency income cannot be dated in the future.
422  Income currency must match the account's currency to link them.
422  Expense currency must match the account's currency to link them.
422  Transfer source and destination accounts must use the same currency.
422  Transfer effective date cannot be in the future.
422  Receipt file is empty.
422  Receipt OCR processing failed.
422  Required receipt confirmation data is missing.

500  Receipt file could not be stored.

Pydantic/FastAPI request validation errors also return HTTP 422.

14. Client Integration Rules

Web and mobile clients should follow these rules:

Authenticate first and send authentication data on protected requests.

Never send or trust client-controlled user_id.

Treat UUIDs as opaque identifiers.

Use PATCH for partial resource updates.

Handle 401, 404, 409, and 422 explicitly in the UI.

Do not assume OCR output is final; confirmation may correct detected values.

Do not create a second expense after successful receipt confirmation.

Use /docs as the detailed runtime schema reference.

15. Contract Source of Truth

The public contract is defined by:

FastAPI routers
        +
Pydantic schemas
        +
domain error mappings

Interactive generated documentation:

/docs

OpenAPI schema:

/openapi.json

When an endpoint, request schema, response schema, or public error changes, this document should be updated in the same feature change.