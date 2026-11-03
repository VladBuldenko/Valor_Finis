# VF-MOB-REFRESH-RETRY (MF-3) — per-screen checklist

Status: **implemented and locally verified; device and staging acceptance (gate BR-7) PENDING.**
Baseline: `main` `a732ee913bf019420efcccaa9975d3450b6d8742` (F1–F6 merged). Gap: GAP-09. Roadmap: MF-3.
Every route file under `apps/mobile/app/` appears exactly once below; `src/features/mf3-screen-coverage.test.ts` reads
this table and fails when a route is missing, when a "yes" is not backed by the screen's source, or when a row is not
`done`.

## How to read the table
- **Class**: `list` (collection), `dashboard` (several sections), `detail` (one object, sometimes with a history list),
  `form` (create/edit/flow; reads data only to render), `none`.
- **Before** is the state found on `main`. **Loading / Empty / Error+Retry / Refresh** are the final state.
- **Refresh**: `yes` = pull-to-refresh re-reads the data shown. `n/a` = no list or a form whose typed input a refresh
  must not touch; those still get Retry on every load failure.
- **Optional data**: a secondary read whose failure must not hide the primary data (shown as a partial notice with its own
  Retry).
- Shared pieces: `components/query-states.tsx` (`QueryBoundary`, `LoadError`, `InlineError`, `RetryAction`),
  `lib/query-view.ts` (pure phases and wording), `lib/screen-refresh.ts` (coordinated, de-duplicated refresh),
  `lib/app-focus.ts` (foreground bridge).

| Route file | Screen source | Class | Queries | Before | Loading | Empty | Error + Retry | Refresh | Optional data | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| `(app)/index.tsx` | `features/dashboard/dashboard-screen.tsx` | dashboard | monthly summary, financial overview, category summary, budget status, budgets, goals, goal progress, Inbox sources | spinner; text-only error that replaced retained data; no refresh | per section | per section | per section, Retry, retained data kept | yes (all 7 + Inbox sources) | budgets (currency), goal progress | done |
| `(app)/accounts/index.tsx` | `features/accounts/accounts-screen.tsx` | list | accounts | text-only error | yes | filter-aware | yes | yes | — | done |
| `(app)/accounts/new.tsx` | `features/accounts/account-create-screen.tsx` | form | none | no reads | n/a | n/a | n/a | n/a | — | done |
| `(app)/accounts/[id]/index.tsx` | `features/accounts/account-detail-screen.tsx` | detail | accounts, account transactions | text-only errors | yes | transactions | account + history | yes (form input untouched) | — | done |
| `(app)/accounts/[id]/edit.tsx` | `features/accounts/account-edit-screen.tsx` | form | accounts | text-only error | yes | not found | yes; background failure no longer blanks the form | n/a (form) | — | done |
| `(app)/income/index.tsx` | `features/income/income-screen.tsx` | list | income, accounts | text-only error | yes | yes | yes | yes | accounts (names) | done |
| `(app)/income/new.tsx` | `features/income/income-create-screen.tsx` | form | accounts | text-only error | yes | n/a | accounts picker Retry | n/a (form) | accounts | done |
| `(app)/income/[id]/edit.tsx` | `features/income/income-edit-screen.tsx` | form | income, accounts | text-only errors | yes | not found | income + accounts Retry | n/a (form) | accounts | done |
| `(app)/expenses/index.tsx` | `features/expenses/expenses-screen.tsx` | list | expenses, categories, accounts | text-only errors | yes | yes | all three, Retry | yes (form input untouched) | accounts | done |
| `(app)/expenses/[id].tsx` | `features/expenses/expense-detail-screen.tsx` | form | expenses, categories, accounts | text-only errors | yes | not found | all three, Retry | n/a (form) | accounts | done |
| `(app)/transfers/index.tsx` | `features/transfers/transfers-screen.tsx` | list | transfers, accounts | text-only error | yes | yes | yes | yes | accounts (names) | done |
| `(app)/transfers/new.tsx` | `features/transfers/transfer-create-screen.tsx` | form | accounts | text-only error | yes | fewer than two | yes, stale-list notice has Retry | n/a (form) | — | done |
| `(app)/goals/index.tsx` | `features/goals/goals-screen.tsx` | list | goals, goal progress | text-only error | yes | filter-aware | yes | yes | goal progress | done |
| `(app)/goals/new.tsx` | `features/goals/goal-create-screen.tsx` | form | none | no reads | n/a | n/a | n/a | n/a | — | done |
| `(app)/goals/[id]/index.tsx` | `features/goals/goal-detail-screen.tsx` | detail | goals, goal transactions, accounts | text-only errors | yes | transactions | goal, accounts, history | yes (form input untouched) | accounts | done |
| `(app)/goals/[id]/edit.tsx` | `features/goals/goal-edit-screen.tsx` | form | goals | text-only error | yes | not found | yes | n/a (form) | — | done |
| `(app)/goals/priorities.tsx` | `features/goals/goal-priorities-screen.tsx` | form | goals | text-only error that replaced an order being edited | yes | — | yes; only when nothing is loaded | n/a (draft order) | — | done |
| `(app)/budgets/index.tsx` | `features/budgets/budgets-screen.tsx` | list | budgets, budget status | text-only errors | yes | yes | yes | yes | budget status | done |
| `(app)/budgets/new.tsx` | `features/budgets/budget-create-screen.tsx` | form | categories | text-only error | yes | n/a | categories Retry | n/a (form) | — | done |
| `(app)/budgets/[id]/edit.tsx` | `features/budgets/budget-edit-screen.tsx` | form | budgets, categories | text-only errors | yes | not found | both | n/a (form) | — | done |
| `(app)/categories/index.tsx` | `features/categories/categories-screen.tsx` | list | categories | text-only error | yes | yes | yes | yes | — | done |
| `(app)/categories/new.tsx` | `features/categories/category-create-screen.tsx` | form | none | no reads | n/a | n/a | n/a | n/a | — | done |
| `(app)/categories/[id]/edit.tsx` | `features/categories/category-edit-screen.tsx` | form | categories | text-only error | yes | not found | yes | n/a (form) | — | done |
| `(app)/analytics/index.tsx` | `features/analytics/analytics-screen.tsx` | dashboard | forecast, trend, category trend | text-only errors | per section | per section | per section | yes | — | done |
| `(app)/overview/index.tsx` | `features/analytics/financial-overview-screen.tsx` | dashboard | financial overview, income/expense trend | "Try again" existed; a refresh failure hid data | per section | n/a | per section (kept) | yes | — | done |
| `(app)/receipts/[id].tsx` | `features/receipts/receipt-review-screen.tsx` | form | receipt, categories, accounts | text-only errors | yes | not found | all three, Retry | n/a (form) | accounts | done |
| `(app)/receipts/upload.tsx` | `features/receipts/receipt-upload-screen.tsx` | form | none | write flow with its own retry text | n/a | n/a | n/a (write; never auto-retried) | n/a | — | done |
| `(app)/rules/index.tsx` | `features/financial-rules/rules-screen.tsx` | list | rules | F3: refresh + Retry | yes | yes | yes | yes | — | done |
| `(app)/rules/new.tsx` | `features/financial-rules/rule-editor-screen.tsx` | form | accounts, goals, budgets (form data) | F3: Retry | yes | n/a | yes | n/a (form) | — | done |
| `(app)/rules/[id]/index.tsx` | `features/financial-rules/rule-detail-screen.tsx` | detail | rule, accounts, goals, budgets | F3: refresh + Retry | yes | n/a | yes | yes | accounts, goals, budgets | done |
| `(app)/rules/[id]/edit.tsx` | `features/financial-rules/rule-editor-screen.tsx` | form | rule, form data | F3: Retry | yes | n/a | yes | n/a (form) | — | done |
| `(app)/rules/[id]/preview.tsx` | `features/financial-rules/rule-preview-screen.tsx` | form | rule, accounts, goals | F5: Retry; preview is a manual POST (never retried automatically) | yes | n/a | yes | n/a (manual example) | goals | done |
| `(app)/rules/history.tsx` | `features/financial-rules/rule-history-screen.tsx` | list (paged) | executions (infinite), rules, goals | F6: refresh + Retry | yes | yes | first load, later page, refresh | yes | rules, goals (names) | done |
| `(app)/inbox/index.tsx` | `features/financial-rules/inbox-screen.tsx` | list (3 sources) | proposals, alerts, executions | F4: refresh without a real spinner (`refreshing={false}`) | per source | per source | per source | yes (real spinner, one pull at a time; evaluation request unchanged) | each source | done |
| `(app)/inbox/alerts.tsx` | `features/financial-rules/alerts-screen.tsx` | list (paged) | alert feed (infinite) | F4: refresh + Retry | yes | yes | yes | yes (paging kept) | — | done |
| `(app)/inbox/proposals/[id].tsx` | `features/financial-rules/proposal-detail-screen.tsx` | detail | proposal | F4: refresh + Retry | yes | n/a | yes | yes | — | done |
| `sign-in.tsx` | `features/auth/auth.service.ts` | form | none | no reads | n/a | n/a | n/a | n/a | — | done |

## Foreground refetch (all screens)
`app/_layout.tsx` installs `lib/app-focus-runtime.ts` once. It reports a real inactive/background → active change to
TanStack's `focusManager`; TanStack then refetches only mounted (active) queries whose data is stale. It never
invalidates the whole cache, never calls the network itself, and is independent of the Smart Rules evaluation host's own
AppState subscription (one debounced evaluate path, unchanged).

## Not changed (by design)
Mutation semantics and retry policy (GET-only bounded transport retry; no automatic POST/PATCH/PUT/DELETE retry; TanStack
retries stay disabled), the F4 Inbox indicator logic (`inbox-data.ts`, `use-inbox-data.ts`), the evaluation trigger and
provider, the session boundary and query-client rotation.

## Pending
BR-7 staging drills (expired token, hung request ending in a Retry state) and physical-device acceptance on iOS and
Android. Expo exports and Node tests are not device acceptance.
