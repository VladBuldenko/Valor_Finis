# VF-020F4 — Inbox, proposals and alerts: implementation design sheet (for owner approval)

Status: **APPROVED by the owner (D1-D5, exactly as proposed); implemented in VF-020F4.**
This approves the F4 implementation specification only. It is not acceptance of the broader DR-9 release gate, and
J15/J16 staging and device acceptance remain PENDING.
No approved high-fidelity specs for R-08/R-09/R-10 exist in the repository (inventory lists them; the state matrix has
one paragraph for R-08). This sheet fixes the behaviour from the approved decisions (Q9, C1-C8), the F4 roadmap row and
journeys J15/J16, and uses the F3 / Goals / Accounts screens as the visual baseline. No new package, no backend change.

## 1. Navigation and routes (`app/(app)/`)

| Route | Screen | Surface |
|---|---|---|
| `inbox/index.tsx` | Inbox | R-08 |
| `inbox/proposals/[id].tsx` | Proposal detail (confirm / reject) | R-09 |
| `inbox/alerts.tsx` | Alerts list (acknowledge) | R-10 |

Dashboard: one button "Inbox" next to "Rules" carrying the attention indicator (section 4). Feature code in
`src/features/financial-rules/` (inbox files prefixed `inbox-`), routes stay thin.

## 2. Data model (one shared source for Dashboard and Inbox)

Three independent queries, all through the F1 service and per-user keys, none blocks another:

| Source | Request | Bound |
|---|---|---|
| Proposals | `GET /rule-proposals?status=awaiting_confirmation&limit=20` | first page + at most 2 more (`offset` 20, 40) = **max 3 requests** |
| Alerts | `GET /rule-alerts?acknowledged=false&limit=20` | same cap of 3 |
| Executions | `GET /rule-executions?limit=5` | **1 request**, informational only |

A source is **complete** only when its last response satisfies `offset + items.length >= total` (backend metadata, never
a local total). If the cap is reached with items remaining, the source is *incomplete*. Alerts with `available:false`
are *unavailable* (never "empty"). A pure `deriveInboxIndicator` and the Inbox read the same query data
(`useInboxData`), so they cannot disagree.

## 3. Inbox screen (R-08)

Opening the Inbox requests one evaluation (section 6), then shows three sections, each with its own loading,
empty, error-with-Retry state (a failed source never blanks the others):

1. **Waiting for you** (proposals): card = rule name, planned total + currency, "Expires <date/time>", opens R-09.
   Empty: "Nothing is waiting for you." Incomplete (cap reached): "Showing the first N. More are waiting." (N = items shown,
   not a total).
2. **Alerts**: card = level label + `alertMessage`, opens "Alerts" (R-10); only unacknowledged are listed here.
   `available:false` -> "Alerts are not available yet." (never an empty state). Empty: "No alerts need your attention."
3. **Recent activity** (last 5 executions, informational): status label + rule name-free summary
   (`executionStatusInfo` + `reasonText`). **Not actionable**, no link (full history is F6). A failed/blocked execution
   here never changes the indicator.

Pull-to-refresh re-requests all sources (and may re-request evaluation, subject to the cooldown).

## 4. Dashboard indicator (C7): `attention` | `clear` | `unknown`

Inputs: per source `{status: loading|error|success, items, complete, available}` and `evaluation: not_attempted|
pending|failed|succeeded`. Necessary sources: proposals, alerts, and evaluation **only if attempted in this session**.
Executions never participate.

- `attention`: at least one loaded actionable item (proposal `awaiting_confirmation` and not past `expires_at`, or alert
  with `acknowledged_at === null`). Wins over any failed/loading/incomplete other source.
- `clear`: every necessary source is success, complete, available, and contains no actionable item (evaluation, if
  attempted, has succeeded).
- `unknown`: everything else (failed, loading, incomplete/cap reached, alerts unavailable, evaluation failed or pending).

Dashboard button text is the fixed word "Inbox" with a state marker beside it: attention "Needs attention", clear
"Up to date", unknown "Status unknown" (text, not colour). The accessible name differs per state ("Inbox, needs
attention" / "Inbox, up to date" / "Inbox, status unknown"). No number and no "unread" anywhere.

## 5. Proposal detail (R-09) and decisions

Shows only backend data: rule name, source income (amount, currency, received date), Account/currency when present,
planned Goal allocations (`goal_name`, `planned_amount`, and for `executed_partial` also `applied_amount`), planned total,
"Available for this suggestion now: <confirm_capacity>" when returned, "Expires <time>", status chip. Standing
explanation: "A suggestion holds part of your Account's capacity for rules. Nothing is reserved until you confirm."

Actions (only while `awaiting_confirmation`): **Confirm** and **Decline**, each behind a confirmation dialog
("Reserve these amounts for your Goals? This sets money aside inside the Account; it does not move money in your bank." /
"Decline this suggestion? Nothing will be reserved."). One request at a time (guard); never auto-repeated.

Outcome comes from the **returned `status`** (C5), via the F1 `proposalOutcome`: executed -> "Reserved for your Goals";
executed_partial -> shows planned vs applied per Goal; rejected / expired / cancelled -> "Nothing was reserved" and
never styled as success; `awaiting_confirmation` returned -> "still waiting". A confirm that returns a non-executed
status states that it differs from what was asked.

Stale (HTTP 409 `rule_proposal_stale`): the backend may have committed the cancellation, so the screen **refetches the
proposal and the related data** and then shows the authoritative state ("This suggestion is out of date and was
cancelled. Nothing was reserved."). A timeout / lost connection on Confirm or Decline is an **unknown outcome**: the
screen says so, refetches the proposal, and shows the authoritative status; it never re-sends by itself.

Cache after a decision: F1 `proposal_decided` set for the returned status (confirm executed: proposals, executions,
goals, goal-progress, accounts; rejected/expired/cancelled: proposals, executions, accounts). Income, Expenses, Budgets
and Transfers are not touched.

## 6. Alerts (R-10)

List of alerts with a filter "To review" (`acknowledged=false`, default) / "Reviewed" (`acknowledged=true`), paged by
`limit=20` with a "Load more" button (offset from `items.length`; no auto-paging). Row: level label (`alertLevelInfo`),
message (`alertMessage`; deleted subject -> neutral "A deleted Account/Budget"), created date, and separate lines
"Reviewed <date>" and "Resolved <date>" (resolved = the Account recovered; independent of acknowledgement). Action
"Mark as reviewed" (POST acknowledge; idempotent: a replay returns the stored first-acknowledgement time, the response is
the authority). Invalidates alerts only. `available:false` -> "Alerts are not available yet." Errors via the F1 mapper.

## 7. Evaluation trigger mounting

One `RulesEvaluationHost` inside the signed-in subtree that is already keyed by the QueryClient generation, so it is
created once per session/client and unmounted (disposed) on sign-out or rotation. It owns: one trigger
(`createRulesEvaluationTrigger`, user id, client, `isCurrent` = live client and same user), one AppState subscription
via `watchForeground` (no other listeners), and a small context exposing `requestEvaluation(reason)`.

- Session ready -> `foreground` request once; background -> active -> `foreground`.
- Inbox open -> `inbox_open` (cooldown 30 s applies).
- Successful Income create -> `income_recorded` (one trailing run if a run is active). Wired by calling the context from
  the Income create success handler only.
- Results/failures flow through F1: stale results discarded, failures reported (the Inbox shows "Could not check your
  rules just now. Try again." and the indicator treats a failed attempted evaluation as unknown), no POST retry.
- Copy never says rules run while the app is closed (C1).

## 8. States and accessibility

Every section/screen: loading (`ActivityIndicator` with label), empty, loaded, error with a "Retry" button scoped to that
source, saving (disabled + busy), conflict/stale (live-region message). All Pressables have `accessibilityRole` and a label
including current state; alerts/errors use a polite live region; status is never colour-only; targets >= 44 pt.
Copy follows C1-C8 and the F1 forbidden-copy scan (it also reads JSX text).

## 9. Decisions (all approved as recommended)

| # | Question | Recommendation |
|---|---|---|
| D1 | Approve the routes, the three Inbox sections and the Dashboard marker wording (section 4)? | Approve |
| D2 | Pagination bound: first page of 20 plus at most 2 more per source (max 3 requests); beyond that the indicator stays `unknown`? | Approve |
| D3 | Recent activity: last 5 executions, informational only, no link until F6? | Approve |
| D4 | Mount the evaluation host once for the signed-in subtree (session ready, foreground, Inbox open, Income create)? | Approve |
| D5 | Alerts list filters "To review" / "Reviewed" with manual "Load more"? | Approve |

Out of scope: Preview UI / AUTO activation (F5), full execution history (F6), backend or migrations, push
notifications, any unattended-scheduling claim. J15/J16 acceptance on staging/devices stays PENDING.
