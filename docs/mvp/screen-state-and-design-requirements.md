# Screen States and Design Requirements (VF-MVP-ENG-001, Part 6)

Date: 2026-10-27. Basis: `main` @ `08d985c030a38823fe43863c806d90bbc86e97b4`. Audience: UI/UX designers and the
mobile engineering lead.

This document specifies **what each state must communicate and enable**. It deliberately defines **no colors,
fonts, spacing or visual style**. It never invents a backend guarantee: where the API offers nothing for a state,
the state says so.

How to read the tables. **Client today**: `YES` implemented, `PARTIAL`, `NO`. **Backend support**: what the API
actually provides. A state marked "n/a" does not apply to that surface.

## 1. Global state catalog

| State | What the backend actually provides | What the client does today | Design requirement |
|---|---|---|---|
| Initial / empty | Empty arrays (`[]`) for lists; `available:false` for alerts without the E9A table | Static "No X yet." text per list; filter-aware on Accounts and Goals | Explain what the object is and offer the single next action; never imply an error. |
| Loading | n/a | `ActivityIndicator` per query | Keep layout stable; do not show stale numbers as fresh. |
| Loaded | Data | Rendered from cache | Show server figures only. |
| Refreshing | TanStack background refetch | **No pull-to-refresh; no focus refetch config** | Provide an explicit refresh gesture and a visible "updating" cue that does not hide existing data. |
| Submitting | n/a | Button spinner, `isPending` guard on most forms | Disable repeat submit; keep entered values; never lose input on failure. |
| Success | 2xx | Mostly navigation or silent cache update | Confirm the **outcome in domain words** (e.g. "Reserved", never "Transferred"). |
| Validation failure | 422 `{"detail":[…]}` or rule 422 `{"detail":"…"}`; client-side validators exist per form | `Alert` with first message | Field-level messages near the field; keep the form. |
| Authentication failure | 401 from FastAPI on a bad/expired token | **None** — thrown `Error`, no sign-out or re-login | Required: a defined session-expired state with sign-in and preserved navigation intent. (M11) |
| Permission / ownership failure | **There is no 403.** A foreign or missing object is 404 | 404 text from `detail` | Treat as "no longer available"; never reveal whether it belongs to someone else. |
| Network failure | n/a | TanStack default retries; static "Unable to load …" | Distinguish offline from server error; offer Retry (today there is none). |
| Timeout | None defined | **No client timeout**; request can hang | Required: a bounded wait with a retry state. (M11) |
| Server failure | 500; 503 for FX provider (`Currency conversion is temporarily unavailable…`) | Raw detail in Alert | Plain language; mark whether data was or was not saved (for 5xx the client cannot know: say so and offer "check before retrying" for non-idempotent actions). |
| Idempotent replay | Goal transactions and transfer create return **200** (vs 201) with the original object | Handled for both via attempt keys; success path is the same | Show the original outcome; do not show "duplicate" as an error. |
| Concurrent edit conflict | 409 for stale Goal priority set and stale proposals; **no version/ETag on any PATCH** (rule `version` is server-managed; `FinancialRuleUpdate` has no expected-version field) | Priorities screen refetches on stale 409 | Where there is no conflict token, last write wins: design must not promise conflict detection. |
| Financial capacity rejection | 409 `Reservation exceeds the Account's reservable capacity.`; rules produce `skipped`/partial executions | Mapped for manual reservations | Show the figure that limits the action (from the Account), never a computed one. |
| Archived / disabled object | 409 `Archived account cannot receive new transactions.`, `Archived goal cannot receive contributions.`; rule `status` `paused`/`disabled` | Pickers exclude archived Accounts; releases from archived partitions allowed | Archived objects stay readable and explain why actions are unavailable. |
| Insufficient data | `data_status: incomplete_data`, `unresolved_*_count > 0`, `savings_rate_percent: null`, `period_state: future/in_progress` | Overview honors `data_status`/`period_state` | Say what is missing; never show 0 for unknown. |
| Expired / stale proposal | Status `expired`; 409 stale on confirm (cancelled, nothing written) | n/a (no UI) | Required distinct end states: expired, stale-cancelled, rejected, executed. |
| Accessibility | n/a | ~10 files carry any `accessibilityLabel`/`Role`; most controls unlabeled | See section 4. |

## 2. Surface-by-surface requirements

### 2.1 Sign-in and session
| State | Show | Actions | Recovery | Backend data | Client today |
|---|---|---|---|---|---|
| Initial | Email, password | Sign in | — | Supabase | YES |
| Submitting | Disabled controls, progress | — | — | — | YES |
| Auth failure (bad credentials) | Supabase message in plain words | Retry | Re-enter | Supabase | YES (Alert) |
| Session restoring | Full-screen wait | — | — | AsyncStorage | YES (spinner) |
| Session expired mid-use | "Your session ended" + sign in | Sign in | Return to the previous screen after sign-in | 401 | **NO** |
| Offline at launch | Cached session still unlocks app; data fails to load | Retry | — | none | PARTIAL (no offline cue) |

### 2.2 Dashboard
| State | Show | Actions | Recovery | Backend data | Client today |
|---|---|---|---|---|---|
| Loading / loaded | Per-section loaders; month summary, Income/Expenses/Net, category spend, budget status, goals | Navigate | — | 7 queries | YES |
| Section error | Per-section message | Retry that section | Refetch that query | — | PARTIAL (message, no retry) |
| Empty (new user) | "No budgets yet", "No goals yet" | One primary next step | — | `[]` | PARTIAL |
| Rules signal | Open proposals count, unacknowledged alerts, "rules evaluated at <time>" | Open Inbox | — | proposals, alerts, `evaluate` | **NO** (M06) |
| Stale month | Date used for "this month" | — | — | device month vs server date | NO (known follow-up) |

The Dashboard must not present an aggregate "total balance" or "safe to spend" (decision Q10).

### 2.3 Accounts (list, detail, create/edit)
| State | Show | Actions | Recovery | Backend data | Client today |
|---|---|---|---|---|---|
| Loaded | Name, type, currency, `current_balance`, reserved, "Available to reserve", `allocation_status` | Open, create, archive view | — | `AccountResponse` | YES |
| Overcommitted | A non-color marker plus explanation: reservations exceed what the Account can cover **after real spending**; no money moved | Release reservations | Navigate to Goals | `allocation_status`, `reservable_amount` (negative) | YES (marker) |
| Negative balance | Plain statement; balance may legitimately be negative | — | — | `negative_balance` | NO (not shown) |
| Below floor | "Reservable is below your safety floor" with floor and reservable | Edit floor rule | Rules | `minimum_unallocated_floor` | **NO** |
| Holds | Amount held by open proposals (`active_rule_holds`) and rule capacity | Open proposals | Inbox | `active_rule_holds`, `rule_capacity` | **NO** |
| Archived | Read-only ledger; reactivate | Reactivate | — | `status` | YES |
| Delete / currency change blocked | Reason: history, planned transfer, reservation, or rule reference | Archive instead | — | 409 text | PARTIAL (raw text) |
| Manual adjustment submitting/validation | Direction, amount, date | Save | Keep form | 422/409 | YES |

### 2.4 Income and Expense entry
| State | Show | Actions | Recovery | Client today |
|---|---|---|---|---|
| Submitting | Disabled save | — | — | YES |
| Success | The recorded item; if linked, the Account balance change is reflected | Add another | — | YES |
| Currency mismatch with Account (422) | "This Account uses a different currency" | Choose another Account / unlink | Keep form | PARTIAL (raw text) |
| FX unavailable (422/503) | "Currency conversion unavailable; try again shortly" (503) or "cannot be converted for this date" (422) | Retry | Keep form | PARTIAL |
| Account list failed | "Account link will stay unchanged" | Save without link | — | YES |
| Rule side effect (new) | After Income: if a rule produced a proposal or execution, a quiet cue linking to the Inbox | Open Inbox | — | **NO** |
| Concurrent edit | None provided (no version) | — | last write wins | n/a |

### 2.5 Budgets
Loaded shows `limit`, spent, status, risk (`watch`, `at_risk`, `exceeded`), pace/projection from the backend. Risk
must be conveyed with text/icon, not color alone. Delete blocked by a rule shows the rule reference reason (today:
raw `detail`, no link). Create/edit errors keep the form. Client today: YES except the rule-reference explanation.

### 2.6 Goals: list, detail, reserve and release
| State | Show | Actions | Recovery | Backend data | Client today |
|---|---|---|---|---|---|
| Loaded | Target, `current_amount`, `tracked_amount`, `linked_amount`, allocations by Account, priority | Open, reorder, create | — | `GoalResponse` | YES |
| Reserve submitting | "Reserving" (never "transferring") | — | — | `client_request_id` | YES |
| Reserve success | "Reserved X from <Account>. Your account balance did not change." | Done | — | 201/200 | PARTIAL (no balance-unchanged statement) |
| Reserve success with floor warning | Success **plus** the warning: floor, projected reservable after this reservation | Keep / Release | Release flow | `warnings[]` | **NO** (M08) |
| Hard rejection (capacity) | "This Account has X available to reserve" using the Account's fresh `reservable_amount`; refresh Accounts | Reduce amount, pick another Account | Refetch accounts | 409 | YES |
| Archived Goal / Account | Why the action is unavailable | Unarchive / pick another | — | 409 | YES |
| Release | Explicit partition choice (never preselected); success says "Released. No transfer was made." | — | — | 201/200 | PARTIAL |
| Partition shortfall | "Only X is reserved against this Account" | Adjust | — | 409 | YES |
| Idempotent replay | Same success as original | — | — | 200 | YES |
| Dropped response | Retry uses the same key while the form is open | Retry | Reopen form loses key (known residual) | — | PARTIAL |
| Currency mismatch | "Goal and Account currencies must match" | Pick another | — | 422 | PARTIAL |

### 2.7 Goal priorities
Loaded list with up/down controls and Save; unsaved-order indicator; Save disabled when unchanged or pending.
Stale-set 409: "Your goals changed elsewhere", reload the list and discard the draft (YES). Archived Goals are not
rankable. Empty: "No goals to prioritize yet." (YES). Accessibility: reorder controls carry labels (YES, 6 labels);
a non-gesture alternative to drag must be preserved.

### 2.8 Transfers
Create: source ≠ destination, same currency, date (a future date means *planned*; the UI must say that a planned
transfer changes no balance until posted). Success states differ: posted ("Moved X from A to B") vs planned
("Scheduled; no balance change yet"). Post requires an explicit effective date not in the future. Errors: already
posted (409), currency mismatch (422), future effective date (422), archived Account (409), idempotency conflict
(409, close and reopen form). Delete of a planned transfer is allowed. Client today: YES, with raw error text.
A transfer must never be described as Income, Expense or a Goal action.

### 2.9 Receipts
| State | Show | Actions | Recovery | Client today |
|---|---|---|---|---|
| Picking / uploading / processing | Distinct progress per step | Cancel before upload | — | YES |
| Upload errors | too large (413), unsupported (415), empty (422), storage (500) | Retry/choose another | — | YES (raw text) |
| OCR failed (422) | "We could not read this receipt" | Retry processing or enter manually | Keep receipt id | PARTIAL |
| Review | Detected merchant, amount, currency, date as **editable suggestions** | Confirm | — | YES |
| Already confirmed | Link to the Expense | Open Expense | — | YES |
| Confirm failure (currency mismatch, data missing) | Reason; stays editable | Fix and retry | Refetch receipt | YES |
| Receipts list | **None exists** | — | — | **NO** (M13) |

### 2.10 Financial Overview and Analytics
`period_state` (`complete`, `in_progress`, `future`) and `data_status` (`complete_data`, `incomplete_data`) must be
visible. `unresolved_income_count` / `unresolved_expense_count` explain missing base-currency conversion.
`savings_rate_percent: null` renders as "not available", never 0. Net is labelled "Income minus Expenses
recorded", never "cash flow" or "balance". Month navigation limits (future months) follow `period_state`.
Client today: YES.

### 2.11 Rules list and editor (MISSING in client)
| State | Show | Actions | Backend data / limitation |
|---|---|---|---|
| Empty | What a rule is (internal earmarking; never moves bank money) and the first rule to create | Create | `[]` |
| Loaded | Name, type, status (`draft`, `enabled`, `paused`, `disabled`), mode AUTO/CONFIRM, order, target summary | Open, enable, pause | `GET /financial-rules` (unpaginated) |
| Draft | Clearly not active | Edit, enable, delete | — |
| Enabling | Revalidation result | — | 409/422 messages |
| Enable blocked | Reasons: subject archived, currency mismatch, alert rule while the alerts table is absent ("This rule type cannot be enabled yet.") | Fix the cause | text only |
| Paused / disabled | Open proposals were cancelled | Re-enable | — |
| Delete blocked | Only draft/disabled and no history; the backend text is the same for both causes | Disable instead | X9 |
| Duplicate | "A rule of this type already exists for this subject." | Edit existing | 409 |
| Editing an enabled rule | Material edits supersede open proposals | Confirm intent | contract |
| Concurrent edit | No conflict token | n/a | last write wins |
| Archived subject | Rule shows the archived Account/Goal | Pick another | 409 |
| Insufficient data | A rule with no eligible past income says nothing has run yet | — | executions empty |

AUTO versus CONFIRM wording must make two things explicit: both create **internal Goal reservations only**; and
until Gate I is passed, execution happens "when the app evaluates (app open, refresh, or after you record income)",
not "automatically while the app is closed".

### 2.12 Rule preview (BLOCKED)
No backend dry run exists. Until decision Q3 is made, the design must not show a preview result. If approved, the
state set is: loading, result (planned items, capacity used, partial/skip reasons), "nothing would happen" (with
reason), failure, and "preview is not a promise: figures can change before income arrives".

### 2.13 Inbox, proposals, alerts, executions (MISSING in client)
| Surface / state | Show | Actions | Recovery | Backend data |
|---|---|---|---|---|
| Inbox empty | "Nothing needs your attention" | — | — | `[]` from three endpoints |
| Inbox loaded | Open proposals (soonest `expires_at` first is a design choice), unacknowledged alerts, recent failures | Open, confirm, reject, acknowledge | Refresh = call `POST /evaluate` then refetch | proposals, alerts, executions |
| Alerts unavailable | "Alerts are not available yet" (`available:false`) — **not** "no alerts" | — | — | `RuleAlertListResponse.available` |
| Evaluating | "Checking your rules" | — | — | `evaluate` summary |
| Evaluate partial | `alerts_failed:true` or `blocked:true` shown as "Some checks could not run; they will retry" only when `failed_retryable` > 0 | Retry later | — | counters |
| Proposal awaiting | Rule name, source Income, planned items per Goal, **hold** on the Account, `expires_at` countdown, `confirm_capacity` | Confirm, reject | — | `RuleProposalResponse` |
| Proposal submitting | Disabled actions | — | — | — |
| Confirm → executed / executed_partial | Success with applied vs planned (partial explained) | View Goal | — | `status`, `items[].applied_amount` |
| Confirm → expired | "This proposal expired on <date>; nothing was applied" | Dismiss | — | `status: expired` (HTTP 200) |
| Confirm → 409 stale | "Your balances changed; the proposal was cancelled and nothing was written" | Refresh | refetch | 409 text |
| Confirm → rejected / cancelled (200) | Terminal state explanation | — | — | `status` |
| Idempotent replay | Same terminal outcome | — | — | 200 + stored state |
| Alert | Level (watch, at risk, exceeded, breached), subject name, period; resolved vs acknowledged shown separately | Acknowledge | — | `RuleAlertResponse` |
| Alert subject deleted | `subject_name` may be null → neutral label | — | — | `subject_name: null` |
| Execution history | Per execution: status, plain-language reason, items, capacity snapshot | Filter by rule/status | — | `RuleExecutionResponse` |
| Dead / stuck events | **No data is available to explain them**; only counters | — | — | none (gap) |

### 2.14 Safety-floor warning and capacity rejection (patterns)
- *Floor warning* (advisory): shown after a **successful** manual reservation; states the floor, the projected
  reservable amount, and that nothing was blocked. Offers Release as the way back. Never styled as an error.
- *Capacity rejection* (hard): shown for a **failed** reservation; states the limiting `reservable_amount`; nothing
  was written. Never suggests moving money from the bank.
- *Overcommitment* (status): an Account state, not an error; may arise from real spending.

## 3. Cross-surface behavior requirements

1. Every amount comes from the response; the client does not add, subtract or round money.
2. After any mutation, the affected families must refresh (see the matrix); the screen must not show a pre-mutation
   figure as current.
3. Every destructive or irreversible action (delete, confirm, reject) shows its consequence and requires a
   deliberate second step; confirm of a proposal states that it creates internal reservations only.
4. Error text must be mapped from `status` + exact `detail` to plain language with a safe fallback; raw
   "API request failed: …" is never shown.
5. All dates shown for "today"-dependent rules say they use the server date.
6. Archived and disabled objects remain visible with the reason actions are unavailable.

## 4. Accessibility requirements (behavioral, not visual)

| Requirement | Detail | Today |
|---|---|---|
| Names and roles | Every control has an accessible name and role; icon-only controls never rely on glyph alone | Few controls labeled (10 files) |
| Non-color status | Risk (watch/at risk/exceeded), overcommitted, breached, and rule status are conveyed by text or icon as well as color | Risk text is color-styled; verify |
| Dynamic text size | Layouts survive large system text; no truncated amounts or statuses | Unverified |
| Touch targets | Minimum comfortable target for list actions and reorder controls | Unverified |
| Screen reader announcements | Async outcomes (submit success/failure, evaluation done, proposal state) are announced | No live-region usage found |
| Focus management | After submit, modal close, or error, focus moves to the result or first invalid field | Unverified |
| Reorder without drag | Up/down controls remain | YES (priorities) |
| Money reading | Amounts include currency and sign in a form a screen reader reads correctly | Unverified |
| Reduced motion | No essential information in animation | Unverified |
| Language | English strings only today; copy must be centralized for later localization | Strings inline |

---

## v1.1 Addendum (VF-MVP-ENG-003)

### Auth surfaces (A-01..A-03)
| State | Show | Actions | Recovery | Backend/Auth data |
|---|---|---|---|---|
| Sign-up initial | Email, password, confirm | Create account, back to sign-in | — | Supabase |
| Submitting | Disabled controls | — | — | — |
| Confirmation pending | "Check your email" (same text whether or not the email was already registered, C6) | Resend, back | Open mail app | project setting UNKNOWN |
| Password policy failure | The policy requirement in plain words | Edit | Keep email | Supabase message |
| Rate limited | "Try again later" | Wait | — | Supabase |
| Network failure | Offline vs server wording | Retry | Keep input | — |
| Forgot password request | Email field; the same confirmation message always (C6) | Send, back | — | Supabase |
| Reset link opened | New password, confirm | Submit | — | recovery session |
| Link expired/invalid/used | Clear state | Request a new link | — | Supabase |
| Reset success | "Password updated" then signed in or to sign-in | Continue | — | — |
| Session expired (all screens) | "Your session ended" | Sign in; return to previous screen | — | 401 (M11) |

### Pagination states (Expenses, Income) after BE-3
Loading first page; loaded; loading more (existing rows stay visible); end of list; page error with retry that keeps
loaded rows; empty; refresh resets to the first page. Totals shown only from the response.

### Server-date label (Q8)
Date-dependent surfaces (transfers, goal transactions, overview, budget dates) show "Server date: <date>" or an
equivalent approved label wherever "today" changes the outcome.

### Rule preview (R-07), now in scope
States: loading; result (planned amount per target Goal, partial/skip reasons mapped from codes, capacity figures:
reservable, floor, holds, rule capacity); "nothing would happen" with reason; stale (rule edited after preview, must
re-preview); failure (code-mapped); not previewable (rule status/type). Copy: "Preview uses your current balances; actual results can
differ when income arrives." Enabling AUTO is disabled until a current preview was shown.
Hypothetical presentation (rule C8): the result is headed as an example ("If you received <sample income>"), shows the sample
income and the server date it was computed for, never uses the words "reserved", "done" or "will" for its amounts, and
never appears in the Inbox, history or any list that holds real outcomes. A preview is not stored on the server; the "current
preview shown" flag for AUTO gating is client state tied to the rule version. A shown preview is not a guarantee of a later
execution and AUTO enabling copy says so (rule C1).

### Inbox composition states (R-08)
Opening the Inbox triggers evaluate then loads the three sources independently. Each source has its own loading,
empty, error-with-retry state; one failing source does not blank the others. The Dashboard entry shows the attention
indicator (`attention` / `clear` / `unknown`, rule C7): no number, no word "unread"; `clear` only when every source loaded
completely; any failed or partial source gives `unknown`, never `clear`. Design all three states.
