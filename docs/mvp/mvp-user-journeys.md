# MVP User Journeys (VF-MVP-ENG-001, Part 4)

Date: 2026-10-27. Basis: `main` @ `08d985c030a38823fe43863c806d90bbc86e97b4`.

Each journey states what the **backend supports** and whether the **current mobile client can perform it**
(`Mobile: POSSIBLE | PARTIAL | NOT POSSIBLE`). Endpoint paths are real (OpenAPI-verified); request and response
schemas are in [api-mobile-contract-matrix.md](api-mobile-contract-matrix.md). Error text is quoted from
`app/core/exception_handlers.py`; the backend sends no machine-readable code, only `{"detail": "<text>"}` plus the
HTTP status. Cache families are the real TanStack key families (`[family, userId, …]`).

Security boundary common to every journey: the user comes from the verified Supabase JWT; no payload carries
`user_id`; every read and write is scoped by that user; a foreign id returns the same 404 as a missing id.

Summary:

| ID | Journey | Backend | Mobile |
|---|---|---|---|
| J01 | Sign in and establish a session | Supabase Auth | PARTIAL |
| J02 | Create an Account with an opening balance | IMPLEMENTED | POSSIBLE |
| J03 | Record Income into an Account | IMPLEMENTED | POSSIBLE |
| J04 | Record an Expense and update the Account balance | IMPLEMENTED | POSSIBLE |
| J05 | Create and manage a Budget | IMPLEMENTED | POSSIBLE |
| J06 | Create a Goal | IMPLEMENTED | POSSIBLE |
| J07 | Reserve money from an Account for a Goal | IMPLEMENTED | POSSIBLE (floor warning not shown) |
| J08 | Release a reservation without a Transfer | IMPLEMENTED | POSSIBLE |
| J09 | Reorder Goals by priority | IMPLEMENTED | POSSIBLE |
| J10 | Move money between owned Accounts | IMPLEMENTED | POSSIBLE |
| J11 | Upload, review, confirm a receipt | IMPLEMENTED | POSSIBLE |
| J12 | Understand monthly Income, Expenses, Net, analytics | IMPLEMENTED | POSSIBLE |
| J13 | Create and enable a supported rule | IMPLEMENTED | **NOT POSSIBLE** |
| J14 | Preview and manage an AUTO or CONFIRM rule | **Preview MISSING**; management IMPLEMENTED | **NOT POSSIBLE** |
| J15 | Inspect and confirm/reject a proposal | IMPLEMENTED | **NOT POSSIBLE** |
| J16 | Read and acknowledge an alert | IMPLEMENTED (needs E9A in production: UNKNOWN) | **NOT POSSIBLE** |
| J17 | Safety-floor warning and hard capacity rejection | IMPLEMENTED | PARTIAL (rejection yes, warning no) |
| J18 | Rule execution history, failures, recovery | PARTIAL (no recovery endpoint) | **NOT POSSIBLE** |

---

## J01 — Sign in and establish a session
- **Mobile:** PARTIAL. **Entry:** app launch → `/sign-in` when no session.
- **Preconditions:** a Supabase user exists (no in-app sign-up). Network reachable.
- **Actions:** enter email and password → Sign in.
- **API calls:** Supabase `signInWithPassword` (not FastAPI). Subsequent FastAPI calls carry the access token.
- **State transitions:** no session → session (stored by Supabase in AsyncStorage) → `(app)` routes unlock.
- **Expected:** Dashboard loads; all queries enabled by `Boolean(session)`.
- **Error/conflict:** invalid credentials → Alert with the Supabase message. Expired/revoked token mid-session →
  FastAPI 401 → `apiRequest` throws a plain `Error`; **no sign-out, no refresh, no re-login prompt** (gap M11).
- **Data changes:** none server-side.
- **Cache invalidation:** none on sign-in. On sign-out the cache is **not** cleared (keys are user-scoped).
- **Security:** `AUTH_MODE` must be Supabase in production; `X-User-Id` is dev/test only. Tokens are never logged.
- **Acceptance:** valid login lands on Dashboard; wrong password shows an error and no session; killing and
  reopening the app restores the session; after sign-out, protected routes are unreachable; **an expired token
  produces a defined recovery (to be implemented)**.

## J02 — Create an Account with an opening balance
- **Mobile:** POSSIBLE. **Entry:** Dashboard → Accounts → Add.
- **Preconditions:** signed in.
- **Actions:** name, type (checking/savings/cash), currency, optional opening balance and date → Save.
- **API:** `POST /accounts` (201 `AccountResponse`).
- **State:** Account `active`; a non-zero opening balance creates an opening-balance ledger row.
- **Expected:** Account appears in the Active list with `current_balance` = opening balance; `reserved_amount`
  0; `reservable_amount` per backend.
- **Errors:** 422 validation (amount precision beyond NUMERIC(12,2), blank name).
- **Data changes:** `accounts` row (+ one `account_transactions` row when an opening balance is given).
- **Cache:** invalidate `["accounts",uid]`.
- **Security:** Account owned by the JWT user.
- **Acceptance:** balance shown equals the backend value to the cent; an Account with zero opening balance has
  an empty ledger; the new Account is selectable in Income, Expense, Transfer, Goal reservation pickers.

## J03 — Record Income into an Account
- **Mobile:** POSSIBLE. **Entry:** Dashboard → Income → Add.
- **Preconditions:** optionally an active Account in the same currency.
- **Actions:** amount, currency, received date, source, description, optional Account → Save.
- **API:** `POST /income` (201). Backend also writes one `financial_events` outbox row in the same transaction
  and schedules a best-effort post-response drain of **that user's** events (`RULE_EVENT_BACKGROUND_DISPATCH`,
  default true).
- **State:** Income recorded; if linked, an Account credit is projected; the event is `pending`.
- **Expected:** Income in list; Account balance increases by the amount; Financial Overview income increases.
  If the user has an enabled eligible rule, AUTO executes (or a CONFIRM proposal appears) shortly after, **but the
  mobile client shows no sign of it today** (J13–J15).
- **Errors:** 422 `Income currency must match the account's currency to link them.`; 422 future-dated
  foreign-currency Income; 503 FX provider unavailable; 422 `This currency cannot be converted for the given date.`
- **Data:** `income`, `account_transactions` (if linked), `financial_events`; FX snapshot fields.
- **Cache:** `["income"]`, `["analytics","financial-overview"]`, `["analytics","income-expense-trend"]`; when
  linked also `["accounts"]` and `["accounts","transactions"]`. **Not invalidated today:** rule families (do not
  exist yet).
- **Security:** Account must belong to the user (otherwise 404).
- **Acceptance:** linked Account balance, Income list, Overview Income all reflect the amount after the mutation
  without a manual refresh; an unlinked Income changes no Account balance.

## J04 — Record an Expense and update the Account balance
- **Mobile:** POSSIBLE. **Entry:** Dashboard → Expenses (inline form) or Receipt confirmation (J11).
- **Actions:** title, amount, currency, date, description, category, optional Account → Add.
- **API:** `POST /expenses` (201).
- **State:** Expense recorded; if linked, an Account debit is projected (balance may go negative); budgets and
  analytics change.
- **Expected:** Expense in list; Account balance decreases; Budget status and Overview Expenses update. A debit can
  push an Account into `allocation_status: "overcommitted"` (reservations are never blocked by real spending).
- **Errors:** 422 currency mismatch with the Account; 422/503 FX; 404 category/Account.
- **Data:** `expenses`, `account_transactions` (if linked).
- **Cache:** the `expense-cache.ts` set: expenses, monthly-summary, category-summary, budget-status,
  spending-trend, category-trend, spending-forecast, financial-overview, income-expense-trend; accounts and account
  transactions when linked.
- **Security:** category and Account ownership enforced.
- **Acceptance:** Account balance equals prior balance minus the expense; an overcommitted Account shows the marker
  without any money having moved.

## J05 — Create and manage a Budget
- **Mobile:** POSSIBLE. **Entry:** Dashboard → Budgets.
- **Actions:** create (name, limit, period weekly/monthly/yearly, start, optional end, optional category); edit;
  delete.
- **API:** `POST/GET/PATCH/DELETE /budgets`; status via `GET /analytics/budget-status`.
- **State:** versioned budget history; status `watch`/`at_risk`/`exceeded`/healthy computed by the backend.
- **Errors:** 409 duplicate budget; 409 immutable field; 409 `Budget end date cannot be set to a date before
  today.`; 409 `Budget is referenced by a financial rule and cannot be deleted.`
- **Data:** `budgets` (+ `budget_versions`).
- **Cache:** `["budgets"]`, `["analytics","budget-status"]`.
- **Acceptance:** status and risk shown are the backend values; deleting a Budget used by a rule shows a message that
  names the cause (**today the raw `detail` is shown and no rules UI exists**).

## J06 — Create a financial Goal
- **Mobile:** POSSIBLE. **Entry:** Goals → Add.
- **Actions:** name, target amount, currency, optional target date → Save.
- **API:** `POST /goals`.
- **State:** Goal `active`, `priority_rank` assigned by the backend (last), `current_amount` 0.
- **Cache:** `["goals"]`, `["analytics","goal-progress"]`.
- **Acceptance:** Goal appears at the end of the priority order; currency immutable once history exists.

## J07 — Reserve money from an Account for a Goal
- **Mobile:** POSSIBLE (safety-floor warning not displayed). **Entry:** Goal detail → Contribute → "Reserve from
  account".
- **Preconditions:** active Goal and active Account in the same currency; `reservable_amount` > 0.
- **Actions:** choose Account (picker shows reservable amount), amount, description → Save.
- **API:** `POST /goals/{id}/transactions` body `{type:"contribution", amount, account_id, client_request_id}`.
  `client_request_id` is **required** when `account_id` is set. Response 201 = created, 200 = idempotent replay.
- **State:** a linked Goal transaction (a reservation) is recorded. **The Account's `current_balance` does not
  change; no Transfer; no AccountTransaction.** `reserved_amount` rises, `reservable_amount` falls.
- **Expected:** Goal `linked_amount` and `allocations[account]` rise; history row labelled Reservation. If the
  Account's projected `reservable_amount` falls below its enabled floor, the **response carries `warnings[]`**
  (code `minimum_unallocated_floor`, floor, projected reservable, projected rule capacity) and the reservation is
  still created.
- **Errors:** 409 `Reservation exceeds the Account's reservable capacity.` (hard rejection, J17); 409 `Archived
  account cannot receive new transactions.`; 409 `Archived goal cannot receive contributions.`; 422 `Goal and Account
  currencies must match.`; 422 effective date rule; 409 `client_request_id has already been used for a different goal
  transaction.`; 404 Goal/Account.
- **Concurrency:** two simultaneous reservations are serialized by the per-user advisory lock L0; the second may
  receive the capacity 409.
- **Data:** one `goal_transactions` row with `account_id`.
- **Cache:** `invalidateGoalTransactionQueries`: goals, goal transactions, goal-progress; **plus accounts** when linked.
  Not invalidated: Account ledger, income, expenses, overview.
- **Security:** both Goal and Account must belong to the user; ownership failures are 404.
- **Acceptance:** after saving, the Account detail shows unchanged balance and larger reserved amount; a dropped
  response retried with the same key creates exactly one reservation; the warning, when returned, is shown and does
  not block.

## J08 — Release reserved money back into Account availability without creating a Transfer
- **Mobile:** POSSIBLE. **Entry:** Goal detail → Withdraw → choose the partition to release (never preselected).
- **API:** `POST /goals/{id}/transactions` body `{type:"withdrawal", amount, account_id, client_request_id}`
  (release from that Account's partition) or without `account_id` (tracked-only withdrawal).
- **State:** a linked withdrawal row; Account `reserved_amount` falls and `reservable_amount` rises. **No Transfer,
  no Account balance change, no bank movement.**
- **Errors:** 409 `Withdrawal exceeds the goal amount reserved against this account.`; 409 `Withdrawal exceeds the
  current goal balance.` (tracked); an **archived** Account's partition stays releasable.
- **Cache:** as J07 (accounts refreshed because linked).
- **Acceptance:** the released amount is available to reserve again; the Transfers list is unchanged.

## J09 — Reorder Goals by priority
- **Mobile:** POSSIBLE. **Entry:** Goals → Priorities.
- **API:** `PUT /goals/priorities` body `{goal_ids:[…]}` — the **complete** ordered set of the user's non-archived
  Goals; response is the reordered Goal list.
- **State:** `priority_rank` rewritten atomically under L0.
- **Errors:** 409 `Goal list is out of date. Reload goals and try again.` (set differs: client refetches);
  409 `Archived goals cannot be ranked.`
- **Cache:** `["goals"]` replaced from the response; nothing else invalidated.
- **Acceptance:** the saved order is the order shown in Goals list and Dashboard; a second device that added a Goal
  causes the stale-set 409 and a refetch, never a partial save.

## J10 — Move money between owned Accounts
- **Mobile:** POSSIBLE. **Entry:** Dashboard → Transfers → New.
- **API:** `POST /account-transfers` `{client_request_id, source_account_id, destination_account_id, amount,
  transfer_date, description?}` (201, or 200 replay); later `POST /account-transfers/{id}/post` for planned;
  `DELETE /account-transfers/{id}`.
- **State:** a past/today date posts immediately (source debit + destination credit); a future date stays `planned`
  (no ledger effect). A transfer is neither Income nor Expense.
- **Errors:** 422 currency mismatch; 422 `Transfer effective date cannot be in the future.`; 409 already posted;
  409 idempotency conflict; 409 archived Account; 409 `Account is referenced by planned transfers. Delete them
  first.` on Account delete.
- **Cache:** `["account-transfers"]`, `["accounts"]`, `["accounts","transactions"]`. Overview/analytics unaffected by design.
- **Acceptance:** total across the two Accounts is unchanged; Income and Expenses are unchanged; a retry after a lost
  response yields one transfer.

## J11 — Upload, review and confirm a receipt
- **Mobile:** POSSIBLE. **Entry:** Dashboard → Receipts upload.
- **API:** `POST /receipts/upload` (multipart) → `POST /receipts/{id}/process` → `GET /receipts/{id}` →
  `POST /receipts/{id}/confirm`.
- **State:** receipt uploaded → processed (OCR fields detected) → confirmed (creates an Expense; confirmation is
  atomic and serialized per receipt).
- **Errors:** 413 too large; 415 unsupported type; 422 empty file; 422 OCR failed; 409 not processable /
  already confirmed / not confirmable; 422 missing confirmation data; 500 storage failure.
- **Cache:** invalidates `["receipts"]` and the full expense set (+ accounts when the expense is linked).
- **Acceptance:** exactly one Expense per receipt even with two devices; a failed process keeps the receipt id so
  the user can retry processing; nothing is written on a failed confirm.

## J12 — Understand monthly Income, Expenses, Net and analytics
- **Mobile:** POSSIBLE. **Entry:** Dashboard card → Financial Overview; Dashboard → Analytics.
- **API:** `GET /analytics/financial-overview?year&month`, `/income-expense-trend?count`, `/monthly-summary`,
  `/category-summary`, `/spending-trend`, `/category-trend`, `/spending-forecast`, `/budget-status`, `/goal-progress`.
- **State:** read-only. `period_state` (`complete`, `in_progress`, `future`) and `data_status` (`complete_data`, `incomplete_data`) describe completeness;
  `unresolved_income_count` / `unresolved_expense_count` flag amounts without a base-currency conversion.
- **Semantics:** Net = Income − Expenses of **recorded** records. It is not bank cash flow, not an Account balance,
  not net worth.
- **Acceptance:** figures equal the backend response; unresolved counts are surfaced, not hidden; transfers and
  reservations never change Income, Expenses or Net.

## J13 — Create and enable a supported financial rule
- **Mobile: NOT POSSIBLE.** **Entry (proposed):** a rules area (does not exist).
- **Backend:** `POST /financial-rules` creates a **draft** of one of four types: `INCOME_ALLOCATION`
  (AUTO or CONFIRM; policy `FIXED_PER_GOAL` or `PERCENT_OF_INCOME_WATERFALL`; 1–50 Goal targets; income sources,
  default excludes `refund`; `cap_at_target`, `allow_partial`), `MINIMUM_UNALLOCATED_FLOOR`,
  `OVERCOMMITMENT_ALERT`, `BUDGET_ALERT`. Then `POST …/enable`.
- **State:** `draft → enabled ⇄ paused`, `enabled|paused → disabled`, `disabled|paused|draft → enabled`. Enabling
  re-validates the Account and Goals (active, same currency) and sets `active_since`; `effective_from` defaults to
  the server date of the **first** enable. Alert rules can be enabled only where the E9A table exists.
- **Errors:** 409 `A rule of this type already exists for this subject.`; 422 `The source Account and every target
  Goal must use the same currency.`; 422 field validation; 409 `The rule's Account or Goal is archived.`; 409 `This
  status change is not allowed from the rule's current status.`; 409 `This rule type cannot be enabled yet.` (alert
  rule while E9A is absent).
- **Data:** `financial_rules`, `financial_rule_goal_targets`. Rules never create bank transfers or payments.
- **Cache (proposed):** a new `["financial-rules",uid]` family; accounts when a floor changes `minimum_unallocated_floor`.
- **Acceptance (when built):** a rule can be created, edited while draft, enabled, paused, disabled, deleted
  (draft/disabled without execution history only); invalid configurations are explained before submit and by the
  backend message after.

## J14 — Preview and manage an AUTO or CONFIRM rule
- **Mobile: NOT POSSIBLE.** **Preview: MISSING in the backend** (`POST /financial-rules/{id}/preview` is specified
  in the contract but absent from OpenAPI). The contract states "AUTO requires a preview before enable" as a UX
  rule with no server enforcement.
- **Backend management:** PATCH while editing (a material edit bumps `version`, supersedes open proposals); pause
  or disable **cancels open proposals** (`rule_inactive`); `GET /rule-executions?rule_id=` for history.
- **Trigger distinction (honest labelling):**
  1. *User-triggered evaluation:* `POST /financial-rules/evaluate` (bounded drain of the caller's own due events).
  2. *Activity-triggered best-effort:* a drain scheduled after each Income write in the web process.
  3. *Unattended scheduled:* the dispatcher Cron. **Not deployed; never observed; do not claim.**
- **Acceptance (when built):** AUTO copy never promises background execution until Gate I; CONFIRM is the default
  safe path; preview (approved, Q3 A; endpoint MISSING, task BE-2) writes nothing.

## J15 — Inspect and confirm or reject a proposal
- **Mobile: NOT POSSIBLE.** **Entry (proposed):** Inbox.
- **API:** `GET /rule-proposals?status&limit&offset`; `GET /rule-proposals/{id}`; `POST …/confirm`; `POST …/reject`.
- **State:** a CONFIRM rule on eligible Income creates an `awaiting_confirmation` execution with planned items, a
  permanent `hold_sequence` (a soft hold on the Account's capacity) and `expires_at` = 168 h after creation.
  Confirm applies the reservations (executed or executed_partial); reject releases the hold.
- **Critical behavior:** confirm and reject are idempotent on terminal proposals and return **HTTP 200 with the
  stored state**. **A 200 does not mean confirmed.** The client must read `status`: `executed`, `executed_partial`
  (success), or `expired`, `rejected`, `cancelled` (not applied). A proposal that fails revalidation is committed as
  cancelled (stale) and the call returns 409 `The proposal can no longer be confirmed and was cancelled (stale).
  Nothing was written.`
- **Errors:** 404 `Rule proposal not found.`
- **Data:** goal transactions (reservations) created on confirm; audit rows.
- **Cache (proposed):** proposals, executions, alerts, goals, goal-progress, accounts.
- **Acceptance (when built):** the result shown always comes from the returned `status`; expiry shows the
  deadline and a clear "expired" end state; confirming never moves bank money.

## J16 — Read and acknowledge an alert
- **Mobile: NOT POSSIBLE.** **API:** `GET /rule-alerts?acknowledged&limit&offset`;
  `POST /rule-alerts/{id}/acknowledge` (idempotent; the first acknowledgement time is kept).
- **Alert kinds:** account episode alerts (`level: breached`) for floor breach or overcommitment (an episode
  resolves when the Account recovers; a later breach is a new alert) and Budget alerts (`watch`, `at_risk`,
  `exceeded`, each level at most once per period, only on escalation).
- **Availability:** `available:false` in the list response means the E9A table is absent (items empty). Alert
  amounts are not stored; the UI must read current figures. Alerts are created at evaluation time (user-triggered
  or dispatcher), not instantly.
- **Errors:** 404 `Rule alert not found.`
- **Acceptance (when built):** acknowledging twice is harmless; `available:false` renders as "not available yet",
  not as "no alerts".

## J17 — Safety-floor warning and hard insufficient-capacity rejection
- **Mobile:** PARTIAL — the rejection is handled, the warning is not displayed.
- **Two different outcomes, never conflated:**
  - **Advisory floor warning (manual reservation):** the reservation **succeeds** (201/200) and the response
    includes `warnings[]` when projected reservable < the Account's enabled floor. Warning-only for manual actions.
  - **Hard rejection:** 409 `Reservation exceeds the Account's reservable capacity.` — nothing is written. Real
    spending can already have overcommitted an Account; that is a status, not an error.
  - **Rules are strict:** a rule allocation respects `rule_capacity` (= reservable − floor − active holds); a
    rule that lacks capacity produces a `skipped`/`blocked` execution or a partial allocation, never a warning.
- **Acceptance (when built):** the warning text names the floor and projected amount from the response and offers
  to keep the reservation; the rejection text never suggests that money can be pulled from the bank.

## J18 — Review rule execution history, failures and recovery paths
- **Mobile: NOT POSSIBLE.** **API:** `GET /rule-executions?rule_id&status&limit&offset` returns executions with
  `items` (planned/applied amounts per Goal) and `audit` rows, plus a capacity snapshot.
- **Statuses:** `awaiting_confirmation`, `executed`, `executed_partial`, `skipped`, `blocked`, `rejected`,
  `expired`, `cancelled`. Reason codes seen in source: `insufficient_capacity`, `nothing_to_allocate`,
  `source_account_archived`, `target_goal_archived`, `currency_mismatch`.
- **Failure and recovery reality:** `POST /financial-rules/evaluate` returns counters (`failed_retryable`, `dead`,
  `blocked`) but **no endpoint lists events or retries a dead event**. `blocked: true` means the user's oldest unfinished
  event is under a live lease or waiting for its backoff, so newer events wait behind it (a `dead` event never blocks).
  Retryable events are retried by later drains with backoff (1 m, 5 m, 30 m, 2 h, 12 h; six attempts, then `dead`).
  A `dead` event has no user-facing recovery. This is a documented gap (see the contract matrix).
- **Acceptance (when built):** every non-success execution displays a plain-language reason mapped from
  `reason_code`; unknown codes fall back to a neutral message; the user is never told a retry will happen unless the
  response says `failed_retryable`.

---

## v1.1 Addendum (VF-MVP-ENG-003)

Approved decisions change or add the following. Everything above remains the audited baseline.

### Changes to existing journeys

| Journey | v1.1 change |
|---|---|
| J01 | Sign-in now has links to registration (J19) and recovery (J20). The expired-session recovery is **P0** (M11): a 401 signs the user out, clears the query cache and returns them to sign-in with a "session ended" message. |
| J03 | After a successful Income create the app calls `POST /financial-rules/evaluate` (debounced) when the user has enabled rules (M10); the Inbox attention indicator may switch to `attention` (no count, rule C7). |
| J07 | The safety-floor warning is **P0** (M08): success plus warning, never an error; an idempotent replay renders whatever warnings the response carries. |
| J12 | Dashboard shows no aggregate balance (Q10). Date-dependent labels state the server date (Q8). |
| J13 | Four rule types ship (Q11). CONFIRM is presented first. Alert rules show "not available yet" until the alerts table exists in that environment. |
| J14 | Preview is an approved backend capability (BE-2). **Enabling AUTO requires a preview of the current rule version**; editing a rule invalidates its preview. The preview is hypothetical (C8): labelled as an example from a sample income, no side effect, never listed as an outcome. Copy rule C1 binds all AUTO text. |
| J15 | Inbox is client-composed (Q9): proposals (`awaiting_confirmation`), unacknowledged alerts, recent failed/blocked executions; opening it calls evaluate first. Outcome is read from `status` (C5). |
| J16 | Unchanged; `available:false` is a distinct state. |
| J18 | Execution history is **P1** (M07). No recovery endpoint exists; the UI explains counters only. |

### J19 — Register a new account
- **Mobile:** NOT YET (M14a, P0). **Entry:** sign-in screen → Create account.
- **Preconditions:** staging/production Supabase project allows sign-up (settings UNKNOWN until recorded).
- **Actions:** email, password (and confirmation field) → Create account.
- **API calls:** Supabase Auth `signUp` (not FastAPI). No FastAPI call until a session exists.
- **State transitions:** no account → (if email confirmation is enabled) *confirmation pending* → confirmed → sign-in
  → session. If confirmation is disabled, a session may start immediately.
- **Expected:** the user lands on an empty Dashboard; first FastAPI call creates no rows except what normal use
  creates (default categories are ensured lazily).
- **Errors:** password policy failure (message from the project policy), invalid email, rate limited, network
  failure. **The same neutral message is shown whether or not the email is already registered** (C6).
- **Data changes:** a Supabase Auth user only.
- **Cache:** none; the cache must be empty at start (cleared on any prior sign-out).
- **Security:** no password or token logged or persisted outside Supabase storage; redirect URL uses the app-unique
  scheme (B9); no account-existence leak; rate-limit behavior observed on staging.
- **Acceptance:** drill on iOS and Android: register → (confirm) → sign in → empty-state Dashboard; a second
  registration with the same email shows the neutral message and reveals nothing.

### J20 — Recover a forgotten password
- **Mobile:** NOT YET (M14b, P0). **Entry:** sign-in → Forgot password.
- **Actions:** enter email → Send link → open the emailed link on the device → app opens the reset screen → enter a
  new password → submit → sign in.
- **API calls:** Supabase Auth `resetPasswordForEmail`, then session establishment from the link (the client has
  `detectSessionInUrl: false`, so the app handles the link explicitly), then `updateUser({ password })`.
- **State transitions:** signed out → link requested → link opened (recovery session) → password updated → signed in
  or sent to sign-in.
- **Errors:** link expired/invalid/already used (clear state with a way to request a new link); password policy
  failure; rate limited; app not installed or link opened on another device (documented behavior, not a crash).
- **Data changes:** Supabase Auth credentials only.
- **Security:** the request step shows the same message for known and unknown emails (C6); the recovery session is
  not used for FastAPI data screens until the password is set; tokens never logged; the link scheme is app-unique.
- **Acceptance:** drill on both platforms against staging: complete recovery end to end; expired link shows the
  expired state; a reused link does not log the user in.
