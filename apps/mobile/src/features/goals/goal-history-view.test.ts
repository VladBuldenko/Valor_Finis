// VF-GOALS-PLANNING-002A: wording for "Compared with your financial history".
// Fixtures are what the backend returns (the arithmetic is tested in services/api
// tests/unit/goals/test_goal_history_calculator.py); the app must show them as
// given, choose sentences from the backend's status, direction and limitation
// codes, and never imply the installment is affordable or money is available.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import { findForbiddenCopy } from "../financial-rules/financial-rule-forbidden-copy.ts";
import {
  HISTORY_DISCLAIMER,
  HISTORY_NOT_MODELLED,
  HISTORY_TITLE,
  historyMonthRows,
  historySentences,
} from "./goal-history-view.ts";
import type { GoalHistoryComparison, GoalHistoryMonth } from "./goal.types.ts";

const HERE = dirname(fileURLToPath(import.meta.url));

const month = (start: string, over: Partial<GoalHistoryMonth> = {}): GoalHistoryMonth => ({
  period_start: start,
  period_end: start,
  income_total: "3000.00",
  expense_total: "2400.00",
  net_flow: "600.00",
  income_count: 1,
  expense_count: 1,
  unresolved_income_count: 0,
  unresolved_expense_count: 0,
  has_activity: true,
  included_in_average: true,
  ...over,
});

const comparison = (over: Partial<GoalHistoryComparison> = {}): GoalHistoryComparison => ({
  goal_id: "goal-1",
  as_of: "2026-11-16",
  goal_currency: "EUR",
  base_currency: "EUR",
  status: "comparable",
  limitations: ["budgets_not_modelled", "goal_commitments_not_modelled"],
  analysis_period_start: "2026-08-01",
  analysis_period_end: "2026-10-31",
  months: [month("2026-08-01"), month("2026-09-01"), month("2026-10-01")],
  months_used: 3,
  average_monthly_income: "3000.00",
  average_monthly_expenses: "2400.00",
  average_monthly_net_flow: "600.00",
  required_per_installment: "450.00",
  historical_difference: "150.00",
  difference_direction: "surplus",
  ...over,
});

const unusable = (over: Partial<GoalHistoryComparison> = {}) =>
  comparison({
    status: "insufficient_data",
    months_used: 0,
    average_monthly_income: null,
    average_monthly_expenses: null,
    average_monthly_net_flow: null,
    historical_difference: null,
    difference_direction: null,
    ...over,
  });

describe("comparable history", () => {
  it("states the backend's average and the required installment, then the difference", () => {
    assert.deepEqual(historySentences(comparison()), [
      "Your recorded monthly net flow averaged 600.00 EUR over the last 3 completed months.",
      "Your Goal requires 450.00 EUR per installment.",
      "On that history, your average was 150.00 EUR above the required installment.",
    ]);
  });

  it("a shortfall drops the sign for display and says below; equal says matched", () => {
    assert.match(
      historySentences(comparison({ historical_difference: "-0.01", difference_direction: "shortfall" })).at(-1) ?? "",
      /^On that history, your average was 0\.01 EUR below the required installment\.$/,
    );
    assert.equal(
      historySentences(comparison({ historical_difference: "0.00", difference_direction: "equal" })).at(-1),
      "On that history, your average matched the required installment.",
    );
  });

  it("a negative or zero average is shown exactly as the backend returned it", () => {
    const negative = comparison({ average_monthly_net_flow: "-300.00", historical_difference: "-750.00", difference_direction: "shortfall" });

    assert.match(historySentences(negative)[0], /averaged -300\.00 EUR/);
    assert.match(historySentences(negative)[2], /750\.00 EUR below/);
    assert.match(historySentences(comparison({ average_monthly_net_flow: "0.00" }))[0], /averaged 0\.00 EUR/);
  });

  it("says how many months were used when months without records were left out", () => {
    const two = comparison({ months_used: 2 });

    assert.match(historySentences(two)[0], /over 2 of the last 3 completed months \(months without recorded income and expenses are left out\)\./);
  });

  it("uses the Goal's and the base currency labels as the backend gave them", () => {
    const lines = historySentences(comparison({ base_currency: "EUR", goal_currency: "EUR" }));

    assert.ok(lines[0].includes("600.00 EUR") && lines[1].includes("450.00 EUR"));
  });
});

describe("history that cannot be compared", () => {
  it("too little history says what is needed instead of inventing an estimate", () => {
    const lines = historySentences(unusable({ limitations: ["fewer_than_two_active_months", "budgets_not_modelled", "goal_commitments_not_modelled"] }));

    assert.equal(lines.length, 2);
    assert.match(lines[0], /at least 2 of the last 3 completed months with both recorded income and recorded expenses/);
    assert.equal(lines[1], "Your Goal requires 450.00 EUR per installment.");
    assert.ok(!lines.some((line) => /averaged|above|below/.test(line)));
  });

  it("unresolved currency data names the base currency and shows no average", () => {
    const lines = historySentences(unusable({ limitations: ["unresolved_currency_data", "budgets_not_modelled", "goal_commitments_not_modelled"] }));

    assert.match(lines[0], /no amount in your base currency \(EUR\), so no average is shown\./);
  });

  it("both reasons are given together; an unknown reason still yields a plain message", () => {
    const both = historySentences(unusable({ limitations: ["unresolved_currency_data", "fewer_than_two_active_months"] }));
    const none = historySentences(unusable({ limitations: [], required_per_installment: null }));

    assert.match(both[0], /no average is shown\. A comparison needs at least 2/);
    assert.deepEqual(none, ["There is not enough recorded history to compare yet."]);
  });

  it("a currency mismatch explains it, converts nothing and shows no difference", () => {
    const lines = historySentences(
      comparison({ status: "currency_mismatch", goal_currency: "USD", historical_difference: null, difference_direction: null }),
    );

    assert.match(lines[0], /^This Goal is in USD, but your recorded income and expenses are in EUR\. They are not converted, so no comparison is shown\.$/);
    assert.ok(!lines.some((line) => /above|below|matched/.test(line)));
    assert.ok(lines.some((line) => line.includes("450.00 USD")));
  });

  it("no required installment says there is nothing to compare", () => {
    const lines = historySentences(
      comparison({ status: "no_required_installment", required_per_installment: null, historical_difference: null, difference_direction: null }),
    );

    assert.equal(lines[0], "This Goal has no required installment right now, so there is nothing to compare.");
    assert.ok(!lines.some((line) => /requires/.test(line)));
  });

  it("every state yields at least one sentence", () => {
    for (const status of ["comparable", "insufficient_data", "currency_mismatch", "no_required_installment"] as const) {
      assert.ok(historySentences(comparison({ status })).length > 0, status);
    }
  });
});

describe("month rows", () => {
  it("one row per analysed month with its net flow, labelled by year-month", () => {
    assert.deepEqual(historyMonthRows(comparison()), [
      { label: "2026-08", value: "600.00 EUR net" },
      { label: "2026-09", value: "600.00 EUR net" },
      { label: "2026-10", value: "600.00 EUR net" },
    ]);
  });

  it("a month with no records is said so and a left-out month is marked", () => {
    const rows = historyMonthRows(
      comparison({
        months: [
          month("2026-08-01", { income_total: "0.00", expense_total: "0.00", net_flow: "0.00", income_count: 0, expense_count: 0, has_activity: false, included_in_average: false }),
          month("2026-09-01", { income_total: "100.00", expense_total: "0.00", net_flow: "100.00", expense_count: 0, has_activity: false, included_in_average: false }),
          month("2026-10-01"),
        ],
      }),
    );

    assert.equal(rows[0].value, "no recorded income or expenses");
    assert.equal(rows[1].value, "100.00 EUR net, not in the average");
    assert.equal(rows[2].value, "600.00 EUR net");
  });

  it("a month with unresolved records says its net counts only records with a base-currency amount", () => {
    const rows = historyMonthRows(unusable({ months: [month("2026-08-01", { unresolved_expense_count: 1, included_in_average: false })] }));

    assert.equal(rows[0].value, "600.00 EUR net, counting only records with a EUR amount; not in the average");
  });
});

describe("copy is cautious", () => {
  const everything = [
    HISTORY_TITLE,
    HISTORY_NOT_MODELLED,
    ...(["comparable", "insufficient_data", "currency_mismatch", "no_required_installment"] as const).flatMap((status) =>
      historySentences(comparison({ status, limitations: ["unresolved_currency_data", "fewer_than_two_active_months"] })),
    ),
    ...historySentences(comparison({ historical_difference: "-5.00", difference_direction: "shortfall" })),
    ...historySentences(comparison({ historical_difference: "0.00", difference_direction: "equal" })),
  ];

  it("the title and disclaimer are the specified wording", () => {
    assert.equal(HISTORY_TITLE, "Compared with your financial history");
    assert.equal(HISTORY_DISCLAIMER, "This is based on recorded past activity, not a guarantee that the contribution is affordable.");
  });

  it("passes the project's forbidden-copy rules; the disclaimer is checked apart from its one negated 'guarantee'", () => {
    for (const text of everything) {
      assert.deepEqual(findForbiddenCopy(text), [], text);
    }

    assert.deepEqual(findForbiddenCopy(HISTORY_DISCLAIMER).map((hit) => hit.id), ["guarantee"]);
    assert.match(HISTORY_DISCLAIMER, /not a guarantee/);
  });

  it("outside the disclaimer, no sentence promises, certifies or judges affordability or availability", () => {
    for (const text of everything) {
      assert.doesNotMatch(text, /\b(you can afford|affordable|feasible|achievable|on track|will reach|definitely|certain|safe|available|free to|spare|should|recommend)\b/i, text);
    }
  });

  it("discloses what is not modelled", () => {
    assert.match(HISTORY_NOT_MODELLED, /Budget limits are not counted as spending/);
    assert.match(HISTORY_NOT_MODELLED, /reserved for Goals or set aside by active Rules is not subtracted/);
  });
});

describe("the presentation does no money arithmetic", () => {
  it("has no number parsing or arithmetic", () => {
    const code = readFileSync(join(HERE, "goal-history-view.ts"), "utf8").replace(/\/\/.*$/gm, "");

    assert.doesNotMatch(code, /parseFloat|Number\(|parseInt|\.toFixed|Math\.|\bBigInt\b/);
  });
});
