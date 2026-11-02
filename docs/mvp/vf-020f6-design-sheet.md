# VF-020F6 — Execution history (R-11 / M07 / J18): implementation design sheet (for owner approval)

Status: **PROPOSED — awaiting owner approval.** No UI code exists on this branch; only this sheet.
Approval covers the R-11 implementation design only. It is not acceptance of the broader MVP release; J18 acceptance on
staging and physical iOS/Android stays PENDING until actually tested.
Scope: mobile only. The backend list (`GET /api/v1/rule-executions`) is merged and authoritative.
Baseline: `main` `69266a62f943cfc46ec88c4f91411408908b1bef` (F1–F5 merged; PR #110). Older audit text that calls F1–F5
"missing" is historical.
No owner-approved high-fidelity R-11 specification exists (the handoff index lists R-11 as "Ready" for design, the screen
spec gives one row), so this sheet is the specification.
Visual reference: F3/F4 conventions (`SafeAreaView` + `ScrollView`, `card`, `statusText`, `helperText`/`errorText`,
chips, `RefreshControl`, `OptionPicker`). No new package.
Reused as-is: `financialRulesService.listExecutions(filters, signal)`, `listExecutionsRequest`,
`financialRuleKeys.executionList`, `executionStatusInfo`, `reasonText`, `describeRuleError`, `applyRuleInvalidation`
(the `executions` family), `SessionQueryClient`, `COPY`.

## What the backend actually does (verified in code, not from docs)

| Fact | Source | Consequence for the UI |
|---|---|---|
| List is newest first (`created_at desc, id desc`), `limit` 1–100 (default 20), `offset`, filters `rule_id`, `status`; `total` is the filtered count | `rule_execution_router.py`, `list_executions` | Offset paging over a list that grows at the head: a new execution shifts later pages down, so the same row can reappear on the next page. **Dedupe by id; next offset = items received, never `page × limit`.** |
| `reason_code` is persisted only as: `insufficient_capacity`, `nothing_to_allocate`, `source_account_archived`, `target_goal_archived`, `currency_mismatch` (planner) and `superseded`, `stale`, `source_changed`, `source_deleted`, `rule_inactive` (cancellation). | `rule_allocation_planner.py`, `rule_execution_repository.CANCEL_*` | 10 persisted codes. `income_source_not_selected` is **never stored** (it is only counted in evaluation `not_eligible`, and returned by preview); it stays in `reasonText` but cannot appear in history. |
| `skipped`/`blocked` always carry a reason; `cancelled` always carries one; **`rejected` and `expired` carry none (null)**; `executed`, `executed_partial`, `awaiting_confirmation` carry none | `_append_terminal` calls, `decide()` | A null reason is normal for `rejected`/`expired` and is explained from the **status**, not shown as "no detail". An unknown non-null code uses the neutral fallback and is never echoed. |
| A stale **confirm** answers HTTP 409 with `rule_changed`/`account_unavailable`/`goal_unavailable` text, but the stored reason is `stale` | `_stale_reason`, `CANCEL_STALE` | History maps only the stored `stale`. |
| `blocked` rows have **no items**; `skipped/insufficient_capacity` has items with `applied_amount` null; `executed_partial` has an item for every planned Goal and `applied_amount` is set only for the Goals that fit; `awaiting_confirmation` items hold only what fits | `decide()`, `_execute_rule` | Null `applied_amount` is shown as the words "Not applied", **never `0.00`**. No totals are shown (the response has none; the client does no arithmetic). |
| Capacity snapshot fields are the Account's figures at run time; for `currency_mismatch` the Account currency can differ from `source_currency` | `_execute_rule`, `blocked_reason` | Capacity figures carry the income currency only when the reason is not `currency_mismatch`; otherwise they are shown without a currency code and labelled "Account currency". |
| `source_received_at` is a date (`YYYY-MM-DD`), `created_at`/`decided_at` are instants | `RuleExecutionResponse` | A date-only string is formatted from its own parts. `new Date("2026-11-02")` is UTC midnight and shows the previous day in negative-offset zones. |
| Audit codes written: `proposed`, `applied`, `applied_partial`, `skipped`, `blocked`, `confirmed`, `rejected`, `expired`, `cancelled`, `source_changed`, `source_deleted`; actors `system` / `user`. `source_changed`/`source_deleted` on a **completed** execution are annotations only; the execution is not altered. | `rule_execution_service.py`, `rule_execution_repository.py`, `rule_proposal_service.py` | Known codes get plain-language lines; unknown codes are dropped (not shown raw). `details` is never rendered. |
| The execution id equals the proposal id; the response has **no `expires_at`** and the stored `awaiting_confirmation` state can lag actual expiry | `get_proposal_for_update`, lazy `expire_due_proposals` | History cannot say whether an awaiting row is still open; it points to the Inbox and never offers confirm/reject. |
| The mobile evaluation provider keeps only a coarse status (`succeeded`/`incomplete`/`failed`), **not** the counters | `rules-evaluation-provider.ts`, `statusOfResult` | Counters are not available to the history screen (see D4). |
| A rule that has run cannot be deleted; Goals can be archived | `rule-detail-screen.tsx` copy, planner | Rule/Goal names in history are *current* names and a missing one is handled. |

## D1 — Route and entry points

| Route | Screen |
|---|---|
| `app/(app)/rules/history.tsx` → `rule-history-screen.tsx`, optional search param `rule_id` | Execution history (R-11) |

Static `rules/history` is registered in the layout (title "History") and wins over `rules/[id]`.
Entries (navigation only, no mutation): **Rules list** "History" button; **Inbox → Recent activity** "See all activity"
link (the Inbox's own 5-item query, key and indicator are untouched); **Rule detail** "History" button for
`INCOME_ALLOCATION` rules → `/rules/history?rule_id=<id>`.
A `rule_id` that is not a UUID (hand-typed deep link) does not throw: the screen shows all rules with the line "That rule
link was not valid, so all rules are shown." — it never silently queries something else.
The list response already carries items and audit, so there is **no per-execution GET and no detail route**; each card
expands in place. Recommended: **approve.**

## D2 — Filters and pagination

- **Rule filter**: `OptionPicker` "All rules" + the user's `INCOME_ALLOCATION` rules by *current* name (from the cached
  Rules query). **Status filter**: "All statuses" + the 8 statuses as radio chips with text labels.
- Page size **20**, explicit **"Load more"** button, never automatic. `total` is metadata for "Showing N of T" and for
  deciding whether more exist; next offset = number of items received so far; an empty page while `total` says more
  stops (end state) instead of looping.
- Data: `useInfiniteQuery` keyed by `financialRuleKeys.executionList(userId, { rule_id, status, limit: 20 })` — the same
  pattern as the F4 Alerts feed. Filter values are in the key, so a filter change is a different cache entry and starts
  at page 1; a late response for the previous filter writes only to its own entry. **Interpretation to confirm:** the
  *offset* of each page lives in the infinite query's `pageParams` (stored with the cached data), not in the key — a
  literal "offset in the key" would need one `useQuery` per page. I recommend the infinite query (single refetch path,
  precedent in F4, later-page failure keeps loaded pages natively). Say so if you want per-page keys instead.
- `queryFn` passes TanStack's `signal` to `listExecutions` (abort on unmount/filter change). The key is distinct from the
  Inbox's `inboxExecutions`, so neither feed can replace the other's data.
Recommended: **approve.**

## D3 — History presentation

Card (collapsed): text **status label** (reuse `executionStatusInfo`; never colour alone) · "Income {source_amount}
{source_currency}, received {date}" · "Ran {created_at}" (+ "Decided {decided_at}" when present) · one plain-language line
(status explanation + `reasonText`). Tap toggles expansion (`accessibilityRole="button"`, `accessibilityState.expanded`).
Expanded details:
- **Rule**: current rule name, labelled "Rule (current name)", plus "Recorded version N". Rules list loading/failed →
  "Rule"; list loaded and id absent → "A rule that is no longer in your list". Never claims the name was the historical one.
- **Goals** in stored `position` order: current Goal name ("Goal" while unknown; "A Goal that is no longer in your active
  list" once the Goal list is loaded without it), "Planned {planned_amount}", "Applied {applied_amount}" or "Not applied",
  and "Recorded as a Goal reservation" when `goal_transaction_id` exists (an earmark, C2; never "transfer"/"deposit").
- **Recorded figures when it ran**: "Available to reserve then", "Minimum unallocated amount then", "Held for pending
  suggestions then" (COPY labels + "then"); a null field shows "Not recorded".
- **What happened** (audit, oldest first): translated lines for known codes, e.g. "Suggested to you", "Reserved for your
  Goals", "Partly reserved", "Skipped", "Could not run", "You confirmed", "You declined", "Expired", "Cancelled",
  "The income was changed after this ran" / "…deleted after this ran. This record shows what happened at the time."
  Actor `user` → "You", `system` → "Valor Finis"; unknown code or actor → line omitted. No `details`, ids, event ids or JSON.
- Footer on every expanded card: the C2 sentence ("A reservation sets money aside inside an Account for a Goal. It does not
  move any money in your bank.").

Status explanations (from actual statuses, plus the stored reason when present): `executed` "The full planned amount was
reserved." · `executed_partial` "Only part of the plan fit, so part was reserved." · `skipped` "The rule ran but reserved
nothing." · `blocked` "The rule could not run." · `rejected` "You declined this suggestion. Nothing was reserved." ·
`expired` "This suggestion was not confirmed in time. Nothing was reserved." · `cancelled` "This suggestion was cancelled.
Nothing was reserved." · `awaiting_confirmation` "A suggestion was made and is waiting for a decision. Open the Inbox
to see whether it is still open." (link to `/inbox`; no confirm/reject here, and the Inbox indicator is not read or changed.)
All amounts are the backend's decimal strings, unchanged. Recommended: **approve.**

## D4 — Failures, evaluation counters and recovery

- History shows only **recorded executions**. A standing note: "This list shows rule runs that were recorded. Income that
  has not been checked yet, or could not be checked, does not appear here."
- **No evaluation counters are shown.** The counters (`processed`, `deferred`, `failed_retryable`, `dead`, `blocked`)
  describe one drain and the app does not retain them; showing them would require changing the F4 provider, which is out of
  scope. Only the existing coarse status is used: `incomplete` → "Some income could not be checked completely in this
  session, so recent income may be missing from this list."; `failed` → "The last check did not complete, so recent income
  may be missing from this list." `succeeded`/`not_attempted`/`pending` → no line. Nothing infers dead events from history.
- **No retry action, no promise of retry**, no "failed" status and no recovery text; the backend has no list of dead
  events and no retry endpoint (documented gap). Viewing or refreshing history **never** calls `evaluate`.
Recommended: **approve** (if you want the counters shown, that is a separate, small F4-provider change I would propose
as its own task).

## D5 — States, accessibility, refresh, session ownership

| State | Presentation |
|---|---|
| initial loading | spinner "Loading history" |
| empty (success, 0 items) | "No rule runs yet" (filtered: "No runs match these filters" + "Clear filters"); never shown for an error |
| populated | cards + "Showing N of T" + "Load more" |
| loading next page | the button shows a spinner and is disabled; loaded cards stay |
| end of history | "That is everything." (only when metadata says all were received) |
| refresh | pull-to-refresh refetches the loaded pages only (no evaluate) |
| first-load error | mapped message + **Retry**; list is not shown as empty |
| later-page error | loaded cards stay; inline mapped message + **Retry** for that page |
| refetch error with cached data | cached cards stay, with the error line |
| missing rule / Goal | neutral labels above |
| signed out / session rotation | query disabled; the per-user client is replaced, so user A's pages cannot render for user B |

Accessibility: every filter chip is a radio with a text label and `checked` state; cards are buttons with
`expanded` state and a full spoken summary; errors are `alert` with live region; "Load more" is a button with an
`accessibilityLabel` naming progress ("Load more, showing 20 of 57"); no state is conveyed by colour alone.
Read-only: the history code imports no mutation or `evaluate` call (a test enforces this). Existing invalidation for
rule/proposal/evaluation events already targets the `rule-executions` family, so no change to `planRuleInvalidation`.
Recommended: **approve.**

## Planned tests (outline)

Pure: status/reason/audit mappers (every status, all 10 stored codes + the preview-only code, null vs unknown, known/unknown
audit codes and actors), planned vs applied vs null, nullable capacity, current-vs-historical names (loaded / loading /
failed / missing), date-only formatting in negative-offset zones, page merge (dedupe, next offset from received count,
empty page, total drift), filter→key mapping. Mounted: initial/empty/failed/populated/next-page/later-page failure and
retry, filter change while in flight, stale user A response after user B signs in, sign-out, refresh, no mutation or
evaluate call, expandable card roles and labels, forbidden-copy scan (no retry/transfer/"failed" status/dead-event
wording), Inbox indicator unchanged. Negative controls on ownership, paging, dedupe, null-as-zero and outcome mapping.

## Decisions requested

| # | Question | Recommendation |
|---|---|---|
| D1 | `/rules/history` + optional `rule_id`; entries from Rules, Inbox "See all activity", Rule detail; in-place expansion, no new endpoint | Approve |
| D2 | Rule/status filters, 20 per page, manual "Load more", infinite query with offsets in `pageParams` (confirm or ask for per-page keys) | Approve |
| D3 | Card/expanded content, current-name labelling, "Not applied" for null, no totals, audit translation, no raw JSON/ids | Approve |
| D4 | Recorded executions only; no counters, no retry, coarse session status line only | Approve |
| D5 | State table, accessibility, read-only guarantee, user-scoped caching | Approve |

Out of scope: backend, migrations, dispatcher, dead-event listing or retry, F4 provider/indicator changes, retained
evaluation counters, Preview/AUTO changes, MF3/MF4, BE3, QA1, device/staging acceptance.
