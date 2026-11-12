// The receipt review form rules (VF-MVP-CORE-005). Confirming a receipt creates an Expense, so the form
// follows the manual Expense rules; the backend stays authoritative for calendar validity, ownership,
// archived Accounts and currency compatibility.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { validateReceiptConfirmForm, type ReceiptConfirmFormValues } from "./receipt-validation.ts";

const valid: ReceiptConfirmFormValues = {
  title: "LIDL",
  amount: "3.68",
  currency: "EUR",
  expenseDate: "2026-11-11",
  description: "",
};

const errorOf = (overrides: Partial<ReceiptConfirmFormValues>) => validateReceiptConfirmForm({ ...valid, ...overrides });

describe("validateReceiptConfirmForm", () => {
  it("accepts the detected values as they come from OCR, and corrected ones", () => {
    assert.equal(validateReceiptConfirmForm(valid), null);
    assert.equal(errorOf({ title: "Lidl Süd", amount: "12,34", currency: "usd", description: "weekly shop" }), null);
  });

  it("requires every value OCR may have failed to detect (blank fields are not invented)", () => {
    for (const blank of ["title", "amount", "currency", "expenseDate"] as const) {
      assert.notEqual(errorOf({ [blank]: "" }), null, blank);
      assert.notEqual(errorOf({ [blank]: "   " }), null, blank);
    }
  });

  it("rejects amounts that are not a positive money value with at most 2 decimals", () => {
    for (const amount of ["0", "0.00", "-5", "1.234", "abc", "1e3", "1.2.3", "12 34"]) {
      assert.notEqual(errorOf({ amount }), null, amount);
    }
  });

  it("rejects a currency that is not exactly three letters, and a date that is not YYYY-MM-DD", () => {
    for (const currency of ["EU", "EURO", "E1R", "12E"]) {
      assert.equal(errorOf({ currency }), "Currency must be exactly 3 letters.", currency);
    }
    for (const expenseDate of ["11/11/2026", "2026-1-5", "2026-11-11T10:00"]) {
      assert.equal(errorOf({ expenseDate }), "Date must use YYYY-MM-DD format.", expenseDate);
    }
  });

  it("limits title to 120 and description to 500 characters", () => {
    assert.equal(errorOf({ title: "x".repeat(120) }), null);
    assert.notEqual(errorOf({ title: "x".repeat(121) }), null);
    assert.equal(errorOf({ description: "x".repeat(500) }), null);
    assert.notEqual(errorOf({ description: "x".repeat(501) }), null);
  });
});
