// The Budget form rules (VF-MVP-CORE-004): what the form can know before a request is sent.
// The backend stays authoritative for calendar validity, duplicates, immutable fields and ownership.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { validateBudgetForm, type BudgetFormValues } from "./budget-validation.ts";

const valid: BudgetFormValues = {
  name: "Groceries",
  limitAmount: "400.00",
  startDate: "2026-11-01",
  endDate: "",
};

function errorOf(values: Partial<BudgetFormValues>): string | null {
  return validateBudgetForm({ ...valid, ...values });
}

describe("validateBudgetForm", () => {
  it("accepts a complete form with and without an end date", () => {
    assert.equal(errorOf({}), null);
    assert.equal(errorOf({ endDate: "2026-12-31" }), null);
    assert.equal(errorOf({ endDate: "2026-11-01" }), null, "ending on the start date is a one-day budget");
    assert.equal(errorOf({ endDate: "  " }), null, "a blank end date means no end");
  });

  it("requires a name that is not only whitespace", () => {
    assert.equal(errorOf({ name: "" }), "Name is required.");
    assert.equal(errorOf({ name: "   " }), "Name is required.");
  });

  it("accepts a positive limit written with a dot or a comma", () => {
    for (const limitAmount of ["1", "0.01", "10,5", " 400 ", "9999999999.99"]) {
      assert.equal(errorOf({ limitAmount }), null, limitAmount);
    }
  });

  it("rejects an empty, zero, negative or non-numeric limit", () => {
    for (const limitAmount of ["", " ", "0", "0.00", "-1", "-0.01", "abc", "1.2.3", "Infinity", "NaN"]) {
      assert.equal(errorOf({ limitAmount }), "Limit amount must be greater than zero.", JSON.stringify(limitAmount));
    }
  });

  it("requires the YYYY-MM-DD shape for both dates (calendar validity is the backend's call)", () => {
    for (const startDate of ["", "2026-1-5", "11/11/2026", "2026-11-01T00:00"]) {
      assert.equal(errorOf({ startDate }), "Start date must use YYYY-MM-DD format.", startDate);
    }

    assert.equal(errorOf({ endDate: "31.12.2026" }), "End date must use YYYY-MM-DD format.");
    assert.equal(errorOf({ startDate: "2026-02-30" }), null);
  });

  it("rejects an end date before the start date, so a form can never ask for an inverted budget", () => {
    assert.equal(errorOf({ endDate: "2026-10-31" }), "End date must be on or after the start date.");
  });

  it("reports the first problem only, in form order", () => {
    assert.equal(errorOf({ name: "", limitAmount: "0", startDate: "x" }), "Name is required.");
    assert.equal(errorOf({ limitAmount: "0", startDate: "x" }), "Limit amount must be greater than zero.");
    assert.equal(errorOf({ startDate: "x", endDate: "y" }), "Start date must use YYYY-MM-DD format.");
  });
});
