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
  "source": "manual"
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

must be greater than 0

currency

no

3 characters, default EUR. Normalized to uppercase; must be exactly 3
alphabetic characters.

expense_date

yes

date

description

no

optional

source

no

max 30 characters, default manual

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

category_id may be set to null to make the expense uncategorized.

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
  "base_amount": "35.50",
  "base_currency": "EUR",
  "fx_rate": "1.00000000",
  "fx_rate_date": "2026-08-09",
  "fx_source": "identity",
  "created_at": "<datetime>",
  "updated_at": "<datetime>"
}

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

Balance source (VF-016D): every current_amount value returned by this API
- from POST /api/v1/goals, GET /api/v1/goals, PATCH /api/v1/goals/{goal_id},
and GET /api/v1/analytics/goal-progress - is computed directly from the
goal_transactions ledger at read time (opening_balance + contribution -
withdrawal), never read from the goals.current_amount database column.
goals.current_amount still physically exists and is still kept in sync by
every transaction write, but it is transitional compatibility storage
only: no read path trusts it, and a future cleanup migration will remove
it once it is no longer needed for rollback safety.

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

default EUR; normalized to uppercase

target_date

no

optional date

status

no

active, completed, archived; default active; never auto-derived

Every new Goal is created with current_amount = 0.00. Sending
current_amount in this request is rejected (422).

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
exists because GoalTransaction rows do not store their own currency:
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
computed from the goal_transactions ledger as described above - never
read from the transitional column. It may exceed target_amount -
overfunding is a valid, representable state.

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
  "description": "Payday transfer"
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

Business rules:

A Goal's balance can never become negative: a withdrawal whose amount
exceeds the Goal's current ledger-derived balance is rejected with 409
Conflict ("Withdrawal exceeds the current goal balance.").

Overfunding above target_amount is allowed for contributions - there is no
upper bound on a Goal's balance.

Every write locks the owned Goal row (SELECT ... FOR UPDATE) before
calculating the balance from transaction history, so two concurrent
requests against the same Goal are serialized and can never both validate
against the same stale balance.

Transactions are append-only: there is no PATCH or DELETE for an existing
transaction. A correction is represented later by a new, opposite
transaction (a compensating entry), never by editing history.

Response: 201 with the created transaction (see Goal Transaction Response
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

Request fields are optional corrections to OCR output:

{
  "category_id": null,
  "title": "LIDL",
  "amount": "24.99",
  "currency": "EUR",
  "expense_date": "2026-08-09",
  "description": "Created from receipt"
}

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
link expense to receipt
      ↓
receipt status = confirmed

Expense creation and receipt confirmation are atomic.

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

11. Error Contract

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
404  Receipt not found.
404  Linked expense not found.
404  Receipt file not found.

409  Category with this name already exists for this user.
409  Default category cannot be modified.
409  Default category cannot be deleted.
409  Budget with this name, period, and start date already exists for this user.
409  Receipt cannot be processed in its current status.
409  Receipt cannot be confirmed in its current status.
409  Receipt has already been confirmed.

413  Receipt file is too large.
415  Receipt file type is not supported.

422  Receipt file is empty.
422  Receipt OCR processing failed.
422  Required receipt confirmation data is missing.

500  Receipt file could not be stored.

Pydantic/FastAPI request validation errors also return HTTP 422.

12. Client Integration Rules

Web and mobile clients should follow these rules:

Authenticate first and send authentication data on protected requests.

Never send or trust client-controlled user_id.

Treat UUIDs as opaque identifiers.

Use PATCH for partial resource updates.

Handle 401, 404, 409, and 422 explicitly in the UI.

Do not assume OCR output is final; confirmation may correct detected values.

Do not create a second expense after successful receipt confirmation.

Use /docs as the detailed runtime schema reference.

13. Contract Source of Truth

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