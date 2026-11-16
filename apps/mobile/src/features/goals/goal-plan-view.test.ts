// VF-GOALS-PLANNING-001: wording for the Goal plan. Fixtures are what the
// backend returns (see services/api tests/unit/goals/test_goal_plan_calculator.py
// for the arithmetic itself); the app must show them as given and never imply a
// plan is affordable or certain.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import { findForbiddenCopy } from "../financial-rules/financial-rule-forbidden-copy.ts";
import {
  PLAN_ASSUMPTION,
  PLAN_TITLE,
  PROGRESS_NOTE,
  WHAT_IF_DISCLAIMER,
  WHAT_IF_HINT,
  planProgressRows,
  planRequirement,
  planStatusMessage,
  whatIfMessage,
} from "./goal-plan-view.ts";
import type { GoalPlan, GoalPlanWhatIf } from "./goal.types.ts";

const HERE = dirname(fileURLToPath(import.meta.url));

const plan = (over: Partial<GoalPlan> = {}): GoalPlan => ({
  goal_id: "goal-1",
  currency: "EUR",
  goal_status: "active",
  as_of: "2026-11-16",
  target_amount: "2000.00",
  current_amount: "500.00",
  tracked_amount: "300.00",
  linked_amount: "200.00",
  remaining_amount: "1500.00",
  overfunded_amount: "0.00",
  target_date: "2027-03-31",
  plan_status: "ready",
  installment_count: 5,
  required_per_installment: "300.00",
  first_installment_date: "2026-11-16",
  last_installment_date: "2027-03-01",
  horizon_months: 600,
  what_if: null,
  ...over,
});

const whatIf = (over: Partial<GoalPlanWhatIf> = {}): GoalPlanWhatIf => ({
  monthly_contribution: "150.00",
  outcome: "reaches_target",
  installments_needed: 10,
  estimated_completion_date: "2027-08-01",
  on_or_before_target_date: null,
  ...over,
});

describe("progress", () => {
  it("shows the backend's remaining amount as returned, with the currency", () => {
    assert.deepEqual(planProgressRows(plan()), [{ label: "Remaining to target", value: "1500.00 EUR" }]);
  });

  it("an overfunded Goal shows zero remaining and by how much it is above target", () => {
    const rows = planProgressRows(
      plan({ current_amount: "650.00", target_amount: "500.00", remaining_amount: "0.00", overfunded_amount: "150.00", plan_status: "already_funded" }),
    );

    assert.deepEqual(rows, [
      { label: "Remaining to target", value: "0.00 EUR" },
      { label: "Above target by", value: "150.00 EUR" },
    ]);
  });

  it("separates tracked progress from reserved money in plain words", () => {
    assert.match(PROGRESS_NOTE, /Tracked progress is not money set aside in an Account/);
    assert.match(PROGRESS_NOTE, /Reserved progress is earmarked inside an Account/);
    assert.match(PROGRESS_NOTE, /does not move money/);
  });
});

describe("required installment", () => {
  it("is shown only for a ready plan, using the backend's amount, count and dates", () => {
    assert.deepEqual(planRequirement(plan()), {
      headline: "300.00 EUR per installment",
      schedule: "5 installments, from 2026-11-16 to 2027-03-01, to reach the target by 2027-03-31.",
    });
    assert.match(planRequirement(plan({ installment_count: 1, last_installment_date: "2026-11-16" }))?.schedule ?? "", /^1 installment, from/);
  });

  it("is absent for every other status, and when any backend field is missing", () => {
    for (const status of ["archived", "already_funded", "no_target_date", "target_date_passed"] as const) {
      assert.equal(planRequirement(plan({ plan_status: status })), null, status);
    }

    assert.equal(planRequirement(plan({ required_per_installment: null })), null);
    assert.equal(planRequirement(plan({ installment_count: null })), null);
  });

  it("explains the situation instead, for each status", () => {
    assert.equal(planStatusMessage(plan()), null);
    assert.match(planStatusMessage(plan({ plan_status: "archived" })) ?? "", /archived.*no plan is shown/);
    assert.match(planStatusMessage(plan({ plan_status: "already_funded" })) ?? "", /reached its target/);
    assert.match(planStatusMessage(plan({ plan_status: "already_funded", overfunded_amount: "50.00" })) ?? "", /above its target/);
    assert.match(planStatusMessage(plan({ plan_status: "no_target_date", target_date: null })) ?? "", /Add a target date/);
    assert.match(planStatusMessage(plan({ plan_status: "target_date_passed", target_date: "2026-11-01" })) ?? "", /target date \(2026-11-01\) has passed/);
  });

  it("states the one schedule assumption and that nothing is scheduled, reserved or moved", () => {
    assert.match(PLAN_ASSUMPTION, /one contribution today and one on the 1st of each following month, up to the target date/);
    assert.match(PLAN_ASSUMPTION, /nothing is scheduled, reserved or moved/);
    assert.match(PLAN_ASSUMPTION, /estimate/);
  });
});

describe("what-if", () => {
  it("reaches the target: the backend's date and count, with a timing note only when the backend gave one", () => {
    assert.equal(
      whatIfMessage(whatIf({ on_or_before_target_date: true }), plan()),
      "At 150.00 EUR per installment the target could be reached around 2027-08-01 (10 installments). That is on or before the target date.",
    );
    assert.match(whatIfMessage(whatIf({ on_or_before_target_date: false }), plan()), /That is after the target date\.$/);
    assert.doesNotMatch(whatIfMessage(whatIf(), plan()), /target date\.$/);
    assert.match(whatIfMessage(whatIf({ installments_needed: 1 }), plan()), /\(1 installment\)/);
  });

  it("explains when no date can be calculated", () => {
    assert.match(whatIfMessage(whatIf({ outcome: "no_contribution", monthly_contribution: "0.00", installments_needed: null, estimated_completion_date: null }), plan()), /zero never reaches the target/);
    assert.match(
      whatIfMessage(whatIf({ outcome: "not_reachable_within_horizon", monthly_contribution: "0.01", installments_needed: null, estimated_completion_date: null }), plan()),
      /0\.01 EUR per installment the target would take more than 600 months, so no date is shown/,
    );
    assert.match(whatIfMessage(whatIf({ outcome: "already_funded" }), plan()), /Nothing is left to reach/);
    assert.match(whatIfMessage(whatIf({ outcome: "not_applicable" }), plan()), /archived Goal takes no contributions/);
  });

  it("is always labelled an estimate, not a promise", () => {
    assert.equal(WHAT_IF_DISCLAIMER, "An estimate, not a promise.");
  });
});

describe("copy never promises or judges affordability", () => {
  const everything = [
    PLAN_TITLE,
    PLAN_ASSUMPTION,
    PROGRESS_NOTE,
    WHAT_IF_HINT,
    WHAT_IF_DISCLAIMER,
    planStatusMessage(plan({ plan_status: "archived" })),
    planStatusMessage(plan({ plan_status: "already_funded" })),
    planStatusMessage(plan({ plan_status: "no_target_date" })),
    planStatusMessage(plan({ plan_status: "target_date_passed" })),
    planRequirement(plan())?.headline,
    planRequirement(plan())?.schedule,
    ...(["reaches_target", "no_contribution", "not_reachable_within_horizon", "already_funded", "not_applicable"] as const).map((outcome) =>
      whatIfMessage(whatIf({ outcome, on_or_before_target_date: true }), plan()),
    ),
  ].filter((text): text is string => typeof text === "string");

  it("passes the project's forbidden-copy rules (no transfer wording, no guarantee, no invented balances)", () => {
    for (const text of everything) {
      assert.deepEqual(findForbiddenCopy(text), [], text);
    }
  });

  it("makes no affordability, feasibility or certainty claim", () => {
    for (const text of everything) {
      assert.doesNotMatch(text, /\b(you can afford|affordable|feasible|achievable|on track|will reach|will be reached|definitely|certain)\b/i, text);
    }
  });
});

describe("the presentation does no money arithmetic", () => {
  it("has no number parsing or arithmetic", () => {
    const code = readFileSync(join(HERE, "goal-plan-view.ts"), "utf8").replace(/\/\/.*$/gm, "");

    assert.doesNotMatch(code, /parseFloat|Number\(|parseInt|\.toFixed|Math\.|\bBigInt\b/);
  });
});
