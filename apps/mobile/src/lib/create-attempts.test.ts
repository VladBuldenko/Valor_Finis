import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { createSubmitGuard, resolveCreateAttempt, type CreateAttempt } from "./create-attempts.ts";

type Payload = { amount: string };

function ids() {
  let next = 0;

  return () => `id-${(next += 1)}`;
}

describe("create attempt lifecycle", () => {
  it("gives a new logical operation a new key", () => {
    const generate = ids();
    const first = resolveCreateAttempt<Payload>([], "u1", "a", { amount: "1.00" }, generate);
    const second = resolveCreateAttempt<Payload>([], "u1", "a", { amount: "1.00" }, generate);

    // Two independent forms (empty attempt lists) = two operations, even with identical content.
    assert.notEqual(first.attempt.clientRequestId, second.attempt.clientRequestId);
  });

  it("reuses the key of the same payload when an outcome-unknown submission is retried", () => {
    const generate = ids();
    const first = resolveCreateAttempt<Payload>([], "u1", "a", { amount: "1.00" }, generate);
    const retry = resolveCreateAttempt(first.attempts, "u1", "a", { amount: "1.00" }, generate);

    assert.equal(retry.attempt.clientRequestId, first.attempt.clientRequestId);
    assert.equal(retry.attempts.length, 1);
  });

  it("gives a changed payload a new key and still remembers the earlier one", () => {
    const generate = ids();
    const first = resolveCreateAttempt<Payload>([], "u1", "a", { amount: "1.00" }, generate);
    const changed = resolveCreateAttempt(first.attempts, "u1", "b", { amount: "2.00" }, generate);
    const editedBack = resolveCreateAttempt(changed.attempts, "u1", "a", { amount: "1.00" }, generate);

    assert.notEqual(changed.attempt.clientRequestId, first.attempt.clientRequestId);
    // Editing the form back to the first payload reuses the FIRST key: that earlier
    // submission may have been saved, so it must never be duplicated.
    assert.equal(editedBack.attempt.clientRequestId, first.attempt.clientRequestId);
    assert.equal(editedBack.attempts.length, 2);
  });

  it("never reuses an attempt made for another user", () => {
    const generate = ids();
    const mine = resolveCreateAttempt<Payload>([], "u1", "a", { amount: "1.00" }, generate);
    const theirs = resolveCreateAttempt(mine.attempts, "u2", "a", { amount: "1.00" }, generate);

    assert.notEqual(theirs.attempt.clientRequestId, mine.attempt.clientRequestId);
    assert.deepEqual(
      theirs.attempts.map((attempt: CreateAttempt<Payload>) => attempt.scope),
      ["u2"],
    );
  });

  it("does not mutate the list it is given", () => {
    const generate = ids();
    const original: CreateAttempt<Payload>[] = [];

    resolveCreateAttempt(original, "u1", "a", { amount: "1.00" }, generate);

    assert.deepEqual(original, []);
  });

  it("a cleared list (after a success) means the next submission is a new operation", () => {
    const generate = ids();
    const first = resolveCreateAttempt<Payload>([], "u1", "a", { amount: "1.00" }, generate);
    const afterSuccess = resolveCreateAttempt([], "u1", "a", { amount: "1.00" }, generate);

    assert.notEqual(afterSuccess.attempt.clientRequestId, first.attempt.clientRequestId);
  });
});

describe("synchronous submit guard", () => {
  it("lets exactly one of two taps delivered before any re-render through", () => {
    const guard = createSubmitGuard();

    assert.equal(guard.tryEnter(), true);
    assert.equal(guard.tryEnter(), false);
    assert.equal(guard.isBusy(), true);
  });

  it("is released after the request settles, so the next submission can start", () => {
    const guard = createSubmitGuard();

    guard.tryEnter();
    guard.release();

    assert.equal(guard.isBusy(), false);
    assert.equal(guard.tryEnter(), true);
  });
});
