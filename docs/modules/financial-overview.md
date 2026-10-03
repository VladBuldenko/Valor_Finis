# Financial Overview — Contract and Decision Record (VF-019)

Status: backend implemented (VF-019B); mobile Financial Overview screen
and Dashboard card implemented (VF-019C, see section 10). Manual device
acceptance is pending (VF-019D). Discovery: VF-019A.

The exact request/response shapes are in `docs/api-contract.md`
(section 10, "Financial Overview" and "Income-Expense Trend"). This
document records the semantics and the approved product decisions behind
them.

---

## 1. Purpose

Answer, for a calendar month and across recent months:

- how much Income was recorded,
- how much was spent (Expenses),
- Net (Income - Expenses),
- the savings rate.

All values are calculated by FastAPI. Clients display them; they never
re-derive them.

## 2. Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/analytics/financial-overview?year=&month=` | One calendar month |
| `GET /api/v1/analytics/income-expense-trend?count=` | `count` (1..24, default 6) consecutive months, oldest first, ending with the current month |

Both are read-only, authenticated, scoped to the caller, and take "today"
from the server date (no public `as_of`). The service functions accept an
explicit `as_of` so tests never depend on the wall clock.

## 3. Sources — canonical records only

Included:

- `income` rows (any source, including `refund`),
- `expenses` rows (manual and receipt-confirmed),

whether or not they are linked to an Account.

Never read, so never counted as Income or Expense:

- `account_transactions` — opening balances, manual adjustments, and the
  Income/Expense projections of linked records (reading them would count a
  linked record twice),
- `account_transfers` — planned or posted,
- `goal_transactions` — contributions and withdrawals.

Only `income_service` and `expenses_service` write the two canonical
tables (Receipt confirmation goes through `expenses_service`), so the
exclusions above hold by construction and are covered by tests.

## 4. Date semantics (decision Q1)

| Requested month | `period_state` | Included dates | `effective_end` |
|---|---|---|---|
| ended before today (`period_end < as_of`) | `complete` | whole month | `period_end` |
| contains today (including its last day) | `in_progress` | 1st .. `as_of` inclusive | `as_of` |
| starts after today | `future` | none — all zeros | `null` |

- Future-dated records are never included.
- A future month is a valid request (200), not an error: a client whose
  local month is already ahead of the server date (see the D13 timezone
  gap in `docs/modules/account-transfers.md`) receives zeros, not a 422.
- The trend uses exactly the same rule per bucket:
  `effective_end = min(period_end, as_of)`, `is_complete = period_end < as_of`.
- `monthly-summary` is unchanged and still counts its whole calendar
  month, including future-dated Expenses. For the current month the two
  endpoints can therefore differ when future-dated Expenses exist.

## 5. Money

- Totals sum each resolved record's persisted `base_amount` — the
  historical FX snapshot taken at create/update time. The original
  mixed-currency `amount` is never summed, FX is never re-resolved, and
  reads make no provider/network call.
- Python `Decimal` only. Amounts have two decimal places; an empty month
  is `"0.00"`.
- `net_flow = income_total - expense_total` (may be negative or zero).
- `savings_rate_percent = net_flow / income_total * 100`, rounded to two
  places with `ROUND_HALF_EVEN`; negative values are not clamped; a rate
  that rounds to zero is `"0.00"`, never `"-0.00"`; `null` exactly when
  `income_total` is zero (decision Q3).

## 6. Resolved / unresolved (decision Q4)

A record is unresolved when `base_amount` is null or its snapshot
`base_currency` differs from the user's current base currency. It is:

- excluded from its total,
- counted in `unresolved_income_count` / `unresolved_expense_count`,
- never treated as a known zero.

`data_status` (overview only) is `incomplete_data` when either unresolved
count is greater than zero, otherwise `complete_data` — including an
empty month. Totals are then computed from the resolved records only.
`income_count` / `expense_count` count only the resolved records in the
totals.

In practice Income always has a snapshot (it is resolved at creation);
legacy foreign-currency Expenses created before VF-014B5C may not.

## 7. What Net is not (decision Q9)

The UI term is **Net (Income - Expenses)**. It is recorded income minus
recorded expenses. It is NOT:

- a bank-reconciled cash flow,
- a change in Account balances (unlinked records, opening balances,
  adjustments, and Transfers make the two differ),
- available cash,
- net worth.

The savings rate is a ratio of these recorded figures; it is unrelated to
Goal funding.

## 8. Decision record (approved for VF-019B)

| # | Decision |
|---|---|
| Q1 | Complete months: whole month. Current month: through the server date, inclusive. Future-dated records excluded. Overview and trend share the same rule; `monthly-summary` unchanged. |
| Q2 | Income with `source="refund"` is Income; refunds are never subtracted from Expenses. |
| Q3 | `net_flow = income - expenses`; savings rate `net / income * 100`, negative allowed, `null` for zero income, `ROUND_HALF_EVEN`, two places. |
| Q4 | Unresolved records are excluded from sums, counted, and flag `incomplete_data`; totals come from resolved data. |
| Q5 | Trend: monthly buckets only; default 6, maximum 24; `count` < 1 or > 24 is 422. |
| Q6 | Mobile starts with a textual presentation; no chart dependency. |
| Q7 | A later mobile slice adds a compact Income / Expenses / Net Dashboard card. |
| Q8 | Mobile navigates calendar months; the backend takes explicit `year`/`month`. |
| Q9 | Terminology: "Net (Income - Expenses)" — never cash flow, balance, or net worth. |
| Q10 | Financial Overview takes priority over Goal ↔ Account semantics discovery; Goals are not integrated with Accounts. |

## 9. Implementation notes

- `analytics_service._build_financial_flow_figures` is the single
  calculation behind both endpoints, so a month's overview and its trend
  bucket can never disagree.
- Bounded reads only: `income_repository.get_income_in_date_range` and
  `expenses_repository.get_expenses_in_date_range`, one query per side.
  The trend reads its whole window once and groups by month in one pass.
- No new tables, migrations, indexes, or dependencies. Existing
  single-column indexes on `user_id` and the date columns serve the
  bounded queries; composite indexes or SQL aggregation are only worth
  revisiting after measuring real data volumes.

## 10. Mobile (VF-019C)

The mobile client only renders backend values; it never computes Net, the
savings rate, FX conversions, or any total. Amounts stay strings end to end.

- Screen: `app/(app)/overview/index.tsx` ("Financial Overview",
  `src/features/analytics/financial-overview-screen.tsx`).
  - Month selector (Previous / month label / Next) over calendar months,
    including year changes; Next is disabled at the device's current local
    month. The selection is "current month" or one specific earlier month;
    "current month" follows the device's local month, which is re-read when
    the screen regains focus (`useLocalCalendarMonth`, no timer).
  - "Income and expenses" section for the selected month
    (`financial-overview`): Income, Expenses, Net (Income - Expenses) with
    a textual surplus/deficit/break-even label, savings rate ("Unavailable"
    when the backend returns null), record counts, the backend period line
    (complete / in progress through effective_end / future), an
    "Incomplete data" warning with the unresolved counts when
    `data_status` is `incomplete_data`, and an empty-state note.
  - "Monthly history" section (`income-expense-trend`, count 6): the
    buckets in backend order with the same figures; a bucket shows the
    incomplete warning when its unresolved counts are non-zero (buckets
    have no data_status). The window is the last 6 months ending with the
    current server month, as the backend anchors it; the month selected
    above does not change it, and the screen says so under the heading.
  - The two sections load, fail, and retry (`refetch`) independently.
- Dashboard: an "Income and expenses" card for the device's current local
  month (Income, Expenses, Net, backend currency, incomplete-data notice)
  with a "Financial Overview" button. The existing "This month"
  monthly-summary card is unchanged; the two may show different expense
  figures for the current month (see section 4). The Dashboard's month is
  also re-read on focus.
- Query keys: `["analytics", "financial-overview", userId, year, month]`
  and `["analytics", "income-expense-trend", userId, count]`, enabled only
  with a session.
- Invalidation: every successful Income create/update/delete
  (`income-cache.ts`, regardless of Account link) and every Expense
  mutation (`expense-cache.ts`, which Receipt confirmation also uses)
  invalidates both families. Transfers, Account adjustments, and Goal
  mutations do not, because they never change these figures.

## 11. Out of scope / follow-ups

- Category and Income-source breakdowns.
- Bank cash-flow reconciliation, net worth, projected balances.
- Changing `monthly-summary`'s whole-month semantics (would be a separate,
  explicit contract change).
- User timezone semantics (D13): "today" remains the server date.
