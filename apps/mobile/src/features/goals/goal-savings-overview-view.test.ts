// VF-GOALS-PLANNING-002B: wording for the "Savings plans" overview. Fixtures are
// what the backend returns (see services/api
// tests/unit/goals/test_goal_savings_overview_calculator.py for the arithmetic);
// the app must show them as given and never imply an installment is scheduled,
// reserved, moved or affordable.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import { findForbiddenCopy } from "../financial-rules/financial-rule-forbidden-copy.ts";
import {
  OVERVIEW_ASSUMPTION,
  OVERVIEW_DISCLAIMER,
  OVERVIEW_NOT_MODELLED,
  OVERVIEW_TITLE,
  hasOverviewContent,
  overviewComparisonLines,
  overviewContinuesNote,
  overviewContributionRows,
  overviewHeadline,
  overviewMonthRows,
  overviewNotices,
  overviewSummaryLines,
} from "./goal-savings-overview-view.ts";
import type { GoalSavingsMonth, GoalSavingsOverview, GoalSavingsPlannedGoal } from "./goal.types.ts";

const HERE = dirname(fileURLToPath(import.meta.url));

const planned = (name: string, over: Partial<GoalSavingsPlannedGoal> = {}): GoalSavingsPlannedGoal => ({
  goal_id: `id-${name}`,
  name,
  priority_rank: 1,
  target_date: "2027-03-31",
  remaining_amount: "1000.00",
  installment_count: 5,
  required_per_installment: "200.00",
  first_installment_date: "2026-11-16",
  last_installment_date: "2027-03-01",
  continues_after_window: false,
  ...over,
});

const month = (start: string, total: string, count: number, over: Partial<GoalSavingsMonth> = {}): GoalSavingsMonth => ({
  period_start: start,
  period_end: start,
  installment_date: start,
  total_required: total,
  planned_goal_count: count,
  contributions: [],
  historical_difference: null,
  difference_direction: null,
  ...over,
});

const overview = (over: Partial<GoalSavingsOverview> = {}): GoalSavingsOverview => ({
  as_of: "2026-11-16",
  base_currency: "EUR",
  horizon_months: 12,
  is_total_complete: true,
  planned_goals: [planned("Trip"), planned("Laptop", { goal_id: "id-Laptop", priority_rank: 2, required_per_installment: "300.00" })],
  months: [
    month("2026-11-01", "500.00", 2, {
      contributions: [
        { goal_id: "id-Trip", amount: "200.00" },
        { goal_id: "id-Laptop", amount: "300.00" },
      ],
      historical_difference: "100.00",
      difference_direction: "surplus",
    }),
    month("2026-12-01", "200.00", 1, { historical_difference: "-50.00", difference_direction: "shortfall" }),
    month("2027-01-01", "0.00", 0),
  ],
  exclusions: {
    archived: 0,
    completed: 0,
    already_funded: 0,
    no_target_date: 0,
    target_date_passed: 0,
    other_currency: 0,
    other_currencies: [],
  },
  history: {
    status: "comparable",
    analysis_period_start: "2026-08-01",
    analysis_period_end: "2026-10-31",
    months: [],
    months_used: 3,
    average_monthly_income: "3000.00",
    average_monthly_expenses: "2400.00",
    average_monthly_net_flow: "600.00",
  },
  limitations: ["budgets_not_modelled", "goal_commitments_not_modelled", "future_obligations_not_modelled"],
  ...over,
});

const withExclusions = (over: Partial<GoalSavingsOverview["exclusions"]>): Partial<GoalSavingsOverview> => ({
  exclusions: { ...overview().exclusions, ...over },
});

describe("headline and summary", () => {
  it("shows this month's combined installment exactly as the backend returned it, with the base currency", () => {
    assert.deepEqual(overviewHeadline(overview()), { label: "This month's combined required installment", amount: "500.00 EUR" });
  });

  it("counts the planned Goals, and says how many have an installment this month when fewer", () => {
    assert.deepEqual(overviewSummaryLines(overview()), ["2 Goals planned."]);
    assert.deepEqual(
      overviewSummaryLines(overview({ planned_goals: [planned("A"), planned("B"), planned("C")] })),
      ["3 Goals planned, 2 with an installment this month."],
    );
    assert.deepEqual(overviewSummaryLines(overview({ planned_goals: [planned("A")], months: [month("2026-11-01", "200.00", 1)] })), ["1 Goal planned."]);
  });

  it("says plainly when the total is incomplete", () => {
    assert.ok(overviewSummaryLines(overview({ is_total_complete: false })).some((line) => /incomplete/.test(line)));
    assert.ok(!overviewSummaryLines(overview()).some((line) => /incomplete/.test(line)));
  });

  it("with nothing planned there is no headline amount and no claim of zero savings", () => {
    const none = overview({ planned_goals: [], months: [month("2026-11-01", "0.00", 0)] });

    assert.equal(overviewHeadline(none), null);
    assert.deepEqual(overviewSummaryLines(none), ["No Goal has a required installment right now."]);
    assert.equal(overviewHeadline(overview({ months: [] })), null);
  });
});

describe("comparison with recorded history", () => {
  it("states the average and the difference for this month, with the surplus sign shown in words", () => {
    assert.deepEqual(overviewComparisonLines(overview()), [
      "Your recorded monthly net flow averaged 600.00 EUR over the last 3 completed months.",
      "On that history, your average was 100.00 EUR above this month's combined installment.",
    ]);
  });

  it("a shortfall drops the minus sign and says below", () => {
    const lines = overviewComparisonLines(
      overview({ months: [month("2026-11-01", "800.00", 2, { historical_difference: "-200.00", difference_direction: "shortfall" })] }),
    );

    assert.equal(lines[1], "On that history, your average was 200.00 EUR below this month's combined installment.");
    assert.ok(!lines.some((line) => line.includes("-")));
  });

  it("a negative recorded net flow is shown as the backend gave it", () => {
    const lines = overviewComparisonLines(
      overview({
        history: { ...overview().history, average_monthly_net_flow: "-500.00" },
        months: [month("2026-11-01", "500.00", 1, { historical_difference: "-1000.00", difference_direction: "shortfall" })],
      }),
    );

    assert.match(lines[0], /averaged -500\.00 EUR/);
    assert.match(lines[1], /1000\.00 EUR below/);
  });

  it("an equal month says matched", () => {
    const lines = overviewComparisonLines(overview({ months: [month("2026-11-01", "600.00", 2, { historical_difference: "0.00", difference_direction: "equal" })] }));

    assert.equal(lines[1], "On that history, your average matched this month's combined installment.");
  });

  it("says how many months were used when some were left out, never as zero", () => {
    const lines = overviewComparisonLines(overview({ history: { ...overview().history, months_used: 2 } }));

    assert.match(lines[0], /over 2 of the last 3 completed months \(months without recorded income and expenses are left out\)\./);
  });

  it("insufficient history explains why instead of showing a number", () => {
    const thin = overview({
      history: { ...overview().history, status: "insufficient_data", average_monthly_net_flow: null, months_used: 0 },
      limitations: ["fewer_than_two_active_months", "budgets_not_modelled"],
    });
    const unresolved = overview({
      history: { ...overview().history, status: "insufficient_data", average_monthly_net_flow: null, months_used: 0 },
      limitations: ["unresolved_currency_data", "budgets_not_modelled"],
    });
    const unknown = overview({ history: { ...overview().history, status: "insufficient_data", average_monthly_net_flow: null } });

    assert.match(overviewComparisonLines(thin).join(" "), /needs at least 2 of the last 3 completed months/);
    assert.match(overviewComparisonLines(unresolved).join(" "), /no amount in your base currency \(EUR\), so no average is shown/);
    assert.deepEqual(overviewComparisonLines(unknown), ["There is not enough recorded history to compare yet."]);
    assert.ok(!overviewComparisonLines(thin).join(" ").match(/averaged|above|below/));
  });

  it("nothing planned means nothing to compare", () => {
    assert.deepEqual(overviewComparisonLines(overview({ planned_goals: [], history: { ...overview().history, status: "no_planned_goals" } })), []);
  });
});

describe("what is left out of the total", () => {
  it("other-currency Goals are named, never converted, and the total is called incomplete", () => {
    const one = overviewNotices(overview(withExclusions({ other_currency: 1, other_currencies: ["USD"] })));
    const two = overviewNotices(overview(withExclusions({ other_currency: 2, other_currencies: ["GBP", "USD"] })));

    assert.deepEqual(one, ["1 Goal in USD is not included, because amounts in different currencies are never added or converted. The total is incomplete."]);
    assert.match(two[0], /^2 Goals in GBP, USD are not included/);
  });

  it("Goals without a target date and overdue Goals are unplanned, never zero savings", () => {
    const notices = overviewNotices(overview(withExclusions({ no_target_date: 2, target_date_passed: 1 })));

    assert.match(notices[0], /^2 Goals have no target date, so no installment is calculated\. They are not counted as needing nothing\./);
    assert.match(notices[1], /^1 Goal has a target date that has passed, so no installment is calculated\. Update its date to plan ahead\./);
  });

  it("singular and plural agree", () => {
    assert.match(overviewNotices(overview(withExclusions({ no_target_date: 1 })))[0], /^1 Goal has no target date.*It is not counted/);
    assert.match(overviewNotices(overview(withExclusions({ target_date_passed: 3 })))[0], /^3 Goals have a target date that has passed.*their dates/);
  });

  it("funded, completed and archived Goals are silent, and a clean overview has no notices", () => {
    assert.deepEqual(overviewNotices(overview(withExclusions({ archived: 2, completed: 1, already_funded: 3 }))), []);
    assert.deepEqual(overviewNotices(overview()), []);
  });

  it("the section is shown only when there is something to plan or to flag", () => {
    const empty = overview({ planned_goals: [], months: [] });

    assert.equal(hasOverviewContent(overview()), true);
    assert.equal(hasOverviewContent(empty), false);
    assert.equal(hasOverviewContent(overview({ ...empty, ...withExclusions({ archived: 4, completed: 1, already_funded: 2 }) })), false);

    for (const flagged of [{ no_target_date: 1 }, { target_date_passed: 1 }, { other_currency: 1, other_currencies: ["USD"] }]) {
      assert.equal(hasOverviewContent(overview({ ...empty, ...withExclusions(flagged) })), true, JSON.stringify(flagged));
    }
  });
});

describe("the breakdown and the next months", () => {
  it("lists this month's installment for each Goal in the backend's (priority) order", () => {
    assert.deepEqual(overviewContributionRows(overview()), [
      { label: "Trip", value: "200.00 EUR" },
      { label: "Laptop", value: "300.00 EUR" },
    ]);
    assert.deepEqual(overviewContributionRows(overview({ months: [] })), []);
  });

  it("shows each month's total and Goal count, the backend's comparison, and 'no installments' when none", () => {
    assert.deepEqual(overviewMonthRows(overview()), [
      { label: "2026-11", value: "500.00 EUR for 2 Goals (recorded average 100.00 EUR above)" },
      { label: "2026-12", value: "200.00 EUR for 1 Goal (recorded average 50.00 EUR below)" },
      { label: "2027-01", value: "no installments" },
    ]);
  });

  it("shows consecutive months without installments as one range, still covering every month", () => {
    const rows = overviewMonthRows(
      overview({
        months: [
          month("2026-11-01", "300.00", 1),
          month("2026-12-01", "0.00", 0),
          month("2027-01-01", "0.00", 0),
          month("2027-02-01", "0.00", 0),
          month("2027-03-01", "100.00", 1),
          month("2027-04-01", "0.00", 0),
        ],
      }),
    );

    assert.deepEqual(rows, [
      { label: "2026-11", value: "300.00 EUR for 1 Goal" },
      { label: "2026-12 to 2027-02", value: "no installments" },
      { label: "2027-03", value: "100.00 EUR for 1 Goal" },
      { label: "2027-04", value: "no installments" },
    ]);
    assert.deepEqual(overviewMonthRows(overview({ months: [] })), []);
  });

  it("omits the comparison for a month the backend did not compare, and says matches for an equal one", () => {
    const rows = overviewMonthRows(
      overview({ months: [month("2026-11-01", "500.00", 2), month("2026-12-01", "600.00", 2, { historical_difference: "0.00", difference_direction: "equal" })] }),
    );

    assert.equal(rows[0].value, "500.00 EUR for 2 Goals");
    assert.equal(rows[1].value, "600.00 EUR for 2 Goals (recorded average matches)");
  });

  it("says once when Goals keep needing installments after the window", () => {
    assert.equal(overviewContinuesNote(overview()), null);
    assert.equal(overviewContinuesNote(overview({ planned_goals: [planned("A", { continues_after_window: true })] })), "Some Goals need installments after these 12 months.");
  });
});

describe("the copy is honest about what this is", () => {
  const rows = overview();
  const everything = [
    OVERVIEW_TITLE,
    OVERVIEW_ASSUMPTION,
    OVERVIEW_NOT_MODELLED,
    OVERVIEW_DISCLAIMER,
    overviewHeadline(rows)?.label,
    ...overviewSummaryLines(rows),
    ...overviewSummaryLines(overview({ is_total_complete: false, planned_goals: [planned("A"), planned("B"), planned("C")] })),
    ...overviewComparisonLines(rows),
    ...overviewComparisonLines(overview({ months: [month("2026-11-01", "800.00", 2, { historical_difference: "-200.00", difference_direction: "shortfall" })] })),
    ...overviewComparisonLines(overview({ history: { ...rows.history, status: "insufficient_data" }, limitations: ["fewer_than_two_active_months", "unresolved_currency_data"] })),
    ...overviewNotices(overview(withExclusions({ other_currency: 2, other_currencies: ["GBP", "USD"], no_target_date: 1, target_date_passed: 2 }))),
    ...overviewMonthRows(rows).map((row) => row.value),
    overviewContinuesNote(overview({ planned_goals: [planned("A", { continues_after_window: true })] })),
  ].filter((text): text is string => typeof text === "string");

  it("passes the project's forbidden-copy rules (no transfer wording, no promise, no invented balances)", () => {
    for (const text of everything) {
      assert.deepEqual(findForbiddenCopy(text), [], text);
    }
  });

  it("makes no affordability, scheduling or certainty claim", () => {
    for (const text of everything) {
      assert.doesNotMatch(text, /\b(you can afford|affordable|feasible|achievable|on track|will be (saved|paid|moved|reserved|transferred)|definitely|certain|safe to)\b/i, text);
    }
  });

  it("states that the installments are hypothetical, not scheduled, and that nothing is set aside or moved", () => {
    assert.match(OVERVIEW_ASSUMPTION, /hypothetical required installments, not scheduled contributions/);
    assert.match(OVERVIEW_ASSUMPTION, /one installment today and one on the 1st of each following month, up to its target date/);
    assert.match(OVERVIEW_ASSUMPTION, /Nothing is scheduled, set aside or moved\./);
  });

  it("discloses what is not modelled: Budgets, recurring bills, other obligations, reservations and Rules", () => {
    assert.match(OVERVIEW_NOT_MODELLED, /Budget limits/);
    assert.match(OVERVIEW_NOT_MODELLED, /recurring bills and other future obligations are not counted/);
    assert.match(OVERVIEW_NOT_MODELLED, /money already reserved for Goals or set aside by active Rules/);
  });

  it("frames the figures as recorded past activity, not a promise", () => {
    assert.match(OVERVIEW_DISCLAIMER, /recorded past activity and hypothetical installments/);
    assert.match(OVERVIEW_DISCLAIMER, /not a promise/);
  });
});

describe("the presentation does no money arithmetic", () => {
  it("has no number parsing or arithmetic", () => {
    const code = readFileSync(join(HERE, "goal-savings-overview-view.ts"), "utf8").replace(/\/\/.*$/gm, "");

    assert.doesNotMatch(code, /parseFloat|Number\(|parseInt|\.toFixed|Math\.|\bBigInt\b|\breduce\(/);
  });
});
