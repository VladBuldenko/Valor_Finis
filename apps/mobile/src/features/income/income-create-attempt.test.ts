import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { resolveCreateAttempt } from "../../lib/create-attempts.ts";
import { incomePayloadKey, toIncomeCreateInput, type IncomeCreatePayload } from "./income-create-attempt.ts";

const base: IncomeCreatePayload = {
  amount: "2500.00",
  currency: "EUR",
  received_at: "2026-11-05",
  source: "salary",
};

describe("income create payload key", () => {
  it("is the same for the same form state, however optional fields are omitted", () => {
    assert.equal(incomePayloadKey(base), incomePayloadKey({ ...base }));
    assert.equal(incomePayloadKey(base), incomePayloadKey({ ...base, description: undefined, account_id: undefined }));
  });

  it("differs when any field the backend compares differs", () => {
    const keys = new Set([
      incomePayloadKey(base),
      incomePayloadKey({ ...base, amount: "2500.01" }),
      incomePayloadKey({ ...base, currency: "USD" }),
      incomePayloadKey({ ...base, received_at: "2026-11-06" }),
      incomePayloadKey({ ...base, source: "gift" }),
      incomePayloadKey({ ...base, description: "x" }),
      incomePayloadKey({ ...base, account_id: "acc-1" }),
    ]);

    assert.equal(keys.size, 7);
  });

  it("builds a body that carries the attempt's key and the unchanged payload", () => {
    const { attempt } = resolveCreateAttempt([], "u1", incomePayloadKey(base), base, () => "key-1");

    assert.deepEqual(toIncomeCreateInput(attempt), { ...base, client_request_id: "key-1" });
  });
});
