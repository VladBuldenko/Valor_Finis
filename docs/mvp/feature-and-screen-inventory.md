# Feature and Screen Inventory (VF-MVP-ENG-001, Part 3)

Date: 2026-10-27. Basis: `main` @ `08d985c030a38823fe43863c806d90bbc86e97b4`. Source: every file under
`apps/mobile/app` and `apps/mobile/src/features`.

The current navigation (a flat Stack plus a button grid on the Dashboard) is **an implementation fact, not the
final UX design**. Designers are free to restructure it; this inventory records what exists and what each screen
needs from the backend.

Abbreviations. **Auth**: every `(app)` route is behind `Stack.Protected guard={!!session}`; every API call sends
`Authorization: Bearer <Supabase access token>` through `src/api/api-client.ts` (`apiRequest`). **Status**:
IMPLEMENTED / PARTIAL / MISSING per the audit. **MVP**: Required (R), Optional (O), Deferred (D). Query-key
families are written `[family, userId, …]`. Loading = `ActivityIndicator`. Error = a static line, no retry
action, unless stated. All forms guard double submit with `isPending`. There is **no pull-to-refresh** on any
screen.

## 1. Navigation map (as implemented)

```text
app/_layout.tsx                 QueryClientProvider > AuthProvider > Stack (Protected by session)
 ├─ sign-in                     (public)
 └─ (app)/_layout.tsx           Stack, titles only, no tabs
     ├─ index                   Dashboard  -> buttons: overview, accounts, income, transfers, expenses,
     │                                        analytics, budgets, categories, goals, receipts/upload
     ├─ accounts · accounts/new · accounts/[id] · accounts/[id]/edit
     ├─ income · income/new · income/[id]/edit
     ├─ transfers · transfers/new
     ├─ expenses · expenses/[id]
     ├─ categories · categories/new · categories/[id]/edit
     ├─ budgets · budgets/new · budgets/[id]/edit
     ├─ goals · goals/new · goals/[id] · goals/[id]/edit · goals/priorities
     ├─ analytics · overview
     └─ receipts/upload · receipts/[id]      (not registered in the layout; default header titles)
```

Not present: rules, proposals, alerts, inbox, executions, settings/profile, receipts list, any tab bar.

## 2. Implemented screens

### Authentication
| Field | Value |
|---|---|
| Route / component | `/sign-in` · `app/sign-in.tsx` (inline; `auth.service.ts` `signInWithEmail`) |
| Objective | Establish a session. |
| Displays | Email, password fields. |
| Editable | email, password (`secureTextEntry`, `autoComplete`). |
| Actions | Sign in. Sign-out lives on the Dashboard. |
| Endpoints | None to FastAPI; Supabase Auth only. |
| Auth | Public; redirected away once a session exists. |
| Cache | None. `AuthProvider` owns session; no `queryClient.clear()` on sign-out. |
| Loading / error | Button spinner; `Alert` with the Supabase message. |
| Empty | n/a. |
| Limitations | No sign-up, reset, magic link, biometric unlock, 401/expiry handling. The root shows a spinner while the session restores. |
| Status / MVP | PARTIAL / R (sign-up and reset: decision Q5). |

### Dashboard
| Field | Value |
|---|---|
| Route / component | `/` · `dashboard/dashboard-screen.tsx` |
| Objective | Monthly orientation and entry to every area. |
| Displays | This month summary; Income / Expenses / Net card (links to `/overview`); category spend; budget status with risk; goals (filter current/completed/archived); navigation buttons; sign-out. |
| Editable | None. |
| Actions | Navigate; sign out. |
| Endpoints | `GET /analytics/monthly-summary?year&month`, `/analytics/financial-overview`, `/analytics/category-summary`, `/analytics/budget-status`, `GET /budgets`, `GET /goals`, `GET /analytics/goal-progress`. |
| Cache | Reads `["analytics","monthly-summary"|"financial-overview"|"budget-status"|"goal-progress", uid, …]`, `["budgets", uid]`, `["goals", uid]`. Refreshed only by invalidation from mutations or remount; no focus or pull refresh. |
| Loading / error | Per-section spinner and per-section static error line. |
| Empty | "No budgets yet.", "No goals yet." / "No current goals." |
| Limitations | No Account balances, no rules/alerts/proposals signal, no unread badge; month taken from the device calendar (`use-local-calendar-month.ts`) while "today" on the server is server date. |
| Status / MVP | PARTIAL / R (needs Inbox/alert entry, M06). |

### Accounts
| Screen | Route · component | Displays · editable · actions | Endpoints | Cache keys | Limitations | Status / MVP |
|---|---|---|---|---|---|---|
| List | `/accounts` · `accounts-screen.tsx` | Active/archived toggle; name, type, `current_balance`, `reserved_amount`, `reservable_amount` ("Available to reserve"), overcommitted marker. No editing. Links to detail, edit, new. | `GET /accounts` | `["accounts",uid]` | No safety floor, holds or `rule_capacity`. Empty text reflects the filter ("No accounts yet." only for the right view). | IMPLEMENTED / R |
| Create | `/accounts/new` · `account-create-screen.tsx` | Name, type picker (checking/savings/cash), currency, optional opening balance + date. Submit. | `POST /accounts` | invalidates `["accounts",uid]` | Zero/empty opening balance means none. | IMPLEMENTED / R |
| Detail | `/accounts/[id]` · `account-detail-screen.tsx` | Balance, reserved, "Available to reserve", overcommitted note; transaction ledger; manual adjustment form (direction, amount, date, description); archive/reactivate; delete. | `GET /accounts` (resolve by id), `GET /accounts/{id}/transactions`, `POST /accounts/{id}/transactions`, `PATCH /accounts/{id}` (status), `DELETE /accounts/{id}` | `["accounts",uid]`, `["accounts","transactions",uid,id]` | Ledger unpaginated; archived/overcommitted/409 lifecycle messages come from raw `detail`. | IMPLEMENTED / R |
| Edit | `/accounts/[id]/edit` · `account-edit-screen.tsx` | Name, type, currency; save disabled without changes; empty PATCH prevented. | `GET /accounts`, `PATCH /accounts/{id}` | `["accounts",uid]` | Currency change is rejected by the backend once history exists (409). | IMPLEMENTED / R |

### Income
| Screen | Route · component | Displays · editable · actions | Endpoints | Cache keys | Limitations | Status / MVP |
|---|---|---|---|---|---|---|
| List | `/income` · `income-screen.tsx` | Amount, currency, source, received date, linked Account label ("Linked account unavailable" when unresolved). Links to new/edit. | `GET /income`, `GET /accounts` | `["income",uid]`, `["accounts",uid]` | Unpaginated. | IMPLEMENTED / R |
| Create | `/income/new` · `income-create-screen.tsx` | Amount, currency (default "EUR" preselected), received date (default device today), source (salary/freelance/refund/gift/other), description, optional Account. | `POST /income` | via `income-cache.ts`: income, financial-overview, income-expense-trend; accounts + account transactions when linked | Currency default is a hard-coded constant. Future-dated Income is rejected (422). A successful create writes a financial event for the rules engine, but the client does not trigger evaluation. | IMPLEMENTED / R |
| Edit/delete | `/income/[id]/edit` · `income-edit-screen.tsx` | Same fields; save; delete with confirm. | `GET /income`, `PATCH /income/{id}`, `DELETE /income/{id}` | as above | Unresolved Account link stays unchanged on load failure. | IMPLEMENTED / R |

### Expenses
| Screen | Route · component | Displays · editable · actions | Endpoints | Cache keys | Limitations | Status / MVP |
|---|---|---|---|---|---|---|
| List + create | `/expenses` · `expenses-screen.tsx` | Inline create form (title, amount, currency, date, description, category, Account) above the list. | `GET /expenses`, `GET /categories`, `GET /accounts`, `POST /expenses` | `["expenses",uid]`, `["categories",uid]`, `["accounts",uid]`; invalidates via `expense-cache.ts` (expenses, nine analytics families, accounts when linked) | Unpaginated; no filters; create and list share one scroll. | IMPLEMENTED / R |
| Detail | `/expenses/[id]` · `expense-detail-screen.tsx` | Edit title, amount, currency, date, description, category, Account; delete. | list + `PATCH /expenses/{id}`, `DELETE /expenses/{id}` | same | Account list failure keeps the link unchanged. | IMPLEMENTED / R |

### Categories
| Screen | Route · component | Displays · editable · actions | Endpoints | Cache | Status / MVP |
|---|---|---|---|---|---|
| List | `/categories` · `categories-screen.tsx` | Includes hidden; hide/show; delete; links to new/edit. | `GET /categories?include_hidden=true`, `PATCH`, `DELETE` | `["categories",uid,"all"]` and `["categories",uid]`; delete also refreshes expenses, budgets, three analytics families | IMPLEMENTED / R |
| Create | `/categories/new` | Name (+ color, icon fields exist in the API). | `POST /categories` | both categories keys | IMPLEMENTED / R |
| Edit | `/categories/[id]/edit` | Name, visibility. Protected defaults return 409. | `GET /categories/{id}`, `PATCH` | `["categories",uid,id]` + families | IMPLEMENTED / R |

### Budgets
| Screen | Route · component | Displays · editable · actions | Endpoints | Cache | Status / MVP |
|---|---|---|---|---|---|
| List | `/budgets` · `budgets-screen.tsx` | Budget name, limit, period, status/risk (pace, projection) from analytics; delete. | `GET /budgets`, `GET /analytics/budget-status`, `DELETE /budgets/{id}` | `["budgets",uid]`, `["analytics","budget-status",uid]` | IMPLEMENTED / R |
| Create | `/budgets/new` | Name, limit, period (weekly/monthly/yearly), start, optional end, optional category. | `GET /categories`, `POST /budgets` | budgets + budget-status | IMPLEMENTED / R |
| Edit | `/budgets/[id]/edit` | Same fields; immutable-field rules return 409. | `GET /budgets` (resolve), `PATCH /budgets/{id}` | same | IMPLEMENTED / R |

Limitation: a Budget referenced by a rule returns a 409 on delete (`BudgetReferencedByRuleError`); the screen
shows the raw `detail` with no explanation or link to the rule (rules UI does not exist).

### Transfers
| Screen | Route · component | Displays · editable · actions | Endpoints | Cache | Status / MVP |
|---|---|---|---|---|---|
| List | `/transfers` · `transfers-screen.tsx` | Planned/posted, source → destination, amount, dates; post a planned transfer with an explicit effective date; delete. | `GET /account-transfers`, `GET /accounts`, `POST /account-transfers/{id}/post`, `DELETE /account-transfers/{id}` | `["account-transfers",uid]`, `["accounts",uid]`; `transfer-cache.ts` | IMPLEMENTED / R |
| Create | `/transfers/new` · `transfer-create-screen.tsx` | Source, destination (owned, same currency), amount, date, description. Attempt-scoped `client_request_id` (`transfer-create-attempts.ts`). | `POST /account-transfers` | transfers + accounts + account transactions | IMPLEMENTED / R |

Limitation: the `client_request_id` lives in the open form; leaving the form after a lost response loses it
(documented residual).

### Goals
| Screen | Route · component | Displays · editable · actions | Endpoints | Cache | Status / MVP |
|---|---|---|---|---|---|
| List | `/goals` · `goals-screen.tsx` | Filter current/completed/archived; amounts, progress, "reserved in accounts"; delete; links to detail, edit, new, priorities. | `GET /goals`, `GET /analytics/goal-progress`, `DELETE /goals/{id}` | `["goals",uid]`, `["analytics","goal-progress",uid]` | IMPLEMENTED / R |
| Create | `/goals/new` | Name, target, currency, target date. | `POST /goals` | goals + goal-progress | IMPLEMENTED / R |
| Edit | `/goals/[id]/edit` | Name, target, target date, status (archive). Currency immutable with history. | `GET /goals`, `PATCH /goals/{id}` | goals + goal-progress | IMPLEMENTED / R |
| Detail | `/goals/[id]` · `goal-detail-screen.tsx` | Tracked / linked amounts, allocations by Account; history labels (Reservation / Release); form: contribute or withdraw, amount, description, source Account (reserve) or explicit partition (release, never preselected). | `GET /goals`, `GET /goals/{id}/transactions`, `GET /accounts`, `POST /goals/{id}/transactions` | `["goals","transactions",uid,id]`, goals, accounts (linked only), goal-progress (`goal-cache.ts`) | IMPLEMENTED / R. Limitation: the response `warnings[]` (safety-floor advisory) is not typed or displayed. |
| Priorities | `/goals/priorities` · `goal-priorities-screen.tsx` | Up/down reorder of non-archived Goals; save sends the full ordered set; stale-set (409) refetches. | `GET /goals`, `PUT /goals/priorities` | `["goals",uid]` | IMPLEMENTED / R |

### Receipts
| Screen | Route · component | Displays · editable · actions | Endpoints | Cache | Status / MVP |
|---|---|---|---|---|---|
| Upload | `/receipts/upload` · `receipt-upload-screen.tsx` | Camera or library picker; upload; process (OCR); handles a failed process by keeping the receipt id. | `POST /receipts/upload` (multipart), `POST /receipts/{id}/process` | none | IMPLEMENTED / R |
| Review/confirm | `/receipts/[id]` · `receipt-review-screen.tsx` | Detected merchant, amount, currency, date; editable title, amount, currency, date, description, category, Account; "already confirmed" branch; confirm creates an Expense and navigates to it. | `GET /receipts/{id}`, `GET /categories`, `GET /accounts`, `POST /receipts/{id}/confirm` | `["receipts","detail",id]` (no user id in key), invalidates `["receipts"]` + expense set | IMPLEMENTED / R |

Limitation: no receipt list, delete or edit screen although `GET/PATCH/DELETE /receipts` exist (M13).

### Analytics and Financial Overview
| Screen | Route · component | Displays | Endpoints | Cache | Status / MVP |
|---|---|---|---|---|---|
| Analytics | `/analytics` · `analytics-screen.tsx` | Spending forecast, spending trend (period selector: day/week/month); category trend (fixed to month); "No category spending in this period yet." | `GET /analytics/spending-forecast`, `/spending-trend`, `/category-trend` | `["analytics", family, uid, …]` | IMPLEMENTED / R |
| Financial Overview | `/overview` · `financial-overview-screen.tsx` | Month navigation, Income, Expenses, Net, savings rate, 6-month history; `period_state` and `data_status` honored. | `GET /analytics/financial-overview?year&month`, `GET /analytics/income-expense-trend?count` | `["analytics","financial-overview"|"income-expense-trend", uid, …]` | IMPLEMENTED / R (device refresh acceptance still recorded as pending) |

## 3. Feature directories (`apps/mobile/src/features`)

| Directory | Role | Notes |
|---|---|---|
| `accounts` | screens, service, types, validation, picker, error copy | Types omit `minimum_unallocated_floor`, `active_rule_holds`, `rule_capacity`, `scheduled_outflows`, `planned_transfer_outflows` display. |
| `analytics` | screens, service, presentation, calendar-month helper | Overview presentation is pure helper code. |
| `auth` | `auth-context.tsx`, `auth.service.ts` | Context owns session only. |
| `budgets` | screens, service, status presentation | |
| `categories` | screens, service | |
| `dashboard` | one screen | |
| `expenses` | screens, service, `expense-cache.ts` | Shared invalidation helper (also used by receipts). |
| `goals` | screens, service, cache, partitions, priorities, transaction attempts/errors | The only directory with Node tests (62). |
| `income` | screens, service, `income-cache.ts` | |
| `receipts` | upload and review screens, service, validation | |
| `transfers` | screens, service, cache, attempts, local date helper | |
| shared (`src/api`, `src/lib`, `src/config`) | `api-client.ts`, `api-error-message.ts`, `query-client.ts`, `supabase.ts`, `env.ts` | No timeout, no 401 handling, default QueryClient. |
| **rules / proposals / alerts / inbox** | **do not exist** | See section 4. |

## 4. Missing Smart Rules screens (identified, not implemented)

These are **capabilities needed**, not designs. Names are working labels. Every endpoint below exists in OpenAPI
unless marked.

| Working label | User objective | Data it needs | Endpoints (real) | Status |
|---|---|---|---|---|
| Rules list | See all rules, status, mode, order | rule list with status, `execution_mode`, `execution_order`, targets, floor amount | `GET /financial-rules` | MISSING |
| Rule create/edit (income allocation) | Define policy `FIXED_PER_GOAL` or `PERCENT_OF_INCOME_WATERFALL`, targets (Goals + amounts/caps), income sources, AUTO or CONFIRM, `cap_at_target`, `allow_partial`, `effective_from` | Accounts, Goals, rule schema | `POST/PATCH /financial-rules` | MISSING |
| Rule create/edit (floor) | Set `floor_amount` for an Account | Account | same | MISSING |
| Rule create/edit (alerts) | Overcommitment for an Account; Budget alert for a Budget | Accounts, Budgets | same | MISSING |
| Rule detail / lifecycle | Enable, pause, disable, delete (draft/disabled with no history only) | rule, executions filtered by `rule_id` | `POST …/enable|pause|disable`, `DELETE`, `GET /rule-executions?rule_id` | MISSING |
| **Rule preview** | See what a rule would do for a sample income before enabling | dry-run result | **none: `POST /financial-rules/{id}/preview` is specified but not implemented** | **BLOCKED** (Q3) |
| Evaluation trigger (no screen) | Foreground/Inbox-open drain | summary counters | `POST /financial-rules/evaluate` | MISSING |
| Inbox | One place for open proposals and unacknowledged alerts | proposals (`awaiting_confirmation`), alerts (`acknowledged=false`), recent failures/blocked executions | `GET /rule-proposals`, `GET /rule-alerts`, `GET /rule-executions` (no composed endpoint) | MISSING |
| Proposal detail | Review planned items, expiry, confirm capacity; confirm or reject | `RuleProposalResponse` incl. `items`, `expires_at`, `confirm_capacity`, `partial` | `GET /rule-proposals/{id}`, `POST …/confirm`, `POST …/reject` | MISSING |
| Alert list/detail | Read and acknowledge | `RuleAlertResponse` (`level`, `subject_name`, `period_key`) | `GET /rule-alerts`, `POST …/acknowledge` | MISSING |
| Execution history | Understand what ran, why something was skipped/blocked | executions with `items`, `audit`, `reason_code`, capacity snapshot | `GET /rule-executions` | MISSING |
| Floor warning (inline) | Advisory after a manual reservation | `warnings[]` on the Goal-transaction response | already returned | MISSING |
| Account capacity detail (inline) | Explain reserved, holds, floor, rule capacity | `AccountResponse` fields | already returned | MISSING |
