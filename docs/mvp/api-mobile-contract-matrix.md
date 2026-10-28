# API-to-Mobile Contract Matrix (VF-MVP-ENG-001, Part 5)

Date: 2026-10-27. Basis: `main` @ `08d985c030a38823fe43863c806d90bbc86e97b4`.
Authority: the OpenAPI document produced by `app.openapi()` and the routers, schemas and
`app/core/exception_handlers.py`. The written contract (`docs/api-contract.md`, `docs/modules/smart-goals-rules.md`)
was compared against it; differences are in section 4. No endpoint in this document is invented: every row
exists in OpenAPI (67 operations under `/api/v1`, plus `GET /` and `GET /health`).

## 1. Cross-cutting behavior

| Topic | Actual behavior |
|---|---|
| Authentication | `Authorization: Bearer <Supabase JWT>`; user id from the token. `AUTH_MODE=development` with `X-User-Id` is local/test only. |
| Ownership | Every read/update/delete is scoped by the authenticated user. A foreign id returns the same 404 as a missing id. No payload accepts `user_id`. |
| Error body | `{"detail": "<English text>"}` for domain errors (status 404, 409, 413, 415, 422, 500, 503). FastAPI validation errors: 422 `{"detail": [ {loc, msg, type}, … ]}`. **No machine-readable code.** Rule-field validation: 422 `{"detail": "<message>"}` (`FinancialRuleInvalidFieldsError`). |
| Money | Responses: decimal strings. Requests: number or string. Never `float` on the backend. Preserve strings in the client. |
| Dates | `YYYY-MM-DD`. "Today" is the **server** date. |
| Pagination | **Only** `rule-executions`, `rule-proposals`, `rule-alerts`: `limit` (default 20, 1–100), `offset`; response `{items,total,limit,offset}`. Everything else returns the full unpaginated set. |
| Single-object reads | No `GET /{id}` for Accounts, Income, Transfers, Goals, Budgets, Expenses. Categories, Receipts, Financial Rules, Rule Proposals have one. Mobile resolves objects from list caches. |
| Idempotency | Client keys: Goal transactions (`client_request_id`, required when `account_id` is set; 201 created / 200 replay) and Account transfer create (`client_request_id` required; 201 / 200). State-based: proposal confirm/reject on a terminal proposal (HTTP 200 + stored state), alert acknowledge (first time kept), `POST /financial-rules/evaluate` (idempotent), goal priorities (full-state replace). **None:** Expense, Income, Account transaction, Budget, Category, Rule create, Receipt confirm (guarded by status 409), enable/pause/disable (409 invalid transition on repeat). |
| Client | One wrapper `apiRequest`; token attached; no timeout; no 401 handling; thrown `Error("API request failed: <status> <body>")` parsed by `getApiErrorMessage`. |

## 2. Endpoint inventory (generated from OpenAPI)

"Mobile uses" = a call to this method and path exists in `apps/mobile/src/features/*/*.service.ts`. 47 of 67
operations are used; the 20 unused are exactly: all 9 `financial-rules`, 4 `rule-proposals`, 2 `rule-alerts`,
1 `rule-executions`, and 4 `receipts` operations (`POST /receipts`, `GET /receipts`, `PATCH`, `DELETE`).

### account-transfers

| Method | Endpoint | Request | Response | Query | Mobile uses |
|---|---|---|---|---|---|
| POST | `/api/v1/account-transfers` | `AccountTransferCreate` | 201 `AccountTransferResponse` | - | yes |
| GET | `/api/v1/account-transfers` | - | 200 `[AccountTransferResponse]` | - | yes |
| DELETE | `/api/v1/account-transfers/{transfer_id}` | - | 204 no body | - | yes |
| POST | `/api/v1/account-transfers/{transfer_id}/post` | `AccountTransferPost` (optional body) | 200 `AccountTransferResponse` | - | yes |

### accounts

| Method | Endpoint | Request | Response | Query | Mobile uses |
|---|---|---|---|---|---|
| POST | `/api/v1/accounts` | `AccountCreate` | 201 `AccountResponse` | - | yes |
| GET | `/api/v1/accounts` | - | 200 `[AccountResponse]` | - | yes |
| PATCH | `/api/v1/accounts/{account_id}` | `AccountUpdate` | 200 `AccountResponse` | - | yes |
| DELETE | `/api/v1/accounts/{account_id}` | - | 204 no body | - | yes |
| POST | `/api/v1/accounts/{account_id}/transactions` | `AccountTransactionCreate` | 201 `AccountTransactionResponse` | - | yes |
| GET | `/api/v1/accounts/{account_id}/transactions` | - | 200 `[AccountTransactionResponse]` | - | yes |

### analytics

| Method | Endpoint | Request | Response | Query | Mobile uses |
|---|---|---|---|---|---|
| GET | `/api/v1/analytics/budget-status` | - | 200 `[BudgetStatusItem]` | - | yes |
| GET | `/api/v1/analytics/category-summary` | - | 200 `[CategorySummaryItem]` | year,month | yes |
| GET | `/api/v1/analytics/category-trend` | - | 200 `CategoryTrendResponse` | period,count,category_id | yes |
| GET | `/api/v1/analytics/financial-overview` | - | 200 `FinancialOverviewResponse` | year,month | yes |
| GET | `/api/v1/analytics/goal-progress` | - | 200 `[GoalProgressItem]` | - | yes |
| GET | `/api/v1/analytics/income-expense-trend` | - | 200 `IncomeExpenseTrendResponse` | count | yes |
| GET | `/api/v1/analytics/monthly-summary` | - | 200 `MonthlySummaryResponse` | year,month | yes |
| GET | `/api/v1/analytics/spending-forecast` | - | 200 `SpendingForecastResponse` | - | yes |
| GET | `/api/v1/analytics/spending-trend` | - | 200 `SpendingTrendResponse` | period,count | yes |

### budgets

| Method | Endpoint | Request | Response | Query | Mobile uses |
|---|---|---|---|---|---|
| POST | `/api/v1/budgets` | `BudgetCreate` | 201 `BudgetResponse` | - | yes |
| GET | `/api/v1/budgets` | - | 200 `[BudgetResponse]` | - | yes |
| PATCH | `/api/v1/budgets/{budget_id}` | `BudgetUpdate` | 200 `BudgetResponse` | - | yes |
| DELETE | `/api/v1/budgets/{budget_id}` | - | 204 no body | - | yes |

### categories

| Method | Endpoint | Request | Response | Query | Mobile uses |
|---|---|---|---|---|---|
| POST | `/api/v1/categories` | `CategoryCreate` | 201 `CategoryResponse` | - | yes |
| GET | `/api/v1/categories` | - | 200 `[CategoryResponse]` | include_hidden | yes |
| GET | `/api/v1/categories/{category_id}` | - | 200 `CategoryResponse` | - | yes |
| PATCH | `/api/v1/categories/{category_id}` | `CategoryUpdate` | 200 `CategoryResponse` | - | yes |
| DELETE | `/api/v1/categories/{category_id}` | - | 204 no body | - | yes |

### expenses

| Method | Endpoint | Request | Response | Query | Mobile uses |
|---|---|---|---|---|---|
| POST | `/api/v1/expenses` | `ExpenseCreate` | 201 `ExpenseResponse` | - | yes |
| GET | `/api/v1/expenses` | - | 200 `[ExpenseResponse]` | - | yes |
| PATCH | `/api/v1/expenses/{expense_id}` | `ExpenseUpdate` | 200 `ExpenseResponse` | - | yes |
| DELETE | `/api/v1/expenses/{expense_id}` | - | 204 no body | - | yes |

### financial-rules

| Method | Endpoint | Request | Response | Query | Mobile uses |
|---|---|---|---|---|---|
| POST | `/api/v1/financial-rules` | `FinancialRuleCreate` (union by `rule_type`) | 201 rule response (union by `rule_type`) | - | **no** |
| GET | `/api/v1/financial-rules` | - | 200 `[object]` | - | **no** |
| POST | `/api/v1/financial-rules/evaluate` | - | 200 `RuleEvaluationResponse` | limit | **no** |
| GET | `/api/v1/financial-rules/{rule_id}` | - | 200 rule response (union by `rule_type`) | - | **no** |
| PATCH | `/api/v1/financial-rules/{rule_id}` | `FinancialRuleUpdate` | 200 rule response (union by `rule_type`) | - | **no** |
| DELETE | `/api/v1/financial-rules/{rule_id}` | - | 204 no body | - | **no** |
| POST | `/api/v1/financial-rules/{rule_id}/disable` | - | 200 rule response (union by `rule_type`) | - | **no** |
| POST | `/api/v1/financial-rules/{rule_id}/enable` | - | 200 rule response (union by `rule_type`) | - | **no** |
| POST | `/api/v1/financial-rules/{rule_id}/pause` | - | 200 rule response (union by `rule_type`) | - | **no** |

### goals

| Method | Endpoint | Request | Response | Query | Mobile uses |
|---|---|---|---|---|---|
| POST | `/api/v1/goals` | `GoalCreate` | 201 `GoalResponse` | - | yes |
| GET | `/api/v1/goals` | - | 200 `[GoalResponse]` | - | yes |
| PUT | `/api/v1/goals/priorities` | `GoalPriorityReorderRequest` | 200 `[GoalResponse]` | - | yes |
| PATCH | `/api/v1/goals/{goal_id}` | `GoalUpdate` | 200 `GoalResponse` | - | yes |
| DELETE | `/api/v1/goals/{goal_id}` | - | 204 no body | - | yes |
| POST | `/api/v1/goals/{goal_id}/transactions` | `GoalTransactionCreate` | 201 `GoalTransactionCreatedResponse` | - | yes |
| GET | `/api/v1/goals/{goal_id}/transactions` | - | 200 `[GoalTransactionResponse]` | - | yes |

### income

| Method | Endpoint | Request | Response | Query | Mobile uses |
|---|---|---|---|---|---|
| POST | `/api/v1/income` | `IncomeCreate` | 201 `IncomeResponse` | - | yes |
| GET | `/api/v1/income` | - | 200 `[IncomeResponse]` | - | yes |
| PATCH | `/api/v1/income/{income_id}` | `IncomeUpdate` | 200 `IncomeResponse` | - | yes |
| DELETE | `/api/v1/income/{income_id}` | - | 204 no body | - | yes |

### receipts

| Method | Endpoint | Request | Response | Query | Mobile uses |
|---|---|---|---|---|---|
| POST | `/api/v1/receipts` | `ReceiptCreate` | 201 `ReceiptResponse` | - | **no** |
| GET | `/api/v1/receipts` | - | 200 `[ReceiptResponse]` | - | **no** |
| POST | `/api/v1/receipts/upload` | multipart (`file`) | 201 `ReceiptResponse` | - | yes |
| GET | `/api/v1/receipts/{receipt_id}` | - | 200 `ReceiptResponse` | - | yes |
| PATCH | `/api/v1/receipts/{receipt_id}` | `ReceiptUpdate` | 200 `ReceiptResponse` | - | **no** |
| DELETE | `/api/v1/receipts/{receipt_id}` | - | 204 no body | - | **no** |
| POST | `/api/v1/receipts/{receipt_id}/confirm` | `ReceiptConfirmRequest` | 200 `ReceiptConfirmResponse` | - | yes |
| POST | `/api/v1/receipts/{receipt_id}/process` | - | 200 `ReceiptResponse` | - | yes |

### rule-alerts

| Method | Endpoint | Request | Response | Query | Mobile uses |
|---|---|---|---|---|---|
| GET | `/api/v1/rule-alerts` | - | 200 `RuleAlertListResponse` | limit,offset,acknowledged | **no** |
| POST | `/api/v1/rule-alerts/{alert_id}/acknowledge` | - | 200 `RuleAlertResponse` | - | **no** |

### rule-executions

| Method | Endpoint | Request | Response | Query | Mobile uses |
|---|---|---|---|---|---|
| GET | `/api/v1/rule-executions` | - | 200 `RuleExecutionListResponse` | limit,offset,rule_id,status | **no** |

### rule-proposals

| Method | Endpoint | Request | Response | Query | Mobile uses |
|---|---|---|---|---|---|
| GET | `/api/v1/rule-proposals` | - | 200 `RuleProposalListResponse` | limit,offset,status | **no** |
| GET | `/api/v1/rule-proposals/{proposal_id}` | - | 200 `RuleProposalResponse` | - | **no** |
| POST | `/api/v1/rule-proposals/{proposal_id}/confirm` | - | 200 `RuleProposalResponse` | - | **no** |
| POST | `/api/v1/rule-proposals/{proposal_id}/reject` | - | 200 `RuleProposalResponse` | - | **no** |

## 3. MVP action matrix

Columns: **Errors** = domain errors an action can produce beyond 401/404/422-validation (full text in Appendix A).
**Consumer** = the mobile screen that calls it today. **Invalidates** = what the client invalidates after success.
**Status**: IMPLEMENTED (backend and mobile), PARTIAL, MISSING (mobile integration absent), BLOCKED.
Query keys for not-yet-built rule screens are marked *proposed*; they are suggestions, not existing code.

### 3.1 Foundation (all IMPLEMENTED unless stated)

| Action | Endpoint | Key errors | Idempotency | Consumer | Reads (query keys) | Invalidates | Gap |
|---|---|---|---|---|---|---|---|
| Sign in | Supabase Auth (not FastAPI) | Supabase message | n/a | `sign-in.tsx` | none | none | No 401 handling, no sign-up/reset (PARTIAL) |
| List Accounts | `GET /accounts` | — | n/a | Accounts, pickers, Goal detail, Dashboard-adjacent | `["accounts",uid]` | n/a | Capacity fields `minimum_unallocated_floor`, `active_rule_holds`, `rule_capacity`, `scheduled_outflows`, `planned_transfer_outflows`, `unallocated_amount`, `negative_balance` returned but not typed/shown |
| Create Account | `POST /accounts` | 422 | none | Account create | — | `["accounts",uid]` | — |
| Account ledger read / manual adjust | `GET`/`POST /accounts/{id}/transactions` | 409 archived Account | none | Account detail | `["accounts","transactions",uid,id]` | accounts + transactions | Unpaginated ledger |
| Edit / archive / delete Account | `PATCH`/`DELETE /accounts/{id}` | 409 currency immutable, deletion not allowed, referenced by planned transfer / Goal reservation / rule | none | Account edit/detail | accounts | `["accounts",uid]` | Rule-reference 409 not explained in UI |
| Create Income | `POST /income` | 422 currency mismatch, future-dated FX, FX unavailable; 503 FX provider | none | Income create | — | income, financial-overview, income-expense-trend (+ accounts, account transactions when linked) | Does not trigger rules evaluation (MISSING, M10) |
| Edit / delete Income | `PATCH`/`DELETE /income/{id}` | same + 404 | none | Income edit | income | same | Income edit/delete cancels or supersedes open proposals server-side (`source_changed`, `source_deleted`); client unaware |
| Create/edit/delete Expense | `POST`/`PATCH`/`DELETE /expenses` | 422 mismatch/FX; 503 FX | none | Expenses | expenses, categories, accounts | `expense-cache.ts` set | — |
| Categories CRUD | `/categories` (5 ops) | 409 exists, default protected, in use by budget | none | Categories | `["categories",uid,"all"]`, `["categories",uid]` | categories (+ expenses, budgets, analytics on delete) | — |
| Budgets CRUD | `/budgets` (4 ops) | 409 exists, immutable field, retroactive deactivation, referenced by rule | none | Budgets | `["budgets",uid]` | budgets, budget-status | Rule-reference 409 not explained |
| Create transfer | `POST /account-transfers` | 409 idempotency conflict, 409 archived, 422 currency mismatch, 422 future date | **`client_request_id` required**; 201 / 200 replay | Transfer create | accounts | transfers, accounts, account transactions | Key lost if the form is left (known residual) |
| Post / delete transfer | `POST …/{id}/post`, `DELETE …/{id}` | 409 already posted; 422 future date | not idempotent; 409 on repeat | Transfers | transfers | transfers, accounts, transactions | — |
| Create Goal / edit / delete | `/goals` (POST, PATCH, DELETE) | 409 currency immutable, deletion not allowed (history), referenced by rule | none | Goals | goals | goals, goal-progress | — |
| Reserve / release (Goal transaction) | `POST /goals/{id}/transactions` | 409 capacity, partition insufficient, tracked insufficient, archived Goal/Account, idempotency conflict; 422 currency mismatch, date rules | **`client_request_id`; 201 / 200** | Goal detail | goals, goal transactions, accounts | goals, transactions, goal-progress (+ accounts when linked) | **`warnings[]` not typed or shown (MISSING, M08)** |
| Goal history | `GET /goals/{id}/transactions` | — | n/a | Goal detail | `["goals","transactions",uid,id]` | n/a | Unpaginated |
| Reorder priorities | `PUT /goals/priorities` | 409 set stale, 409 archived Goal | full-state replace (no key) | Priorities | goals | cache replaced from response | — |
| Receipt upload/process/confirm | `POST /receipts/upload`, `POST …/process`, `GET …/{id}`, `POST …/confirm` | 413, 415, 422 empty/OCR/data missing, 409 not processable/not confirmable/already confirmed, 500 storage | confirm guarded by status (409 repeat) | Receipt upload/review | `["receipts","detail",id]` (no uid) | receipts + expense set | No list/delete UI (M13); receipt key lacks `uid` |
| Analytics reads | 9 `GET /analytics/*` | 422 count over max, invalid period | n/a | Dashboard, Analytics, Overview | `["analytics",family,uid,…]` | by mutations | — |

### 3.2 Smart Rules (backend IMPLEMENTED; mobile MISSING for every row)

| Action | Endpoint | Request / response | Key errors | Idempotency | Pagination | Proposed query keys | Invalidates on success (proposed) | Status |
|---|---|---|---|---|---|---|---|---|
| List rules | `GET /financial-rules` | `[rule]` union by `rule_type` | — | n/a | **none** | `["financial-rules",uid]` | n/a | MISSING |
| Read rule | `GET /financial-rules/{id}` | rule | 404 | n/a | n/a | `["financial-rules",uid,id]` | n/a | MISSING |
| Create rule | `POST /financial-rules` | `FinancialRuleCreate` → 201 rule (always `draft` for allocation) | 409 already exists, 422 currency mismatch, 422 invalid fields, 404 Goal/Account/Budget | **none** (double submit can hit 409 exists) | n/a | — | rules | MISSING |
| Edit rule | `PATCH /financial-rules/{id}` | `FinancialRuleUpdate` | 422, 409 subject archived, 404 | none | n/a | — | rules, proposals (material edit supersedes open proposals) | MISSING |
| Enable / pause / disable | `POST …/enable\|pause\|disable` | → rule | 409 invalid transition, 409 `This rule type cannot be enabled yet.`, 409 subject archived, 422 currency mismatch | not idempotent: repeat → 409 | n/a | — | rules, proposals (pause/disable cancels open proposals), accounts (floor change) | MISSING |
| Delete rule | `DELETE /financial-rules/{id}` | 204 | 409 `Only draft or disabled rules can be deleted.` (**same text also when the rule has execution history**) | n/a | n/a | — | rules | MISSING |
| **Preview** | **none** | — | — | — | — | — | — | **BLOCKED** (does not exist) |
| Evaluate (drain) | `POST /financial-rules/evaluate?limit` (1–`MAX_DRAIN_LIMIT`) | `RuleEvaluationResponse` | — | idempotent | n/a | — | proposals, executions, alerts, goals, goal-progress, accounts | MISSING |
| List proposals | `GET /rule-proposals?status&limit&offset` | `RuleProposalListResponse`; lazily expires due proposals (a read that writes) | — | n/a | **limit/offset/total** | `["rule-proposals",uid,filters]` | n/a | MISSING |
| Read proposal | `GET /rule-proposals/{id}` | `RuleProposalResponse` | 404 | n/a | n/a | `["rule-proposals",uid,id]` | n/a | MISSING |
| Confirm proposal | `POST /rule-proposals/{id}/confirm` | `RuleProposalResponse` | 409 stale (cancelled, nothing written), 404 | **terminal → 200 + stored state** | n/a | — | proposals, executions, goals, goal-progress, accounts | MISSING |
| Reject proposal | `POST /rule-proposals/{id}/reject` | `RuleProposalResponse` | 404 | terminal → 200 + stored state | n/a | — | proposals, executions, accounts | MISSING |
| List executions | `GET /rule-executions?rule_id&status&limit&offset` | `RuleExecutionListResponse` with `items`, `audit` | — | n/a | **limit/offset/total** | `["rule-executions",uid,filters]` | n/a | MISSING |
| List alerts | `GET /rule-alerts?acknowledged&limit&offset` | `RuleAlertListResponse` (`available` flag) | — | n/a | **limit/offset/total** | `["rule-alerts",uid,filters]` | n/a | MISSING |
| Acknowledge alert | `POST /rule-alerts/{id}/acknowledge` | `RuleAlertResponse` | 404 | idempotent | n/a | — | alerts | MISSING |
| Inbox | **no endpoint** | composed client-side from proposals + alerts + executions | — | — | — | — | — | MISSING (design decision Q9) |

## 4. Discrepancies: VF-020 contract versus real API behavior

| # | Contract statement | Real behavior | Impact |
|---|---|---|---|
| X1 | `POST /financial-rules/{id}/preview` dry run (smart-goals-rules §20.4, §10, §21) | **Endpoint absent.** | AUTO "preview before enable" cannot be implemented; blocks M03. |
| X2 | "backend Inbox read model" / "composed backend Inbox" (E9B) | No Inbox endpoint, no unread count. "Composed" means the client calls three endpoints. | Client must compose and poll; the Dashboard entry is a non-numeric attention indicator (no count, scope v1.1 M06 definition). |
| X3 | Proposal read model exposes `planned_amount` (§20.4) | Proposal has `planned_total`; `planned_amount` exists per item (`items[].planned_amount`). | Naming differs; types must follow OpenAPI. |
| X4 | `POST/GET/PATCH/DELETE /api/v1/financial-rules` | No collection-level DELETE; item DELETE only. | Shorthand only. |
| X5 | Confirm / reject of a terminal proposal "is idempotent" | True, and it returns **HTTP 200 with a non-success `status`** (`expired`, `rejected`, `cancelled`). | A 200 is not confirmation; client must branch on `status`. |
| X6 | Alert "Inbox reads current figures; no money columns stored" | `RuleAlertResponse` has no amounts; only `level`, `period_key`, `subject_*`. | UI must fetch Account/Budget figures separately. |
| X7 | Alert acknowledged/resolved semantics | `acknowledged_at` and `resolved_at` are independent; an alert can be resolved and unacknowledged. | Inbox must not equate "resolved" with "read". |
| X8 | Error taxonomy in contract (named domain errors) | Wire format is English text only; two distinct 409s differ only by `detail`. | Exact-string matching, brittle across releases (M15). |
| X9 | Rule delete restricted to draft/disabled without history | A rule with history returns the **same** text "Only draft or disabled rules can be deleted." | The UI cannot tell the user the real reason. |
| X10 | `GET /rule-proposals` is a read | It performs lazy expiry writes under the user lock. | Safe but not read-only; relevant for polling cost. |
| X11 | Contract: AUTO is "executed at the next drain" | Confirmed: drains are (a) `POST /evaluate`, (b) best-effort post-Income background drain, (c) the dispatcher (**not deployed**). | "Unattended" is unproven (Gate I). |
| X12 | `docs/api-contract.md` no GET by id for Accounts/Income/Transfers | Confirmed; also none for Goals, Budgets, Expenses. | Detail screens depend on list caches. |

## 5. Special-attention items

**Account capacity fields (`AccountResponse`).** All are decimal strings: `current_balance` (ledger, may be
negative), `balance_as_of_today`, `scheduled_outflows`, `planned_transfer_outflows`, `reserved_amount`,
`unallocated_amount`, `reservable_amount`, `allocation_status` (`overcommitted` among values),
`negative_balance` (bool), `minimum_unallocated_floor`, `active_rule_holds`, `rule_capacity`. Relationship stated
by the contract: floor-breach is `reservable_amount < minimum_unallocated_floor`; `rule_capacity` = reservable −
floor − active holds. The mobile type declares a subset and ignores the floor/holds/rule-capacity trio.
None of these means bank-available cash.

**Goal reservations.** `GoalTransactionCreate`: `type` (contribution|withdrawal), `amount`, `description`,
`effective_date` (optional; linked transactions must omit it or equal today), `client_request_id`, `account_id`.
`GoalResponse`: `tracked_amount`, `linked_amount`, `current_amount`, `allocations[{account_id, amount}]`,
`priority_rank`. A reservation writes **no** Account ledger row and never changes `current_balance`.

**Income events.** There is no HTTP surface. Each Income create/update/delete writes a `financial_events`
outbox row in the same transaction. The only visible signals are the counters in `RuleEvaluationResponse`
(`processed`, `deferred`, `failed_retryable`, `dead`, `blocked`, `outcomes`) and the resulting executions.
Listing or retrying events is not possible (gap for J18).

**Safety-floor warnings.** `GoalTransactionCreatedResponse.warnings: [GoalTransactionFloorWarning]` where each has
`code="minimum_unallocated_floor"`, `minimum_unallocated_floor`, `projected_reservable_amount`,
`projected_rule_capacity`. Advisory only: computed at response time, not persisted, not part of the idempotency
payload, never blocks. On an idempotent replay (200) the stored transaction is returned unchanged and the
warning is **recomputed from the Account's current state**, so a replay can show a warning the original response
did not (or omit one it did); the UI must render whatever the response carries.

**`financial-rules`.** Four create types, discriminated by `rule_type`. Responses are a union; list and read return
the same union. Mobile needs a discriminated union type. `execution_order` has duplicates and gaps allowed;
`position` on targets is display order only; financial priority is the Goal's `priority_rank`.

**`rule-proposals`.** `status`, `reason_code`, `partial`, `hold_sequence`, `expires_at`, `source_*`, `planned_total`,
`confirm_capacity`, `items[]` with `planned_amount`, `applied_amount`, `target_amount`, `current_amount`,
`expected_amount`. Expiry (`expires_at`, 168 h after creation) is immutable; stored state is normalized to
`expired` lazily on list, confirm, reject and dispatch, and an expired proposal stops holding capacity at the
instant it expires.

**`rule-executions`.** Statuses `awaiting_confirmation`, `executed`, `executed_partial`, `skipped`, `blocked`,
`rejected`, `expired`, `cancelled`. Includes capacity snapshot (`capacity_reservable`, `capacity_floor`,
`capacity_holds`) and `audit[]` (`code`, `actor`, `details`). Exact `reason_code` and audit `code` vocabularies must
be taken from the source of truth before designing copy; the five reason codes found in `rule_execution_service.py`
are `insufficient_capacity`, `nothing_to_allocate`, `source_account_archived`, `target_goal_archived`,
`currency_mismatch` (cancel reasons such as `stale`, `rule_inactive`, `source_changed`, `source_deleted` are also
used in audit/cancellation paths). Treat unknown codes as a neutral fallback.

**`rule-alerts`.** `level` ∈ {`watch`,`at_risk`,`exceeded`,`breached`}; `subject_type` ∈ {`account`,`budget`};
`period_key` is `E<n>` for account episodes and the budget period start (ISO date) for Budget alerts.

## 6. Missing or optional capabilities

| Capability | State |
|---|---|
| Rule preview endpoint | MISSING (required by contract) |
| Machine-readable error codes | MISSING |
| Inbox / unread count endpoint | MISSING, optional |
| Pagination for Expenses, Income, Transfers, Accounts, Goals, Budgets, Rules, Receipts | MISSING |
| List/inspect/retry financial events | MISSING (J18) |
| `GET` by id for Accounts, Income, Transfers, Goals, Budgets, Expenses | MISSING, optional |
| Push or server-initiated notification | DEFERRED |
| Webhook / realtime for proposals | MISSING (polling or manual refresh only) |

## Appendix A — Domain error texts (exact, from `exception_handlers.py`)

Status / source error / `detail`:

| Status | Error | Detail |
|---|---|---|
| 404 | AccountNotFound | Account not found. |
| 409 | AccountCurrencyImmutable | Account currency cannot be changed after transaction history exists. |
| 409 | AccountDeletionNotAllowed | Account with transaction history cannot be deleted. Archive it instead. |
| 409 | AccountArchived | Archived account cannot receive new transactions. |
| 409 | AccountReferencedByPlannedTransfer | Account is referenced by planned transfers. Delete them first. |
| 409 | AccountReferencedByGoalAllocation | Account is referenced by Goal reservations and cannot be deleted or have its currency changed. |
| 409 | AccountReferencedByRule | Account is referenced by a financial rule and cannot be deleted or have its currency changed. |
| 409 | GoalReferencedByRule | Goal is referenced by a financial rule and cannot be deleted or have its currency changed. |
| 409 | BudgetReferencedByRule | Budget is referenced by a financial rule and cannot be deleted. |
| 404 | FinancialRuleNotFound | Financial rule not found. |
| 404 | RuleAlertNotFound | Rule alert not found. |
| 404 | RuleProposalNotFound | Rule proposal not found. |
| 409 | RuleProposalStale | The proposal can no longer be confirmed and was cancelled (stale). Nothing was written. |
| 409 | FinancialRuleAlreadyExists | A rule of this type already exists for this subject. |
| 409 | FinancialRuleInvalidTransition | This status change is not allowed from the rule's current status. |
| 409 | FinancialRuleActivationNotAvailable | This rule type cannot be enabled yet. |
| 409 | FinancialRuleDeletionNotAllowed | Only draft or disabled rules can be deleted. |
| 409 | FinancialRuleSubjectArchived | The rule's Account or Goal is archived. |
| 422 | FinancialRuleCurrencyMismatch | The source Account and every target Goal must use the same currency. |
| 422 | FinancialRuleInvalidFields | message built by the rules service (validation text) |
| 404 | AccountTransferNotFound | Account transfer not found. |
| 409 | AccountTransferIdempotencyConflict | client_request_id has already been used for a different transfer. |
| 422 | AccountTransferCurrencyMismatch | Transfer source and destination accounts must use the same currency. |
| 409 | AccountTransferAlreadyPosted | Account transfer has already been posted. |
| 422 | AccountTransferEffectiveDateInFuture | Transfer effective date cannot be in the future. |
| 409 | CategoryAlreadyExists | Category with this name already exists for this user. |
| 404 | CategoryNotFound | Category not found. |
| 409 | CategoryDefaultModificationNotAllowed | Default category cannot be modified. |
| 409 | CategoryDefaultDeletionNotAllowed | Default category cannot be deleted. |
| 409 | CategoryInUseByBudget | Category is referenced by a budget and cannot be deleted. Hide it instead. |
| 404 | ExpenseNotFound | Expense not found. |
| 422 | ExpenseAccountCurrencyMismatch | Expense currency must match the account's currency to link them. |
| 503 | FxProviderUnavailable | Currency conversion is temporarily unavailable. Please try again shortly. |
| 422 | FxRateUnavailable | This currency cannot be converted for the given date. |
| 422 | FxFutureDatedNotSupported | A foreign-currency expense cannot be dated in the future. |
| 404 | BudgetNotFound | Budget not found. |
| 409 | BudgetRetroactiveDeactivation | Budget end date cannot be set to a date before today. |
| 409 | BudgetAlreadyExists, BudgetImmutableField | (multi-line text; see source) |
| 404 | GoalNotFound | Goal not found. |
| 409 | GoalInsufficientFunds | Withdrawal exceeds the current goal balance. |
| 409 | GoalPartitionInsufficientFunds | Withdrawal exceeds the goal amount reserved against this account. |
| 409 | GoalReservationCapacity | Reservation exceeds the Account's reservable capacity. |
| 422 | GoalLinkedTransactionDate | Linked goal transactions are dated today; effective_date must be omitted or equal to today. |
| 422 | GoalAccountCurrencyMismatch | Goal and Account currencies must match. |
| 409 | GoalPriorityGoalArchived | Archived goals cannot be ranked. |
| 409 | GoalPrioritySetStale | Goal list is out of date. Reload goals and try again. |
| 409 | GoalArchived | Archived goal cannot receive contributions. |
| 409 | GoalCurrencyImmutable | Goal currency cannot be changed after transaction history exists. |
| 409 | GoalDeletionNotAllowed | Goal with transaction history cannot be deleted. Archive it instead. |
| 409 | GoalTransactionIdempotencyConflict | client_request_id has already been used for a different goal transaction. |
| 422 | GoalTransactionEffectiveDateInFuture | Goal transaction effective date cannot be in the future. |
| 404 | IncomeNotFound | Income not found. |
| 422 | IncomeFutureDatedNotSupported | A foreign-currency income cannot be dated in the future. |
| 422 | IncomeAccountCurrencyMismatch | Income currency must match the account's currency to link them. |
| 404/422/415/413/500/409 | Receipt errors | not found; file empty; type not supported; too large; could not be stored; cannot be processed / confirmed in current status; OCR failed; confirmation data missing; already confirmed |

---

## v1.1 Addendum: planned contracts and non-FastAPI calls (VF-MVP-ENG-003)

Nothing in this addendum exists in OpenAPI today. Each item is a **planned contract** delivered by a roadmap task.
Designers and mobile engineers must treat them as dependencies, not as available endpoints.

| Item | Kind | Task | Requirement summary |
|---|---|---|---|
| `code` on every error body | Planned additive field | BE-1 | `{"detail": "...", "code": "stable_snake_case"}`; validation errors also carry a code; registry in `docs/api-contract.md`; never renamed or reused; mobile maps by code with neutral fallback |
| `POST /api/v1/financial-rules/{rule_id}/preview` | Planned endpoint (name per the approved contract; final sheet approved before coding) | BE-2 | Read-only; owner-scoped (foreign id 404); sample income in; planned items per target, partial/skip reasons, capacity figures out; parity with execution; no writes (no rows, no outbox event) |
| Pagination on `GET /expenses` and `GET /income` | Planned parameters/envelope | BE-3 | Backward-compatible with the shipped client (strategy chosen in the task); stable ordering; `total` |
| Supabase Auth `signUp` | Client call (not FastAPI) | MF-4 | Public registration (Q5) |
| Supabase Auth `resetPasswordForEmail`, session from link, `updateUser({password})` | Client calls (not FastAPI) | MF-4 | Password recovery (Q5) |
| Inbox | **No endpoint, by decision** (Q9 A) | F-4 | Composed from `GET /rule-proposals`, `GET /rule-alerts`, `GET /rule-executions` |

Unused endpoints by decision: `POST/GET/PATCH/DELETE /receipts` (Q6 deferral). Unused because the feature is missing
(not by decision): the nine `financial-rules`, four `rule-proposals`, two `rule-alerts` and one `rule-executions`
operations.

Discrepancy status after decisions: X1 (preview) is resolved by approving BE-2; X2 (Inbox) is resolved by decision
(client-composed); X8/X9 (error text only) are resolved by approving BE-1; X3–X7, X10–X12 remain documented behaviors.
