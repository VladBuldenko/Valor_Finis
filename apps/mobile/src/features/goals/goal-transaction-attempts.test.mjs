// Focused tests for goal-transaction-attempts.ts (VF-020B3). They use only
// Node's built-in test runner -- no extra dependency -- and import the
// TypeScript helper directly through Node's type stripping (default from
// Node 22.18; the pinned Node 22.13 needs the flag, which later versions
// still accept):
//   node --experimental-strip-types --test src/features/goals/goal-transaction-attempts.test.mjs
// This file is plain JavaScript on purpose: the app's tsconfig has no Node
// types and does not allow ".ts" import paths, and changing either just for
// tests is out of scope. The helper itself stays fully type-checked by tsc.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  canonicalizeGoalAmount,
  getGoalTransactionDisplayDate,
  resolveGoalTransactionAttempt,
  toGoalTransactionCreateInput,
} from "./goal-transaction-attempts.ts";

const GOAL_ID = "11111111-1111-4111-8111-111111111111";

function payload(overrides = {}) {
  return {
    goalId: GOAL_ID,
    type: "contribution",
    amount: "10.00",
    description: null,
    ...overrides,
  };
}

function sequentialKeys() {
  let counter = 0;

  return () => {
    counter += 1;
    return `key-${counter}`;
  };
}

test("an unchanged retry reuses the same client_request_id", () => {
  const generate = sequentialKeys();

  const first = resolveGoalTransactionAttempt([], payload(), generate);
  const retry = resolveGoalTransactionAttempt(first.attempts, payload(), generate);

  assert.equal(first.attempt.clientRequestId, "key-1");
  assert.equal(retry.attempt.clientRequestId, "key-1");
  assert.equal(retry.attempts.length, 1);
});

test("a materially changed payload gets a new key", () => {
  const generate = sequentialKeys();
  const first = resolveGoalTransactionAttempt([], payload(), generate);

  const changes = [
    { amount: "11.00" },
    { type: "withdrawal" },
    { description: "Payday" },
    { goalId: "22222222-2222-4222-8222-222222222222" },
  ];

  for (const change of changes) {
    const changed = resolveGoalTransactionAttempt(first.attempts, payload(change), generate);
    assert.notEqual(changed.attempt.clientRequestId, first.attempt.clientRequestId);
  }
});

test("returning to an earlier failed payload reuses that payload's key", () => {
  const generate = sequentialKeys();
  const first = resolveGoalTransactionAttempt([], payload(), generate);
  const edited = resolveGoalTransactionAttempt(first.attempts, payload({ amount: "12.00" }), generate);

  const back = resolveGoalTransactionAttempt(edited.attempts, payload(), generate);

  assert.equal(back.attempt.clientRequestId, "key-1");
  assert.equal(back.attempts.length, 2);
});

test("after a success the cleared attempt list starts a genuinely new key", () => {
  const generate = sequentialKeys();
  resolveGoalTransactionAttempt([], payload(), generate);

  // The screen clears its attempts after a successful create.
  const next = resolveGoalTransactionAttempt([], payload(), generate);

  assert.equal(next.attempt.clientRequestId, "key-2");
});

test("does not mutate the caller's attempt list", () => {
  const attempts = Object.freeze([]);

  const result = resolveGoalTransactionAttempt(attempts, payload(), sequentialKeys());

  assert.equal(attempts.length, 0);
  assert.equal(result.attempts.length, 1);
});

test("amounts are canonicalized without Number parsing", () => {
  assert.equal(canonicalizeGoalAmount("10"), "10.00");
  assert.equal(canonicalizeGoalAmount("10.0"), "10.00");
  assert.equal(canonicalizeGoalAmount("10.5"), "10.50");
  assert.equal(canonicalizeGoalAmount("010.00"), "10.00");
  assert.equal(canonicalizeGoalAmount("0.5"), "0.50");
  assert.equal(canonicalizeGoalAmount("12345678901.99"), "12345678901.99");
});

test("equivalent amounts typed differently share one key", () => {
  const generate = sequentialKeys();
  const first = resolveGoalTransactionAttempt(
    [], payload({ amount: canonicalizeGoalAmount("10") }), generate,
  );

  const retry = resolveGoalTransactionAttempt(
    first.attempts, payload({ amount: canonicalizeGoalAmount("10.00") }), generate,
  );

  assert.equal(retry.attempt.clientRequestId, first.attempt.clientRequestId);
});

test("the request body carries the key, omits a null note and never sends effective_date", () => {
  const attempt = { clientRequestId: "key-1", payload: payload() };

  const input = toGoalTransactionCreateInput(attempt);

  assert.deepEqual(input, { client_request_id: "key-1", type: "contribution", amount: "10.00" });
  assert.equal("effective_date" in input, false);
  assert.equal("goalId" in input, false);
});

test("a note is sent exactly as prepared", () => {
  const attempt = {
    clientRequestId: "key-1",
    payload: payload({ description: "Payday" }),
  };

  assert.equal(toGoalTransactionCreateInput(attempt).description, "Payday");
});

test("history shows effective_date as the exact date-only string", () => {
  // created_at is late evening UTC: any Date-based conversion to a local
  // timezone could move the day; the date-only string must come back as is.
  const displayed = getGoalTransactionDisplayDate({
    effective_date: "2026-10-05",
    created_at: "2026-10-05T23:30:00Z",
  });

  assert.equal(displayed, "2026-10-05");
});

test("legacy history without effective_date falls back to created_at", () => {
  const displayed = getGoalTransactionDisplayDate({
    effective_date: null,
    created_at: "2026-01-01T10:00:00Z",
  });

  assert.equal(displayed, "2026-01-01T10:00:00Z");
});
