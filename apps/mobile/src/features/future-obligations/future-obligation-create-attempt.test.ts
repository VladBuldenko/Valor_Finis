// VF-GOALS-PLANNING-002C1: duplicate-submit protection on the client. A retry of the
// same logical bill reuses its client_request_id, so the backend replays the saved
// bill instead of adding a second one; a different bill gets a new key.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { createSubmitGuard, resolveCreateAttempt, type CreateAttempt } from "../../lib/create-attempts.ts";
import {
  futureObligationPayloadKey,
  toFutureObligationCreateInput,
  type FutureObligationCreatePayload,
} from "./future-obligation-create-attempt.ts";

const payload = (over: Partial<FutureObligationCreatePayload> = {}): FutureObligationCreatePayload => ({
  name: "Rent",
  schedule: "monthly",
  amount: "950.00",
  first_due_date: "2026-12-01",
  ...over,
});

let counter = 0;
const nextId = () => `key-${++counter}`;

describe("payload key", () => {
  it("is the same for the same request and different for any material change", () => {
    assert.equal(futureObligationPayloadKey(payload()), futureObligationPayloadKey(payload()));

    for (const change of [
      { name: "Flat" },
      { schedule: "one_time" as const },
      { amount: "951.00" },
      { currency: "USD" },
      { first_due_date: "2026-12-02" },
      { final_due_date: "2027-01-01" },
      { description: "Note" },
    ]) {
      assert.notEqual(futureObligationPayloadKey(payload()), futureObligationPayloadKey(payload(change)), JSON.stringify(change));
    }
  });

  it("treats an omitted optional field as null, the way the form always omits a blank one", () => {
    assert.equal(
      futureObligationPayloadKey(payload()),
      futureObligationPayloadKey({ ...payload(), currency: undefined, final_due_date: undefined, description: undefined }),
    );
  });
});

describe("attempts", () => {
  it("reuses the key when the same bill is submitted again after a failure", () => {
    const first = resolveCreateAttempt<FutureObligationCreatePayload>([], "user-1", futureObligationPayloadKey(payload()), payload(), nextId);
    const again = resolveCreateAttempt(first.attempts, "user-1", futureObligationPayloadKey(payload()), payload(), nextId);

    assert.equal(again.attempt.clientRequestId, first.attempt.clientRequestId);
    assert.equal(again.attempts.length, 1);
  });

  it("uses a new key for a different bill, and still remembers the earlier one", () => {
    const first = resolveCreateAttempt<FutureObligationCreatePayload>([], "user-1", futureObligationPayloadKey(payload()), payload(), nextId);
    const other = payload({ amount: "1000.00" });
    const second = resolveCreateAttempt(first.attempts, "user-1", futureObligationPayloadKey(other), other, nextId);
    const back = resolveCreateAttempt(second.attempts, "user-1", futureObligationPayloadKey(payload()), payload(), nextId);

    assert.notEqual(second.attempt.clientRequestId, first.attempt.clientRequestId);
    assert.equal(back.attempt.clientRequestId, first.attempt.clientRequestId);
  });

  it("never reuses another user's attempt", () => {
    const first = resolveCreateAttempt<FutureObligationCreatePayload>([], "user-1", futureObligationPayloadKey(payload()), payload(), nextId);
    const other = resolveCreateAttempt(first.attempts, "user-2", futureObligationPayloadKey(payload()), payload(), nextId);

    assert.notEqual(other.attempt.clientRequestId, first.attempt.clientRequestId);
  });

  it("the request carries the payload and its key", () => {
    const attempt: CreateAttempt<FutureObligationCreatePayload> = { clientRequestId: "abc", scope: "u", key: "k", payload: payload() };

    assert.deepEqual(toFutureObligationCreateInput(attempt), { ...payload(), client_request_id: "abc" });
  });
});

describe("the submit guard", () => {
  it("lets exactly one of two immediate taps through until it is released", () => {
    const guard = createSubmitGuard();

    assert.equal(guard.tryEnter(), true);
    assert.equal(guard.tryEnter(), false);
    guard.release();
    assert.equal(guard.tryEnter(), true);
  });
});
