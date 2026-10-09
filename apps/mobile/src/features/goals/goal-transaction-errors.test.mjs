// Focused tests for goal-transaction-errors.ts (VF-020C3).
//   node --experimental-strip-types --test src/features/goals/goal-transaction-errors.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ACCOUNT_ARCHIVED_DETAIL,
  ACCOUNT_NOT_FOUND_DETAIL,
  CAPACITY_DETAIL,
  GOAL_ARCHIVED_DETAIL,
  GOAL_NOT_FOUND_DETAIL,
  IDEMPOTENCY_CONFLICT_DETAIL,
  IDEMPOTENCY_CONFLICT_MESSAGE,
  mapGoalTransactionFailure,
  TRACKED_SHORTFALL_DETAIL,
  TRACKED_SHORTFALL_MESSAGE,
} from "./goal-transaction-errors.ts";

const FALLBACK = "Unable to create transaction.";
const trackedWithdrawal = { type: "withdrawal", isLinked: false };
const linkedWithdrawal = { type: "withdrawal", isLinked: true };
const linkedContribution = { type: "contribution", isLinked: true };

function handle(status, detail, context) {
  return mapGoalTransactionFailure({ status, detail }, context, FALLBACK);
}

test("tracked withdrawal shortfall gets the tracked-amount copy", () => {
  const result = handle(409, TRACKED_SHORTFALL_DETAIL, trackedWithdrawal);

  assert.equal(result.message, TRACKED_SHORTFALL_MESSAGE);
  assert.equal(result.message, "Withdrawal exceeds the tracked amount of this goal.");
});

test("the tracked wording is not applied to a linked request", () => {
  const result = handle(409, TRACKED_SHORTFALL_DETAIL, linkedWithdrawal);

  assert.equal(result.message, TRACKED_SHORTFALL_DETAIL);
});

test("linked partition shortfall passes the backend detail through", () => {
  const detail = "Withdrawal exceeds the goal amount reserved against this account.";

  assert.equal(handle(409, detail, linkedWithdrawal).message, detail);
});

test("capacity 409 shows the capacity copy, refreshes Accounts and keeps the attempt", () => {
  const result = handle(409, CAPACITY_DETAIL, linkedContribution);

  assert.equal(result.message, "Reservation exceeds the Account's reservable capacity.");
  assert.equal(result.refreshAccounts, true);
  assert.equal(result.discardAttempt, false);
  assert.equal(result.clearSelectedAccount, false);
});

test("Account 404 refreshes Accounts and clears the selected Account", () => {
  const result = handle(404, ACCOUNT_NOT_FOUND_DETAIL, linkedContribution);

  assert.equal(result.refreshAccounts, true);
  assert.equal(result.clearSelectedAccount, true);
  assert.equal(result.message, ACCOUNT_NOT_FOUND_DETAIL);
});

test("archived Account 409 shows the backend detail, refreshes Accounts and clears the selection", () => {
  const result = handle(409, ACCOUNT_ARCHIVED_DETAIL, linkedContribution);

  assert.equal(result.message, ACCOUNT_ARCHIVED_DETAIL);
  assert.equal(result.refreshAccounts, true);
  assert.equal(result.clearSelectedAccount, true);
});

test("Goal 404 and archived Goal 409 refresh Goals", () => {
  assert.equal(handle(404, GOAL_NOT_FOUND_DETAIL, linkedContribution).refreshGoals, true);
  assert.equal(handle(409, GOAL_ARCHIVED_DETAIL, linkedContribution).refreshGoals, true);
});

test("idempotency conflict shows the reopen copy and discards the stale attempt", () => {
  const result = handle(409, IDEMPOTENCY_CONFLICT_DETAIL, linkedContribution);

  assert.equal(result.message, IDEMPOTENCY_CONFLICT_MESSAGE);
  assert.equal(result.discardAttempt, true);
});

test("a status alone never decides the meaning: an unknown 409/404 keeps its own detail", () => {
  const unknown409 = handle(409, "Something else.", linkedContribution);
  const wrongStatus = handle(404, CAPACITY_DETAIL, linkedContribution);

  assert.equal(unknown409.message, "Something else.");
  assert.equal(unknown409.refreshAccounts, false);
  assert.equal(wrongStatus.refreshAccounts, false);
});

test("422 domain errors pass the backend detail through", () => {
  assert.equal(
    handle(422, "Goal and Account currencies must match.", linkedContribution).message,
    "Goal and Account currencies must match.",
  );
});

test("no detail falls back to the caller's message, never raw API text", () => {
  const result = handle(500, null, trackedWithdrawal);

  assert.equal(result.message, FALLBACK);
  assert.equal(result.message.includes("API request failed"), false);
});
