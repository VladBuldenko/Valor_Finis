// VF-GOALS-PLANNING-002C1: form validation and request building. Pure: amounts stay
// text (never a JavaScript Number), dates are compared as ISO strings, and only
// what the user changed is sent on an edit.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import {
  buildCreatePayload,
  buildUpdatePayload,
  isRealIsoDate,
  localIsoDate,
  normalizeObligationAmount,
  validateFutureObligationForm,
  valuesFromObligation,
  type FutureObligationFormValues,
} from "./future-obligation-validation.ts";
import type { FutureObligation } from "./future-obligation.types.ts";

const HERE = dirname(fileURLToPath(import.meta.url));

const form = (over: Partial<FutureObligationFormValues> = {}): FutureObligationFormValues => ({
  name: "Rent",
  schedule: "monthly",
  amount: "950.00",
  currency: "",
  firstDueDate: "2026-12-01",
  finalDueDate: "",
  description: "",
  ...over,
});

const bill = (over: Partial<FutureObligation> = {}): FutureObligation => ({
  id: "b1",
  user_id: "u1",
  name: "Rent",
  description: null,
  schedule: "monthly",
  amount: "950.00",
  currency: "EUR",
  first_due_date: "2026-12-01",
  final_due_date: null,
  status: "active",
  next_due_date: "2026-12-01",
  client_request_id: null,
  created_at: "2026-11-16T10:00:00Z",
  updated_at: "2026-11-16T10:00:00Z",
  ...over,
});

describe("amount", () => {
  it("accepts a positive amount with up to two decimals, and a comma separator", () => {
    for (const amount of ["0.01", "950", "950.5", "950.50", " 12,34 ", "9999999999.99"]) {
      assert.equal(validateFutureObligationForm(form({ amount })), null, amount);
    }

    assert.equal(normalizeObligationAmount(" 12,34 "), "12.34");
  });

  it("rejects an empty, zero, negative, over-precise, signed or non-numeric amount", () => {
    assert.match(validateFutureObligationForm(form({ amount: "" })) ?? "", /Amount is required/);

    for (const amount of ["0", "0.00", "00.0"]) {
      assert.match(validateFutureObligationForm(form({ amount })) ?? "", /greater than zero/, amount);
    }

    for (const amount of ["-5", "+5", "1.234", "1e3", "abc", "1.2.3", "NaN", "Infinity", "1,234.56"]) {
      assert.match(validateFutureObligationForm(form({ amount })) ?? "", /positive number with up to 2 decimal places/, amount);
    }
  });

  it("rejects an amount larger than the backend's 10 integer digits", () => {
    assert.match(validateFutureObligationForm(form({ amount: "12345678901" })) ?? "", /too large/);
    assert.equal(validateFutureObligationForm(form({ amount: "0000000001" })), null);
  });
});

describe("name, currency and description", () => {
  it("requires a name of at most 100 characters", () => {
    assert.match(validateFutureObligationForm(form({ name: "  " })) ?? "", /Name is required/);
    assert.match(validateFutureObligationForm(form({ name: "x".repeat(101) })) ?? "", /100 characters or fewer/);
    assert.equal(validateFutureObligationForm(form({ name: "x".repeat(100) })), null);
  });

  it("allows a blank currency (the base currency) or exactly three letters", () => {
    assert.equal(validateFutureObligationForm(form({ currency: "" })), null);
    assert.equal(validateFutureObligationForm(form({ currency: "usd" })), null);

    for (const currency of ["US", "USDD", "U1D", "€€€"]) {
      assert.match(validateFutureObligationForm(form({ currency })) ?? "", /exactly 3 letters/, currency);
    }
  });

  it("limits the note to 500 characters", () => {
    assert.match(validateFutureObligationForm(form({ description: "x".repeat(501) })) ?? "", /500 characters or fewer/);
    assert.equal(validateFutureObligationForm(form({ description: "x".repeat(500) })), null);
  });
});

describe("dates", () => {
  it("knows real calendar dates, including leap years", () => {
    for (const real of ["2026-12-31", "2028-02-29", "2000-02-29", "2026-02-28", "2026-04-30"]) {
      assert.equal(isRealIsoDate(real), true, real);
    }

    for (const fake of ["2026-02-29", "2027-02-29", "2100-02-29", "2026-04-31", "2026-13-01", "2026-00-10", "2026-12-00", "2026-1-1", "tomorrow", ""]) {
      assert.equal(isRealIsoDate(fake), false, fake);
    }
  });

  it("requires a real first due date between 2000 and 2100", () => {
    assert.match(validateFutureObligationForm(form({ firstDueDate: "" })) ?? "", /First due date must use YYYY-MM-DD/);
    assert.match(validateFutureObligationForm(form({ firstDueDate: "31/12/2026" })) ?? "", /YYYY-MM-DD/);
    assert.match(validateFutureObligationForm(form({ firstDueDate: "2026-02-30" })) ?? "", /not a real calendar date/);
    assert.match(validateFutureObligationForm(form({ firstDueDate: "1999-12-31" })) ?? "", /between 2000-01-01 and 2100-12-31/);
    assert.match(validateFutureObligationForm(form({ firstDueDate: "2101-01-01" })) ?? "", /between/);
    assert.equal(validateFutureObligationForm(form({ firstDueDate: "2028-02-29" })), null);
    assert.equal(validateFutureObligationForm(form({ firstDueDate: "2020-05-01" })), null); // past is fine
  });

  it("names the date 'Due date' for a one-time bill and 'First due date' for a monthly one", () => {
    assert.match(validateFutureObligationForm(form({ schedule: "one_time", firstDueDate: "" })) ?? "", /^Due date must/);
    assert.match(validateFutureObligationForm(form({ schedule: "monthly", firstDueDate: "" })) ?? "", /^First due date must/);
  });

  it("checks an optional final due date for a monthly bill: real, in range and not before the first", () => {
    assert.equal(validateFutureObligationForm(form({ finalDueDate: "" })), null);
    assert.equal(validateFutureObligationForm(form({ finalDueDate: "2026-12-01" })), null);
    assert.equal(validateFutureObligationForm(form({ finalDueDate: "2027-06-30" })), null);
    assert.match(validateFutureObligationForm(form({ finalDueDate: "2026-11-30" })) ?? "", /cannot be before the first due date/);
    assert.match(validateFutureObligationForm(form({ finalDueDate: "2027-02-30" })) ?? "", /not a real calendar date/);
    assert.match(validateFutureObligationForm(form({ finalDueDate: "soon" })) ?? "", /Final due date must use/);
  });

  it("ignores the final due date of a one-time bill (it has none)", () => {
    assert.equal(validateFutureObligationForm(form({ schedule: "one_time", finalDueDate: "garbage" })), null);
  });

  it("reports the first problem only, in field order", () => {
    assert.match(validateFutureObligationForm(form({ name: "", amount: "0", firstDueDate: "x" })) ?? "", /Name is required/);
    assert.match(validateFutureObligationForm(form({ amount: "0", firstDueDate: "x" })) ?? "", /greater than zero/);
  });

  it("builds a local calendar date, not a UTC one", () => {
    assert.equal(localIsoDate(new Date(2026, 10, 5, 23, 59)), "2026-11-05");
    assert.equal(localIsoDate(new Date(2028, 1, 29, 0, 1)), "2028-02-29");
  });
});

describe("create payload", () => {
  it("is normalized and omits a blank currency, note and final date", () => {
    assert.deepEqual(buildCreatePayload(form({ name: "  Rent ", amount: "950,5" })), {
      name: "Rent",
      schedule: "monthly",
      amount: "950.5",
      first_due_date: "2026-12-01",
    });
  });

  it("includes an upper-cased currency, a trimmed note and a monthly final due date", () => {
    assert.deepEqual(
      buildCreatePayload(form({ currency: " usd ", description: " Flat ", finalDueDate: "2027-06-01" })),
      { name: "Rent", schedule: "monthly", amount: "950.00", first_due_date: "2026-12-01", currency: "USD", final_due_date: "2027-06-01", description: "Flat" },
    );
  });

  it("never sends a final due date for a one-time bill", () => {
    const payload = buildCreatePayload(form({ schedule: "one_time", finalDueDate: "2027-06-01" }));

    assert.equal("final_due_date" in payload, false);
    assert.equal(payload.schedule, "one_time");
  });

  it("keeps the amount as the user's text: no number conversion", () => {
    assert.equal(buildCreatePayload(form({ amount: "0.10" })).amount, "0.10");
    assert.equal(buildCreatePayload(form({ amount: "9999999999.99" })).amount, "9999999999.99");
  });
});

describe("edit: only changed fields are sent", () => {
  it("sends nothing when nothing changed", () => {
    assert.deepEqual(buildUpdatePayload(bill(), valuesFromObligation(bill())), {});
  });

  it("sends exactly what changed", () => {
    const values = { ...valuesFromObligation(bill()), name: "Flat rent", amount: "975.00", firstDueDate: "2027-01-05" };

    assert.deepEqual(buildUpdatePayload(bill(), values), { name: "Flat rent", amount: "975.00", first_due_date: "2027-01-05" });
  });

  it("clears the note and the final due date with an explicit null, and only when they were set", () => {
    const original = bill({ description: "Note", final_due_date: "2027-06-01" });
    const cleared = { ...valuesFromObligation(original), description: "  ", finalDueDate: "" };

    assert.deepEqual(buildUpdatePayload(original, cleared), { description: null, final_due_date: null });
    assert.deepEqual(buildUpdatePayload(bill(), valuesFromObligation(bill())), {});
  });

  it("sets a final due date on a monthly bill that had none", () => {
    const values = { ...valuesFromObligation(bill()), finalDueDate: "2027-09-01" };

    assert.deepEqual(buildUpdatePayload(bill(), values), { final_due_date: "2027-09-01" });
  });

  it("never sends a final due date or the schedule kind for a one-time bill", () => {
    const original = bill({ schedule: "one_time", final_due_date: null });
    const changed = { ...valuesFromObligation(original), finalDueDate: "2027-09-01", name: "Tax" };

    assert.deepEqual(buildUpdatePayload(original, changed), { name: "Tax" });
  });

  it("an upper-cased currency that matches is not a change; a different one is", () => {
    assert.deepEqual(buildUpdatePayload(bill(), { ...valuesFromObligation(bill()), currency: "eur" }), {});
    assert.deepEqual(buildUpdatePayload(bill(), { ...valuesFromObligation(bill()), currency: "usd" }), { currency: "USD" });
  });

  it("an equivalent amount spelling with a comma is normalized before comparing", () => {
    assert.deepEqual(buildUpdatePayload(bill({ amount: "950.5" }), { ...valuesFromObligation(bill({ amount: "950.5" })), amount: "950,5" }), {});
  });

  it("the form shows the stored values", () => {
    assert.deepEqual(valuesFromObligation(bill({ description: "Flat", final_due_date: "2027-06-01" })), {
      name: "Rent",
      schedule: "monthly",
      amount: "950.00",
      currency: "EUR",
      firstDueDate: "2026-12-01",
      finalDueDate: "2027-06-01",
      description: "Flat",
    });
  });
});

describe("no money arithmetic", () => {
  it("has no number parsing or arithmetic on amounts", () => {
    const code = readFileSync(join(HERE, "future-obligation-validation.ts"), "utf8").replace(/\/\/.*$/gm, "");
    const withoutDateParts = code.replace(/Number\(value\.slice\([^)]*\)\)/g, "");

    assert.doesNotMatch(withoutDateParts, /parseFloat|Number\(|parseInt|\.toFixed|Math\.|\bBigInt\b/);
  });
});
