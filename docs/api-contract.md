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

3 characters, default EUR

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
  "created_at": "<datetime>",
  "updated_at": "<datetime>"
}

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

Create Goal

POST /api/v1/goals

Request:

{
  "name": "Vacation",
  "target_amount": "2000.00",
  "current_amount": "500.00",
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

current_amount

no

non-negative, default 0

currency

no

default EUR; normalized to uppercase

target_date

no

optional date

status

no

active, completed, archived; default active

Business rule:

current_amount <= target_amount

Update Goal

PATCH /api/v1/goals/{goal_id}

At least one field is required.

target_date may be set to null.

The final goal state must satisfy the amount rule.

Goal Response

Returns the goal fields plus:

id
user_id
created_at
updated_at

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
  "expenses_count": 12
}

Category Summary

GET /api/v1/analytics/category-summary

Response item:

{
  "category_id": "<uuid-or-null>",
  "category_name": "Food",
  "total_spent": "120.50",
  "expenses_count": 5
}

Budget Status

GET /api/v1/analytics/budget-status

Response item:

{
  "budget_id": "<uuid>",
  "budget_name": "Monthly groceries",
  "category_id": "<uuid-or-null>",
  "category_name": "Food",
  "limit_amount": "400.00",
  "spent": "250.00",
  "remaining": "150.00",
  "exceeded_amount": "0.00",
  "is_exceeded": false
}

Goal Progress

GET /api/v1/analytics/goal-progress

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