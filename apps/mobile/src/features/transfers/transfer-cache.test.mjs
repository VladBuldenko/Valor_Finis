// Focused tests for transfer-cache.ts (VF-MVP-CORE-003) using a real TanStack QueryClient:
// exactly which query families a transfer mutation invalidates.
//   node --experimental-strip-types --test src/features/transfers/transfer-cache.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";

import { QueryClient } from "@tanstack/react-query";

import { invalidateTransferQueries } from "./transfer-cache.ts";

const USER = "user-1";

const KEYS = {
  transfers: ["account-transfers", USER],
  accounts: ["accounts", USER],
  sourceHistory: ["accounts", "transactions", USER, "acc-src"],
  destinationHistory: ["accounts", "transactions", USER, "acc-dst"],
  otherUserAccounts: ["accounts", "user-2"],
  income: ["income", USER],
  expenses: ["expenses", USER],
  budgets: ["budgets", USER],
  goals: ["goals", USER],
  goalProgress: ["analytics", "goal-progress", USER],
  overview: ["analytics", "financial-overview", USER, 2026, 10],
  budgetStatus: ["analytics", "budget-status", USER],
};

function seededClient() {
  const client = new QueryClient();

  for (const key of Object.values(KEYS)) {
    client.setQueryData(key, []);
  }

  return client;
}

function invalidated(client) {
  return Object.entries(KEYS)
    .filter(([, key]) => client.getQueryState(key).isInvalidated)
    .map(([name]) => name)
    .sort();
}

test("a planned create (no ledger rows) refreshes only the transfer list", async () => {
  const client = seededClient();

  await invalidateTransferQueries(client, USER, false);

  assert.deepEqual(invalidated(client), ["transfers"]);
});

test("a posted create / manual post / delete also refreshes the Account list and BOTH account histories", async () => {
  const client = seededClient();

  await invalidateTransferQueries(client, USER, true);

  assert.deepEqual(invalidated(client), ["accounts", "destinationHistory", "sourceHistory", "transfers"]);
});

test("transfers never refresh Income, Expenses, Budgets, Goals or any analytics (a transfer moves no spending)", async () => {
  const client = seededClient();

  await invalidateTransferQueries(client, USER, true);

  const touched = invalidated(client);

  for (const unrelated of ["income", "expenses", "budgets", "goals", "goalProgress", "overview", "budgetStatus"]) {
    assert.equal(touched.includes(unrelated), false, unrelated);
  }
});

test("another user's cache is never touched", async () => {
  const client = seededClient();

  await invalidateTransferQueries(client, USER, true);

  assert.equal(client.getQueryState(KEYS.otherUserAccounts).isInvalidated, false);
});

test("resolves only after the invalidations were issued, so callers can await a fresh list before navigating", async () => {
  const client = seededClient();
  const result = invalidateTransferQueries(client, USER, true);

  assert.ok(result instanceof Promise);
  await result;
  assert.equal(client.getQueryState(KEYS.transfers).isInvalidated, true);
});
