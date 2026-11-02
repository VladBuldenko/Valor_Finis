# Smart Rules mobile foundation (VF-020F1)

Code: `apps/mobile/src/features/financial-rules/`. Foundation only: types, API service, query keys, invalidation sets,
error/status/reason mappers, the evaluation trigger and the forbidden-copy check. There is no screen yet (F2-F6 own
those) and nothing in the app mounts the trigger yet.

## Files

| File | Purpose |
|---|---|
| `financial-rule.types.ts` | Wire types mirroring `services/api/app/modules/financial_rules/*_schemas.py`. Discriminated unions on `rule_type`; union value lists exported as `as const` arrays; `assertNever`. Money is always a decimal **string**. |
| `financial-rule-requests.ts` | Pure path / query / body construction. Validates UUID ids, `limit` (1..100), `offset` (>= 0) and the preview sample amount (positive, <= 2 decimals) before anything is sent. |
| `financial-rule.api.ts` | `createFinancialRulesApi(request)`: the 14 endpoints over an injected transport. |
| `financial-rule.service.ts` | `financialRulesService` = the API bound to `apiRequest` (the only transport). |
| `financial-rule-query-keys.ts` | Typed key registry; every key is `[family, userId, ...]`. |
| `financial-rule-invalidation.ts` | `planRuleInvalidation` (pure) and `applyRuleInvalidation`. |
| `financial-rule-errors.ts` | `describeRuleError`: BE-1 `code` first, safe fallbacks. |
| `financial-rule-presentation.ts` | Status, lifecycle, reason-code, alert-level, preview and proposal-outcome mappers. |
| `financial-rule-evaluation-trigger.ts` | Debounced, bounded `POST /evaluate` trigger and foreground watcher. |
| `financial-rule-copy.ts`, `financial-rule-forbidden-copy.ts` | Wording and the forbidden-phrase rules (C1-C3, C7, C8). |

## Endpoints (method, path, response)

| Service method | HTTP | Response |
|---|---|---|
| `listRules` | `GET /financial-rules` | `FinancialRule[]` (plain array) |
| `createRule` | `POST /financial-rules` | `FinancialRule` (201, always a draft) |
| `getRule` / `updateRule` / `deleteRule` | `GET` / `PATCH` / `DELETE /financial-rules/{id}` | rule / rule / 204 |
| `enableRule` / `pauseRule` / `disableRule` | `POST /financial-rules/{id}/enable \| pause \| disable` | `FinancialRule` |
| `evaluateRules` | `POST /financial-rules/evaluate` | `RuleEvaluationResult` |
| `previewRule` | `POST /financial-rules/{id}/preview` | `RulePreview` (hypothetical, read-only) |
| `listProposals` | `GET /rule-proposals?limit&offset&status` | `{items,total,limit,offset}` |
| `getProposal` / `confirmProposal` / `rejectProposal` | `GET` / `POST .../confirm` / `POST .../reject` | `RuleProposal` |
| `listAlerts` | `GET /rule-alerts?limit&offset&acknowledged` | `{items,total,limit,offset,available}` |
| `acknowledgeAlert` | `POST /rule-alerts/{id}/acknowledge` | `RuleAlert` |
| `listExecutions` | `GET /rule-executions?limit&offset&rule_id&status` | `{items,total,limit,offset}` |

Only GETs may be retried, and only by the transport (bounded, transient failures). Every POST/PATCH/DELETE is sent
exactly once. A timeout or lost connection on a mutation is shown as "outcome unknown" (`describeRuleError(...,
{ mutation: true })`), never as a plain failure.

After confirm/reject the **returned `status`** decides the result (`proposalOutcome`), never the HTTP code (C5).
`available: false` on the alert list means the alerts schema is missing in that environment; it is not "no alerts".

## Query keys

`["financial-rules", user, "list" | "detail", id]`, `["rule-proposals", user, "list", {status,limit,offset}]`,
`["rule-proposals", user, "detail", id]`, `["rule-alerts", user, "list", {acknowledged,limit,offset}]`,
`["rule-executions", user, "list", {rule_id,status,limit,offset}]`,
`["rule-previews", user, ruleId, ruleVersion, sampleAmount, sampleSource]`. A key cannot be built without a user id.

## Invalidation sets (prefixes; nothing is cleared)

| Event | Invalidated |
|---|---|
| rule created | rules |
| rule edited, name/description only | rules |
| rule edited, material (`version` + 1) | rules, that rule's previews, proposals, executions, accounts |
| rule deleted | rules, that rule's previews |
| enable | rules, that rule's previews |
| pause / disable | rules, that rule's previews, proposals, executions, accounts |
| proposal decided, returned `executed` / `executed_partial` | proposals, executions, goals, goal-progress, accounts |
| proposal decided, returned `rejected` / `expired` / `cancelled` | proposals, executions, accounts |
| alert acknowledged | alerts |
| evaluated, nothing processed | none |
| evaluated, otherwise | proposals, executions; + alerts if created/resolved > 0; + goals, goal-progress, accounts if `outcomes` is non-empty |
| Goal or Account changed | previews, proposals |
| income recorded | previews |

Expenses, Income, Budgets, Transfers and the other analytics are never touched.

## Evaluation trigger

One instance per signed-in user and QueryClient generation (create it where the session client is created; dispose it
when that client rotates). Reasons: `foreground`, `inbox_open` (F4), `income_recorded`. Debounce 750 ms; foreground and
inbox_open also wait out a 30 s cooldown measured from the last run's start. Never two runs at once; income recorded
during a run earns one trailing run. Signed-out or stale instances ignore every request; a result arriving after the
session changed is discarded. A failure is reported once and never retried. `watchForeground` fires only on a
transition to `active`; the first run after sign-in is requested by the session owner. Evaluation is user-triggered,
not an unattended scheduler (copy rule C1).

## Not done here

No screens, no mounting of the trigger, no React hooks. Later slices mount the trigger and consume the keys.

## F2: floor warning and Account capacity (VF-020F2, M08/M09)

No backend change. Every amount is the backend's decimal string, rendered as returned; the client does no money
arithmetic and never predicts a warning.

- **Account type** (`accounts/account.types.ts`): `minimum_unallocated_floor`, `active_rule_holds`, `rule_capacity`
  (all decimal strings; `rule_capacity` is signed).
- **Account detail** (`accounts/account-detail-screen.tsx`, rows from `account-capacity-presentation.ts`): Available to
  reserve, Minimum unallocated floor, Active rule holds, Available for rules, each in the Account's own currency with a
  one-line explanation and an accessible name. The floor is shown as a threshold that removes no money; a hold is not a
  completed reservation; the balance does not change when money is earmarked. A negative `rule_capacity` is shown as
  returned with a "Below zero" hint (also in the accessible name). There is no cross-Account total.
- **POST response** (`goals/goal.types.ts`, `goal.service.ts`): `GoalTransactionCreated = GoalTransaction & { warnings?:
  GoalTransactionFloorWarning[] }`; the historical GET type is unchanged. A warning has `code`
  `"minimum_unallocated_floor"`, `minimum_unallocated_floor`, `projected_reservable_amount`, `projected_rule_capacity`.
- **Goal detail** (`goals/goal-transaction-warning.ts`, used by the mutation's `onSuccess`): 201 and the idempotent 200
  replay are handled identically. The form is reset, then the warning (if the backend sent one) is shown in an `Alert`
  BEFORE the cache refresh is awaited, so a slow refetch cannot lose it; then Goals, the Goal's transactions, Goal
  Progress and (linked only) Accounts are invalidated as before. The warning never changes success into an error, and
  nothing re-sends the request (same `client_request_id` and retry behaviour as before). `warnings: []` or no field shows
  nothing; a tracked contribution gets none because the backend sends none.

Acceptance on physical devices and staging is **pending** (not run in this task).

## F3: rules list and editor (VF-020F3, M01/M02, R-01..R-06)

Design: [vf-020f3-design-sheet.md](../mvp/vf-020f3-design-sheet.md) (approved D1-D5). Visual standard: the Goals screens.

**Navigation** (Expo Router, `app/(app)/rules/`, thin routes over `src/features/financial-rules/`):

| Route | Screen | Surface |
|---|---|---|
| `/rules` | `RulesScreen`: list, loading / empty / loaded / error + Retry, pull-to-refresh, "New rule" | R-01 |
| `/rules/new` | `RuleCreateScreen`: choose one of four types, then the editor (saved as a draft) | R-02..R-05 |
| `/rules/[id]` | `RuleDetailScreen`: stored settings + lifecycle actions | R-06 |
| `/rules/[id]/edit` | `RuleEditScreen`: the same editor prefilled | R-02..R-05 |

Entry: a plain "Rules" button on the Dashboard (no count, no badge).

**Editors:** income allocation (Account, mode with CONFIRM first and preselected, fixed/percent policy, percent, 1-50 Goals
with amount or optional cap, income sources, stop-at-target, partial, start date); minimum floor (Account, amount);
overcommitment alert (Account); budget alert (Budget). Logic is pure in `financial-rule-form.ts` (state, shape
validation, discriminated create request, changed-fields-only PATCH plan; switching to the fixed policy sends
`percent: null`; descriptions and dates clear with `null`). Inputs survive a failed save; Save is guarded against double
submission (`createSubmitGuard`); nothing is retried automatically; a timeout on a save is reported as "outcome unknown".

**Lifecycle** (`financial-rule-actions.ts`): Turn on / Pause / Turn off / Edit / Delete exactly as the status machine
allows (delete only for Draft or Off). Status changes go only through `createRuleActionRunner`, which re-checks
availability before any request. Pause, Turn off and Delete ask for confirmation. Backend 409/422 map through
`describeRuleError` (stable code first); alert rules show "Alerts are not available yet in this environment" when the
alerts schema is missing.

**AUTO gate (until F5):** AUTO can be saved as a configuration on a draft or Off rule, but an AUTO allocation rule cannot
be turned on (the button is disabled with an explanation and the runner refuses). A rule that is On or Paused can only be
set to "Ask me first", enforced in the editor, in validation and in the PATCH builder, so editing cannot bypass the gate.
F5 adds Preview and removes the gate.

**Cache:** F1 invalidation sets plus Accounts when a floor rule is edited, deleted or changes status (the Account read
model carries the enabled floor and rule capacity). The pickers share the Accounts, Goals and Budgets cache entries.

**Notice before saving:** editing an On or Paused allocation rule in any field except name, description or order shows
"Changing this rule replaces any suggestions that are still waiting for you." (F1 `isMaterialRuleEdit` now treats
`execution_order` as non-material, matching the backend.)

**Deferred (at F3):** Preview and AUTO enable (F5); Inbox, proposals, alerts list, acknowledge and mounting the evaluation
trigger (F4); execution history and reasons (F6) - all since delivered. Device and staging acceptance is pending.

## F4: Inbox, proposals and alerts (VF-020F4, M04-M06, R-08..R-10)

Design: [vf-020f4-design-sheet.md](../mvp/vf-020f4-design-sheet.md) (approved D1-D5). No backend change, no new endpoint.

**Routes** (`app/(app)/inbox/`): `/inbox` (`InboxScreen`), `/inbox/proposals/[id]` (`ProposalDetailScreen`),
`/inbox/alerts` (`AlertsScreen`). The Dashboard has an "Inbox" button with the indicator marker.

**Inbox sources** (`use-inbox-data.ts`, three independent queries with their own loading / empty / error + Retry):
proposals `status=awaiting_confirmation`, alerts `acknowledged=false`, each fetched by `fetchBoundedPages` (page size 20,
at most 3 requests = one initial page plus two more; completeness only from the backend's `total`), plus the last 5
executions (informational rows with no action, never part of the indicator; a "See all activity" link opens the full history, F6). Keys: `inboxProposals`,
`inboxAlerts`, `inboxExecutions` (separate from the plain list keys); the Alerts screen's manual feed uses `alertFeed`
so manual paging can never create a `clear`.

**Indicator** (`inbox-data.ts` `deriveInboxIndicator`, one derivation shared by Dashboard and Inbox through
`useInboxData` and `inboxIndicatorPresentation`):
- `attention`: a loaded (successful source) open proposal not past `expires_at`, or an unacknowledged alert. A failed,
  loading or incomplete other source cannot cancel it; items of a failed source are not trusted.
- `clear`: proposals and alerts successful, complete and available, nothing actionable, and evaluation either not
  attempted or fully succeeded.
- `unknown`: everything else (failed/loading/incomplete/cap reached, alerts `available:false`, evaluation failed,
  pending or incomplete).
Markers are words ("Needs attention", "Up to date", "Status unknown") with distinct accessible names; no number, never
"unread".

**Proposal detail** (`inbox-proposal-actions.ts` `decideProposal`): one POST; Confirm/Decline behind dialogs; the result
is the returned `status` (`proposalOutcome`); partial shows planned and applied amounts. A stale 409 or an ambiguous
failure (timeout, network, unreadable 2xx, 5xx) triggers one GET of the proposal and a refresh before anything is
claimed; the POST is never resent. Invalidation: the F1 `proposal_decided` set for the returned status, applied only while
the session is still current.

**Alerts**: "To review" / "Reviewed" filters, manual "Load more" (`nextAlertOffset`), reviewed and resolved shown
separately, a deleted subject shown neutrally, `available:false` -> "Alerts are not available yet.", acknowledge is
idempotent and invalidates alerts only.

**Evaluation host** (`rules-evaluation-provider.ts`, bound in `rules-evaluation-host.tsx`, mounted once in
`app/_layout.tsx` inside `SessionScope`): one F1 trigger and one AppState subscription per session / QueryClient
generation, disposed on unmount (rotation or sign-out). Requests: session ready and background -> active
(`foreground`), Inbox open (`inbox_open`), successful Income create (`income_recorded`). F1 debounce (750 ms),
cooldown (30 s), one trailing run, discarded stale results and no POST retry apply. `useRulesEvaluation()` exposes
`request` and the session's evaluation status (`not_attempted | pending | succeeded | incomplete | failed`; a blocked,
failed or dead drain, or failed alert evaluation, is `incomplete`, never a clean success). Rules are checked when the app
opens or refreshes and after income is recorded; nothing here claims unattended execution.

**Pending:** J15/J16 on staging and physical devices, including the three-trigger exactly-once scenario (gate BR-12).
**Deferred:** none in F4. (Preview and AUTO activation: see F5; execution history: see F6 below.)

## F5 - Rule preview and safe AUTO activation (VF-020F5)

Design: `docs/mvp/vf-020f5-design-sheet.md` (D1-D5 approved). The backend contract is `docs/mvp/vf-be2-preview-contract.md`
(BE-2, merged); the backend is unchanged.

**Screen** `app/(app)/rules/[id]/preview.tsx` -> `rule-preview-screen.tsx`. Entry: the "Example" button on the Rule
detail for `INCOME_ALLOCATION` rules (any status); "Turn on (example first)" for an AUTO rule opens it. The user types an
amount (no default; shape-validated by `buildPreviewRequest`) and optionally a source, and asks with "Show example" (never
automatic). `requestRulePreview` sends one `POST .../preview`, never retried, and drops an answer that is for another
rule version, not hypothetical, or arrives after the session changed. `rule-preview-view.ts` turns the response into text
without any arithmetic: every amount is the backend's decimal string; Goal rows keep the server order; outcomes
(`full|partial|skipped|blocked`), effects (`would_apply|would_hold|none`), `reason_code`, `source_selected_by_rule:false`
and the standing limitations (sample income not recorded, other rules not simulated, real-event eligibility not simulated)
are all shown; every state is headed "Example only".

**AUTO authorization** (`preview-authorization.ts`): transient client state, never sent to the server. A proof exists
only after the successful preview was displayed (`markViewed` runs from an effect after render, once Goals/Accounts have
settled) and is scoped to user + rule id + rule version + exact sample. It is revoked by: a material edit, delete or
status change of the rule (F1 invalidation), a different sample, a Goal/Account cache change (a fingerprint of both
families), the preview entry being replaced/invalidated, and a new QueryClient (sign-out / user change gives a fresh,
empty store; the old one is unreachable). A hand-built proof is rejected (proofs are issued only by the store).

**Two independent enforcement points.** UI: `turnOnBlockReason` disables the control with a readable reason unless every
fact holds. Runner: `createRuleActionRunner(api, gate).run(rule, "enable", {proof, isCurrent})` refuses an AUTO
allocation enable without a valid proof, re-reads the rule (`getRule`), refuses a changed version, mode or status
(`ActionStaleError`, authorization revoked), re-checks the session after the read, and only then sends one POST. A runner
without a gate fails closed. `isAutoEnableBlocked` is unchanged; `getRuleActionAvailability(rule, {autoAuthorized})` opens
the AUTO enable only for an authorized state. CONFIRM needs no preview and is not re-read. The editor still offers only
CONFIRM for enabled/paused rules, so a PATCH cannot turn an enabled CONFIRM rule into AUTO.

**Activation** (`auto-activation.ts`): a deliberate dialog (internal Goal reservations without per-income confirmation, no
bank transfer, checked on open/refresh and after income, the example was hypothetical) then `activateAutoRule`. Results:
`activated` (backend status shown), `unexpected_status`, `needs_new_preview`, `not_checked` (re-read failed, nothing
sent), `failed`, `unknown_resolved` / `unknown_pending` (ambiguous POST: never resent; one read-back), `session_changed`.
Invalidation: the F1 `rule_status_changed` set, only while the session is current. The preview is an advisory snapshot:
the backend has no expected-version token, so a change between the re-read and the POST is not excluded, and the copy
does not claim otherwise.

**Pending:** J14 AUTO acceptance on staging and physical iOS/Android.

## F6 - Execution history (VF-020F6)
**Screen** `app/(app)/rules/history.tsx` -> `rule-history-screen.tsx` (+ `rule-history-card.tsx`), registered as
`rules/history` ("History"). Entries (navigation only): the Rules list "History" button, the Inbox "Recent activity"
"See all activity" link, and "History" on an `INCOME_ALLOCATION` rule's detail (`?rule_id=<id>`; a malformed id shows a
notice and all rules, it never throws). It reads `GET /rule-executions` through `financialRulesService.listExecutions`
and the Rules/Goals lists for names; nothing else. It calls no mutation and never asks for an evaluation (it only reads
the coarse evaluation status for one line of context).

**Data** (`use-execution-history.ts`, `execution-history-data.ts`): one `useInfiniteQuery` per user and filter pair, key
`["rule-executions", user, "history", {rule_id, status, limit: 20}]` (`financialRuleKeys.executionHistory`, under the
executions family so existing F1 invalidation refreshes it; distinct from `executionList` and the Inbox's
`inboxExecutions`). Page offsets are the pageParams, not key parts. "Load more" is manual: the next offset is the number
of rows RECEIVED, an empty page ends paging, rows are de-duplicated by id (first occurrence wins). The list is newest
first and offset-paged, so a run recorded while paging can shift rows down; the screen says newer runs can appear and
offers pull-to-refresh, and does not claim a snapshot or a gap-free view. `deriveHistoryState` is the single place that
chooses loading / error / empty / list and the footer (load more, loading, next-page error, end, stalled), so a failure is
never shown as "no history" and a failed later page keeps the loaded rows.

**Presentation** (`execution-history-view.ts`): all eight statuses by text; amounts are the server's decimal strings
(planned and applied per Goal in stored order; a null `applied_amount` is "Not applied", never a number; no totals);
`source_received_at` (a calendar date) is formatted from its own parts, never through `Date`; the recorded capacity
figures are labelled "then" and shown without the income currency when the run was blocked for `currency_mismatch`.
Reasons: the ten codes the backend persists (`insufficient_capacity`, `nothing_to_allocate`, `source_account_archived`,
`target_goal_archived`, `currency_mismatch`, `superseded`, `stale`, `source_changed`, `source_deleted`, `rule_inactive`)
via `reasonText`; `income_source_not_selected` is mapped but is never stored on an execution (preview only); `rejected`
and `expired` carry no reason and are explained from the status; an unknown code gets the neutral text and is never
echoed. Only known audit codes are translated (with a known actor); `details` and ids are never shown. Rule and Goal
names are looked up now and labelled "(current name)"; a missing one is described as no longer listed only once the
list has loaded.

**Limits.** History shows recorded executions only. No evaluation counters are shown (the app does not retain them), no
dead or stuck event is listed, and there is no retry or recovery action: the backend offers none. The Inbox attention
indicator is unaffected (history is not an input to it).

**Pending:** J18 acceptance on staging and physical iOS/Android.
