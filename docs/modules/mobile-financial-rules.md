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

**Deferred:** Preview and AUTO enable (F5); Inbox, proposals, alerts list, acknowledge and mounting the evaluation
trigger (F4); execution history and reasons (F6). Device and staging acceptance is pending.
