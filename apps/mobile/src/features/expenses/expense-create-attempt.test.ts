import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { resolveCreateAttempt } from "../../lib/create-attempts.ts";
import { expensePayloadKey, toExpenseCreateInput, type ExpenseCreatePayload } from "./expense-create-attempt.ts";

const base: ExpenseCreatePayload = {
  category_id: null,
  title: "Groceries",
  amount: "35.50",
  currency: "EUR",
  expense_date: "2026-11-06",
  description: null,
};

describe("expense create payload key", () => {
  it("is the same for the same form state, however optional fields are omitted", () => {
    assert.equal(expensePayloadKey(base), expensePayloadKey({ ...base }));
    assert.equal(
      expensePayloadKey(base),
      expensePayloadKey({ ...base, category_id: undefined, description: undefined, account_id: undefined }),
    );
  });

  it("differs when any field the backend compares differs", () => {
    const keys = new Set([
      expensePayloadKey(base),
      expensePayloadKey({ ...base, category_id: "cat-1" }),
      expensePayloadKey({ ...base, title: "Groceries 2" }),
      expensePayloadKey({ ...base, amount: "35.51" }),
      expensePayloadKey({ ...base, currency: "USD" }),
      expensePayloadKey({ ...base, expense_date: "2026-11-07" }),
      expensePayloadKey({ ...base, description: "x" }),
      expensePayloadKey({ ...base, source: "receipt" }),
      expensePayloadKey({ ...base, account_id: "acc-1" }),
    ]);

    assert.equal(keys.size, 9);
  });

  it("builds a body that carries the attempt's key and the unchanged payload", () => {
    const { attempt } = resolveCreateAttempt([], "u1", expensePayloadKey(base), base, () => "key-1");

    assert.deepEqual(toExpenseCreateInput(attempt), { ...base, client_request_id: "key-1" });
  });
});
