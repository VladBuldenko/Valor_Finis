import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  normalizeExpenseAmount,
  validateExpenseForm,
  type ExpenseFormValues,
} from "./expense-validation.ts";

const validValues: ExpenseFormValues = {
  title: "Groceries",
  amount: "12.50",
  currency: "USD",
  expenseDate: "2026-03-15",
  description: "Weekly shop",
};

function validate(overrides: Partial<ExpenseFormValues>): string | null {
  return validateExpenseForm({ ...validValues, ...overrides });
}

describe("normalizeExpenseAmount", () => {
  it("trims whitespace and converts a comma separator to a point", () => {
    assert.equal(normalizeExpenseAmount("  12,50 "), "12.50");
  });

  it("leaves an already normalized amount untouched", () => {
    assert.equal(normalizeExpenseAmount("12.50"), "12.50");
  });

  it("keeps the value a string so decimal precision is preserved", () => {
    assert.equal(normalizeExpenseAmount("9007199254740993.99"), "9007199254740993.99");
  });
});

describe("validateExpenseForm", () => {
  it("accepts a fully valid form", () => {
    assert.equal(validateExpenseForm(validValues), null);
  });

  describe("amount", () => {
    for (const amount of ["5", "5.1", "5.10", "0.01", "999999999.99", " 7.25 "]) {
      it(`accepts ${JSON.stringify(amount)}`, () => {
        assert.equal(validate({ amount }), null);
      });
    }

    it("accepts a comma decimal separator", () => {
      assert.equal(validate({ amount: "12,50" }), null);
    });

    it("requires an amount", () => {
      assert.equal(validate({ amount: "" }), "Amount is required.");
      assert.equal(validate({ amount: "   " }), "Amount is required.");
    });

    for (const amount of ["0", "0.0", "0.00", "000.00", "0,00"]) {
      it(`rejects zero ${JSON.stringify(amount)}`, () => {
        assert.equal(validate({ amount }), "Amount must be greater than zero.");
      });
    }

    for (const amount of ["-5", "-0.01", "+5"]) {
      it(`rejects signed amount ${JSON.stringify(amount)}`, () => {
        assert.equal(
          validate({ amount }),
          "Amount must be a positive number with up to 2 decimal places.",
        );
      });
    }

    for (const amount of ["1.234", "0.001", "10,999"]) {
      it(`rejects more than 2 decimal places in ${JSON.stringify(amount)}`, () => {
        assert.equal(
          validate({ amount }),
          "Amount must be a positive number with up to 2 decimal places.",
        );
      });
    }

    for (const amount of ["abc", "1e3", "1.", ".5", "1.2.3", "1,5,0", "12 50", "$5"]) {
      it(`rejects malformed amount ${JSON.stringify(amount)}`, () => {
        assert.equal(
          validate({ amount }),
          "Amount must be a positive number with up to 2 decimal places.",
        );
      });
    }
  });

  describe("currency", () => {
    it("accepts lowercase and padded codes (they are uppercased before checking)", () => {
      assert.equal(validate({ currency: "eur" }), null);
      assert.equal(validate({ currency: " pln " }), null);
    });

    for (const currency of ["", "US", "USDD", "U5D", "12$", "€"]) {
      it(`rejects ${JSON.stringify(currency)}`, () => {
        assert.equal(validate({ currency }), "Currency must be exactly 3 letters.");
      });
    }
  });

  describe("title", () => {
    it("requires a title", () => {
      assert.equal(validate({ title: "" }), "Title is required.");
      assert.equal(validate({ title: "   " }), "Title is required.");
    });

    it("accepts a title of exactly 120 characters", () => {
      assert.equal(validate({ title: "a".repeat(120) }), null);
    });

    it("rejects a title of 121 characters", () => {
      assert.equal(
        validate({ title: "a".repeat(121) }),
        "Title must be 120 characters or fewer.",
      );
    });

    it("measures the trimmed title", () => {
      assert.equal(validate({ title: `  ${"a".repeat(120)}  ` }), null);
    });
  });

  describe("description", () => {
    it("allows an empty description", () => {
      assert.equal(validate({ description: "" }), null);
    });

    it("accepts a description of exactly 500 characters", () => {
      assert.equal(validate({ description: "a".repeat(500) }), null);
    });

    it("rejects a description of 501 characters", () => {
      assert.equal(
        validate({ description: "a".repeat(501) }),
        "Description must be 500 characters or fewer.",
      );
    });

    it("measures the trimmed description", () => {
      assert.equal(validate({ description: `  ${"a".repeat(500)}  ` }), null);
    });
  });

  describe("expense date", () => {
    it("accepts a YYYY-MM-DD date", () => {
      assert.equal(validate({ expenseDate: "2026-12-31" }), null);
      assert.equal(validate({ expenseDate: " 2026-12-31 " }), null);
    });

    for (const expenseDate of [
      "",
      "2026-1-01",
      "2026-01-1",
      "26-01-01",
      "20260101",
      "2026/01/01",
      "01-01-2026",
      "2026-01-01T00:00:00Z",
    ]) {
      it(`rejects ${JSON.stringify(expenseDate)}`, () => {
        assert.equal(validate({ expenseDate }), "Date must use YYYY-MM-DD format.");
      });
    }

    it("checks the shape only: calendar validity is left to the backend", () => {
      assert.equal(validate({ expenseDate: "2026-02-31" }), null);
    });
  });

  describe("error precedence", () => {
    it("reports the first failing field in title, amount, currency, date, description order", () => {
      const allInvalid: ExpenseFormValues = {
        title: "",
        amount: "-1",
        currency: "X",
        expenseDate: "bad",
        description: "a".repeat(501),
      };

      assert.equal(validateExpenseForm(allInvalid), "Title is required.");
      assert.equal(
        validateExpenseForm({ ...allInvalid, title: "ok" }),
        "Amount must be a positive number with up to 2 decimal places.",
      );
      assert.equal(
        validateExpenseForm({ ...allInvalid, title: "ok", amount: "1" }),
        "Currency must be exactly 3 letters.",
      );
      assert.equal(
        validateExpenseForm({ ...allInvalid, title: "ok", amount: "1", currency: "USD" }),
        "Date must use YYYY-MM-DD format.",
      );
      assert.equal(
        validateExpenseForm({
          ...allInvalid,
          title: "ok",
          amount: "1",
          currency: "USD",
          expenseDate: "2026-01-01",
        }),
        "Description must be 500 characters or fewer.",
      );
    });
  });
});
