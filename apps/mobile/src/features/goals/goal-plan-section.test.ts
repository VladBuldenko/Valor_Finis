// VF-GOALS-PLANNING-001: wiring of the Goal plan into the app. Source checks in
// the project's usual style (React Native components cannot be mounted in the
// Node runner): the request contract, the cache keys, where the section sits on
// the Goal detail screen, accessibility, and that the existing contribution,
// withdrawal, priority and rule workflows are untouched.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const code = (file: string) => readFileSync(join(HERE, file), "utf8").replace(/\/\/.*$/gm, "");

describe("request contract", () => {
  const service = code("goal.service.ts");
  const planCall = service.slice(service.indexOf("export async function getGoalPlan"));

  it("POSTs to /goals/{id}/plan with an empty body or only monthly_contribution, abortable", () => {
    assert.match(planCall, /`\/api\/v1\/goals\/\$\{goalId\}\/plan`/);
    assert.match(planCall, /method: "POST"/);
    assert.match(planCall, /monthlyContribution === undefined\s*\?\s*\{\}\s*:\s*\{ monthly_contribution: monthlyContribution \}/);
    assert.match(planCall, /signal,/);
  });

  it("does no number handling: the amount travels as the string the user typed", () => {
    assert.doesNotMatch(planCall, /parseFloat|Number\(|parseInt|\.toFixed|Math\./);
  });

  it("the response type mirrors the backend contract", () => {
    const types = code("goal.types.ts");

    for (const field of [
      "remaining_amount", "overfunded_amount", "tracked_amount", "linked_amount", "required_per_installment",
      "installment_count", "first_installment_date", "last_installment_date", "horizon_months", "what_if",
      "estimated_completion_date", "on_or_before_target_date", "installments_needed",
    ]) {
      assert.match(types, new RegExp(`\\b${field}\\b`), field);
    }

    assert.match(types, /plan_status: GoalPlanStatus/);
    assert.match(types, /\| "target_date_passed"/);
  });
});

describe("the section", () => {
  const section = code("goal-plan-section.tsx");

  it("both queries sit under the Goal cache prefix that every Goal transaction invalidates", () => {
    assert.match(section, /queryKey: \["goals", userId, "plan", goalId, "base"\]/);
    assert.match(section, /queryKey: \["goals", userId, "plan", goalId, "estimate", estimate\]/);
  });

  it("asks for an estimate only when the user has entered a valid amount, and only then runs the estimate query", () => {
    assert.match(section, /enabled: Boolean\(userId\) && estimate !== null/);
    assert.match(section, /const canAsk = input !== "" && inputError === null;/);
    assert.match(section, /disabled=\{!canAsk\}/);
    assert.match(section, /setEstimate\(normalizeGoalDecimalAmount\(input\)\)/);
    assert.match(section, /validateGoalAmountInput\(input, "Monthly amount"\)/);
  });

  it("shows only what the view helpers derive from the backend response, with the loading/error/Retry boundary", () => {
    assert.match(section, /<QueryBoundary query=\{planQuery\} what="goal plan">/);
    assert.match(section, /planProgressRows\(plan\)/);
    assert.match(section, /planRequirement\(plan\)/);
    assert.match(section, /planStatusMessage\(plan\)/);
    assert.match(section, /whatIfMessage\(result\.what_if, result\)/);
    assert.match(section, /<QueryBoundary query=\{estimateQuery\} what="estimate">/);
    assert.doesNotMatch(section, /parseFloat|Number\(|parseInt|\.toFixed|Math\.|\bBigInt\b/);
  });

  it("states the assumption and the tracked-versus-reserved note, and hides the what-if for an archived Goal", () => {
    assert.match(section, /\{PLAN_ASSUMPTION\}/);
    assert.match(section, /\{PROGRESS_NOTE\}/);
    assert.match(section, /plan\.plan_status === "archived" \? null : \(/);
  });

  it("is accessible: a header, labelled input and buttons, an alert for a bad amount, live results", () => {
    assert.match(section, /accessibilityRole="header"/);
    assert.match(section, /accessibilityLabel="Monthly amount to try"/);
    assert.match(section, /accessibilityRole="button"\s+accessibilityLabel="Show estimate"\s+accessibilityState=\{\{ disabled: !canAsk \}\}/);
    assert.match(section, /accessibilityRole="alert" accessibilityLiveRegion="polite"/);
    assert.match(section, /<View accessibilityLiveRegion="polite">/);
    assert.match(section, /accessibilityLabel=\{`\$\{row\.label\}: \$\{row\.value\}`\}/);
    assert.match(section, /accessibilityLabel="Clear estimate"/);
  });

  it("creates nothing: no mutation, no write method", () => {
    assert.doesNotMatch(section, /useMutation|\.mutate\(|createGoalTransaction|updateGoal|PATCH|DELETE/);
  });
});

describe("the Goal detail screen", () => {
  const screen = code("goal-detail-screen.tsx");

  it("shows the plan section right after the Goal summary and before any funding form", () => {
    assert.ok(screen.indexOf("<GoalPlanSection model={goalPlan} />") > screen.indexOf("Target date: ${goal.target_date}"));
    assert.ok(screen.indexOf("<GoalPlanSection model={goalPlan} />") < screen.indexOf('Withdraw funds</Text>'));
    assert.ok(screen.indexOf("<GoalPlanSection model={goalPlan} />") < screen.indexOf('Add funds</Text>'));
    assert.match(screen, /const goalPlan = useGoalPlan\(id\);/);
  });

  it("pull-to-refresh re-reads the plan (and a requested estimate) with the rest of the Goal", () => {
    assert.match(screen, /refetcherOf\(goalPlan\.planQuery\)/);
    assert.match(screen, /goalPlan\.estimate !== null \? \[refetcherOf\(goalPlan\.estimateQuery\)\] : \[\]/);
  });

  it("the existing workflows are unchanged: one transaction mutation, the same guards, the same refreshes", () => {
    assert.equal((screen.match(/createTransactionMutation\.mutate\(/g) ?? []).length, 1);
    assert.match(screen, /if \(createTransactionMutation\.isPending \|\| !goal\) \{\s*return;/);
    assert.match(screen, /disabled=\{!canSubmitTransaction\}/);
    assert.match(screen, /invalidateGoalTransactionQueries\(\s*queryClient,\s*session\?\.user\.id,\s*id,/);
    assert.match(screen, /validateGoalAmountInput\(amount, "Amount"\)/);
  });

  it("the shared transaction invalidation prefix covers the plan keys", () => {
    const cache = code("goal-cache.ts");

    assert.match(cache, /queryClient\.invalidateQueries\(\{ queryKey: \["goals", userId\] \}\)/);
  });
});
