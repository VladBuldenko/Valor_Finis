// VF-MVP-MOBILE-UX-001: a Goal transaction amount that is not a valid positive money string is EXPLAINED under the
// field (the submit button was already disabled, silently). Also the focused check of the empty Goal form.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import { validateGoalAmountInput, validateGoalDecimalAmount } from "./goal-amount-validation.ts";
import { validateGoalForm } from "./goal-validation.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const code = (file: string) => readFileSync(join(HERE, file), "utf8").replace(/\/\/.*$/gm, "");

describe("amount feedback while typing", () => {
  it("an empty field says nothing (the button just stays disabled until something is typed)", () => {
    assert.equal(validateGoalAmountInput("", "Amount"), null);
  });

  it("zero and negative amounts are explained, with the same message a submit would give", () => {
    assert.match(validateGoalAmountInput("0.00", "Amount") ?? "", /greater than zero/);
    assert.match(validateGoalAmountInput("0", "Amount") ?? "", /greater than zero/);
    assert.match(validateGoalAmountInput("-50.00", "Amount") ?? "", /positive number/);

    for (const value of ["0.00", "-50.00", "abc", "1.234", "1e3", "5 0", " "]) {
      const message = validateGoalAmountInput(value, "Amount");

      assert.ok(message, `${JSON.stringify(value)} must be explained`);
      assert.equal(message, validateGoalDecimalAmount(value, "Amount"), `${JSON.stringify(value)} reuses the existing validator`);
    }
  });

  it("valid money strings are accepted silently, however large: capacity is the backend's decision", () => {
    for (const value of ["50", "50.00", "0.01", "1,5", "999999999.99"]) {
      assert.equal(validateGoalAmountInput(value, "Amount"), null, value);
    }
  });
});

describe("the Goal detail screen shows it, accessibly, without touching the submit guards", () => {
  const screen = code("goal-detail-screen.tsx");
  const amountField = screen.slice(screen.indexOf("Amount *"), screen.indexOf("Description</Text>"));

  it("the message sits directly under the Amount input, reusing the screen's error style and announcing itself", () => {
    assert.match(amountField, /<TextInput[\s\S]*?keyboardType="decimal-pad"[\s\S]*?\/>\s*\{amountValidationError \? \(/);
    assert.match(amountField, /<Text\s+style=\{styles\.errorText\}\s+accessibilityRole="alert"\s+accessibilityLiveRegion="polite"\s*>\s*\{amountValidationError\}/);
    assert.match(screen, /const amountValidationError = validateGoalAmountInput\(amount, "Amount"\);/);
  });

  it("the disabled guard and the duplicate-submission guard are unchanged, and nothing is retried or computed", () => {
    assert.match(screen, /const canSubmitTransaction =\s*Boolean\(amount\) &&\s*!amountValidationError &&/);
    assert.match(screen, /disabled=\{!canSubmitTransaction\}/);
    assert.match(screen, /if \(createTransactionMutation\.isPending \|\| !goal\) \{\s*return;/);
    assert.equal((screen.match(/createTransactionMutation\.mutate\(/g) ?? []).length, 1);
    assert.doesNotMatch(screen, /\bretry\b|parseFloat|Number\(|\.toFixed|Math\./);
  });

  it("backend failures keep their own path (409 / 422 are mapped from the response, not predicted here)", () => {
    assert.match(screen, /readApiFailure|getApiErrorMessage/);
    assert.doesNotMatch(amountField, /reservable|capacity|balance/i);
  });
});

describe("empty Goal form (check, no change): it IS explained, and nothing is sent", () => {
  it("an empty form fails with 'Name is required.' and a zero target is explained", () => {
    assert.equal(validateGoalForm({ name: "", targetAmount: "", targetDate: "" }), "Name is required.");
    assert.equal(validateGoalForm({ name: "   ", targetAmount: "100.00", targetDate: "" }), "Name is required.");
    assert.match(validateGoalForm({ name: "Trip", targetAmount: "0", targetDate: "" }) ?? "", /Target amount must be greater than zero/);
    assert.equal(validateGoalForm({ name: "Trip", targetAmount: "100.00", targetDate: "" }), null);
  });

  it("the create screen alerts with that message and returns before any request", () => {
    const create = code("goal-create-screen.tsx");
    const handler = create.slice(create.indexOf("function handleCreateGoal"), create.indexOf("return (", create.indexOf("function handleCreateGoal")));

    assert.match(handler, /const validationError = validateGoalForm\(/);
    assert.match(handler, /if \(validationError\) \{\s*Alert\.alert\("Invalid goal", validationError\);\s*return;\s*\}/);
    assert.ok(handler.indexOf("Alert.alert") < handler.indexOf("createGoalMutation.mutate("), "the alert comes first");
  });
});
