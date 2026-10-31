# VF-BE-2 — Rule preview: final contract sheet (approved)

Status: **APPROVED by the owner (D1, D2, D3, the new 409 code, `source_selected_by_rule` and `notices`); implemented in VF-BE-2.**
Branch `feat/VF-API-RULE-PREVIEW`, base `main` `91f95409ad6ec298465c3e17f17917ecf78e1168` (includes BE-1).
Sources: `docs/mvp/mvp-engineering-qa-roadmap.md` (BE-2), `docs/modules/smart-goals-rules.md` (§10.3, §20.4),
`rule_execution_service.py` (`_build_plan`, `_blocked_reason`, `_execute_rule`).

## 1. Endpoint

`POST /api/v1/financial-rules/{rule_id}/preview` — authenticated; `user_id` from the identity only.
HTTP 200 on success. It is a POST because it takes a body; it is **not** a state change and is safe to repeat.
No `Idempotency-Key`, no `client_request_id`: nothing is stored.

### Request

```json
{
  "sample_income": { "amount": "3000.00", "source": "salary" }
}
```

| Field | Type | Rule |
|---|---|---|
| `sample_income.amount` | decimal string | required, `> 0`, at most 12 digits, 2 decimals (same as Income amount). Never a float. |
| `sample_income.source` | `salary \| freelance \| refund \| gift \| other` | optional. When omitted, no source check is reported. |

`extra="forbid"`: `user_id`, currency, dates and any other field are rejected (422 `validation_error`).
The sample income's **currency is the rule's source Account currency** (server-derived, not an input).

### Response (200)

```json
{
  "hypothetical": true,
  "rule_id": "…",
  "rule_version": 3,
  "rule_status": "draft",
  "execution_mode": "CONFIRM",
  "policy": "PERCENT_OF_INCOME_WATERFALL",
  "as_of_date": "2026-11-02",
  "computed_at": "2026-11-02T09:30:00.123456+00:00",
  "sample_income": { "amount": "3000.00", "currency": "EUR", "source": "salary",
                     "source_selected_by_rule": true },
  "capacity": {
    "account_id": "…",
    "currency": "EUR",
    "reservable_amount": "1200.00",
    "assumed_sample_income_credit": "3000.00",
    "reservable_with_sample_income": "4200.00",
    "minimum_unallocated_floor": "500.00",
    "active_rule_holds": "100.00",
    "rule_capacity": "3600.00"
  },
  "predicted_outcome": "partial",
  "effect": "would_hold",
  "reason_code": null,
  "items": [
    { "goal_id": "…", "position": 0, "priority_rank": 1,
      "planned_amount": "300.00", "selected_amount": "300.00" }
  ],
  "planned_total": "450.00",
  "selected_total": "300.00",
  "notices": ["hypothetical_snapshot", "income_not_recorded", "eligibility_not_evaluated"]
}
```

Field semantics:

- `hypothetical: true` always. `sample_income` is echoed; **nothing was recorded, credited, reserved or held**.
- `rule_id`, `rule_version`, `rule_status`, `execution_mode` (`AUTO` | `CONFIRM`), `policy`: the rule as read in the snapshot.
- `as_of_date`: server calendar date (same `server_today()` real execution uses). `computed_at`: database snapshot time.
  A client must treat the whole body as stale once the rule version changes or the user edits Goals/Accounts.
- `capacity` (all two-decimal strings): the same figures the Account read model exposes, plus the explicit sample credit.
  `rule_capacity = reservable_with_sample_income − minimum_unallocated_floor − active_rule_holds`.
- `predicted_outcome`: `full` | `partial` | `skipped` | `blocked`.
- `effect` distinguishes the modes and is never ambiguous:
  - `AUTO` rule → `would_apply` (money would be reserved to the Goals immediately; outcomes executed / executed_partial).
  - `CONFIRM` rule → `would_hold` (a 168-hour soft hold and a proposal awaiting the user's confirmation; **nothing is
    reserved until confirmed**).
  - `skipped` / `blocked` → `none`.
- `reason_code`: null for `full` / `partial`; otherwise one of the existing stable codes
  `nothing_to_allocate`, `insufficient_capacity`, `source_account_archived`, `target_goal_archived`, `currency_mismatch`.
- `items`: the wanted plan in Goal priority order (`planned_amount`) and what would actually be selected
  (`selected_amount`; `0.00` for a Goal that does not fit). `planned_total` / `selected_total` are their sums.
  Only positive cent amounts are planned (as real execution does).
- `notices`: fixed machine tokens; clients must show the hypothetical label.

### What preview does **not** promise (stated in the response `notices`)

`eligibility_not_evaluated`: a real future Income is only processed if it is a live manual entry, created after the rule
became enabled (`active_since`), on or after `effective_from`, within the 7-day window and from a selected source. Preview
does not evaluate those predicates and gives no promise that a real event will satisfy them. `source_selected_by_rule`
is informational only (null when no source was supplied).

## 2. Errors (BE-1 envelope: `detail` + `code`)

| Status | `code` | When |
|---|---|---|
| 404 | `financial_rule_not_found` | unknown id or another user's rule (same body for both; no existence leak) |
| 409 | `financial_rule_preview_not_available` (**new code, added to the registry + snapshot**) | rule type is not `INCOME_ALLOCATION` |
| 422 | `validation_error` | malformed body, non-positive amount, bad decimals, unknown/extra field |
| 401 | existing `auth_*` | unauthenticated |

A rule whose Account/Goals are archived, or whose currencies mismatch, is **not** an HTTP error: it is a normal 200 with
`predicted_outcome: "blocked"` and the reason code (exactly what real execution would record). An internal exception
is the BE-1 generic 500 and leaves no write.

## 3. Shared planning (no second algorithm)

New pure module `rule_allocation_planner.py` (no SQLAlchemy, no I/O). One function
`decide(rule_facts, account_facts, goal_facts, income, capacity) -> AllocationDecision` implements, unchanged:
blocked checks (archived Account, archived Goal, currency mismatch) → Goal priority order (`priority_rank`, unranked
last, id tiebreak) → FIXED or PERCENT waterfall (ROUND_DOWN cents, per-target cap) → `cap_at_target` → positive cents
only → `nothing_to_allocate` / full / `allow_partial` partial in priority order / `insufficient_capacity`.
`_build_plan` and the branch logic of `_execute_rule` call it; persistence, the capacity mutation, hold sequences,
audit rows and lock order in `_execute_rule` stay exactly as they are. Existing execution tests are the regression
guard (they must pass unmodified).

## 4. Read-only enforcement

Preview opens its **own** `Session` (not the request's session) and, as the first statement, runs
`SET TRANSACTION READ ONLY, ISOLATION LEVEL REPEATABLE READ` (transaction level, PostgreSQL), then all reads, then always
`ROLLBACK` and `close()` in `finally`. Any write, `nextval()`, `INSERT/UPDATE/DELETE` raises at the database.
Forbidden and tested: `FOR UPDATE`, advisory locks, `next_hold_sequence`, `expire_due_proposals`, execution/item/audit/alert/
event/idempotency rows, `_execute_rule`. Reads use the existing repository functions (no lock variants).

## 5. Decisions I need from the owner (each has a recommended default)

**D1 — Does the planning capacity include the sample income?** Real execution runs *after* the Income is recorded, so the
Account's `reservable_amount` already contains it.
- **Recommended (B):** plan against `reservable + sample amount` (the capacity real execution would see), report the
  actual figure, the assumed credit and the sum separately, and label it `income_not_recorded`. Parity is defined as:
  preview before recording income X == execution after recording income X, on otherwise identical state.
- Alternative (A): plan against current capacity only (never adds the sample). Simpler claim, but would predict
  `partial`/`skipped` for a salary that in reality fits.

**D2 — Other enabled rules.** Real execution evaluates all eligible rules in order, each consuming capacity. **Recommended:**
preview simulates **only the requested rule** against the current state (other rules' consumption is not simulated and the
response says nothing about them). Alternative: simulate earlier-ordered rules too (larger scope).

**D3 — Which rule statuses are previewable?** **Recommended:** every `INCOME_ALLOCATION` rule in any status
(draft, enabled, paused, disabled), since AUTO re-enable also needs a fresh preview. Non-allocation types → 409 above.
Alternative: draft only, as the status table in §10.3 currently reads.

Also confirm: new code `financial_rule_preview_not_available` (adding it also updates the BE-1 snapshot and
`docs/api-contract.md` §13), and that `source_selected_by_rule` / `notices` are acceptable additive fields.

## 6. Test plan (exit evidence)

Owner isolation (foreign id = 404, identical to missing) and 404/409/422 cases; **parity** (preview vs a real execution of
the same state for AUTO and CONFIRM, comparing selected items); FIXED and PERCENT waterfalls; full / partial / skipped /
blocked (each reason); AUTO vs CONFIRM `effect`; exact capacity/floor/holds arithmetic including active vs expired holds;
**full-row snapshots** of every table read or touchable (rules, targets, executions, items, audit, alerts, goals,
goal_transactions, accounts, account ledger, financial_events, idempotency data) plus sequence values, identical before/
after on success and on every error path (404, 409, 422, forced internal exception); injected `INSERT` and `nextval()`
inside the preview transaction fail at the database; concurrent previews return identical output; preview racing a real
execution and a balance change: consistent snapshot, no deadlock, execution result unchanged; existing execution and BE-1
suites unchanged; full backend suite on a `*_test` database.

## 7. Approval

Reply "approved" (or list changes to D1–D3 / fields). Only then will implementation start; scope will not expand beyond
this sheet.
