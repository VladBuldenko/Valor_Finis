// Transfer create idempotency keys (VF-MVP-CORE-003): one key per logical request, the SAME
// key when an unconfirmed request is retried, a NEW key when the request changes.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  isSameTransferCreatePayload,
  resolveTransferCreateAttempt,
  toAccountTransferCreateInput,
  type TransferCreatePayload,
} from "./transfer-create-attempts.ts";

const payload: TransferCreatePayload = {
  source_account_id: "acc-src",
  destination_account_id: "acc-dst",
  amount: "300.00",
  transfer_date: "2026-11-11",
  description: null,
};

function keys() {
  let counter = 0;

  return () => `key-${(counter += 1)}`;
}

describe("resolveTransferCreateAttempt", () => {
  it("gives a first submission a new key and remembers the attempt", () => {
    const result = resolveTransferCreateAttempt([], payload, keys());

    assert.equal(result.attempt.clientRequestId, "key-1");
    assert.deepEqual(result.attempts, [result.attempt]);
  });

  it("reuses the key for an unchanged retry (the first response may have been lost)", () => {
    const generate = keys();
    const first = resolveTransferCreateAttempt([], payload, generate);
    const retry = resolveTransferCreateAttempt(first.attempts, { ...payload }, generate);

    assert.equal(retry.attempt.clientRequestId, first.attempt.clientRequestId);
    assert.equal(retry.attempts.length, 1);
  });

  it("a change to ANY of the five fields is a new logical request with a new key", () => {
    const changes: Partial<TransferCreatePayload>[] = [
      { source_account_id: "acc-other" },
      { destination_account_id: "acc-other" },
      { amount: "300.01" },
      { transfer_date: "2026-11-12" },
      { description: "rent" },
    ];

    for (const change of changes) {
      const generate = keys();
      const first = resolveTransferCreateAttempt([], payload, generate);
      const next = resolveTransferCreateAttempt(first.attempts, { ...payload, ...change }, generate);

      assert.notEqual(next.attempt.clientRequestId, first.attempt.clientRequestId, JSON.stringify(change));
      assert.equal(next.attempts.length, 2);
    }
  });

  it("editing the form back to an earlier payload reuses that earlier key (no duplicate of an ambiguous attempt)", () => {
    const generate = keys();
    const first = resolveTransferCreateAttempt([], payload, generate);
    const changed = resolveTransferCreateAttempt(first.attempts, { ...payload, amount: "5.00" }, generate);
    const back = resolveTransferCreateAttempt(changed.attempts, payload, generate);

    assert.equal(back.attempt.clientRequestId, first.attempt.clientRequestId);
    assert.equal(back.attempts.length, 2);
  });

  it("does not mutate the attempts it was given", () => {
    const first = resolveTransferCreateAttempt([], payload, keys());
    const snapshot = [...first.attempts];

    resolveTransferCreateAttempt(first.attempts, { ...payload, amount: "1.00" }, keys());

    assert.deepEqual(first.attempts, snapshot);
  });
});

describe("isSameTransferCreatePayload", () => {
  it("compares the exact values that are sent", () => {
    assert.equal(isSameTransferCreatePayload(payload, { ...payload }), true);
    assert.equal(isSameTransferCreatePayload(payload, { ...payload, amount: "300.0" }), false);
    assert.equal(isSameTransferCreatePayload(payload, { ...payload, description: "" }), false);
  });
});

describe("toAccountTransferCreateInput", () => {
  it("sends the key and the five fields, and omits a null description entirely", () => {
    const { attempt } = resolveTransferCreateAttempt([], payload, keys());
    const input = toAccountTransferCreateInput(attempt);

    assert.deepEqual(input, {
      client_request_id: "key-1",
      source_account_id: "acc-src",
      destination_account_id: "acc-dst",
      amount: "300.00",
      transfer_date: "2026-11-11",
    });
    assert.equal("description" in input, false);
  });

  it("sends a present description, and never any server-owned field", () => {
    const { attempt } = resolveTransferCreateAttempt([], { ...payload, description: "to savings" }, keys());
    const input = toAccountTransferCreateInput(attempt) as Record<string, unknown>;

    assert.equal(input.description, "to savings");

    for (const forbidden of ["user_id", "status", "currency", "planned_date", "effective_date", "posted_at"]) {
      assert.equal(forbidden in input, false, forbidden);
    }
  });
});
