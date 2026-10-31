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
