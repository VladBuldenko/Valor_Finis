// Focused tests for goal-cache.ts (VF-020C3) using a real TanStack
// QueryClient: exactly which query families a successful Goal transaction
// invalidates.
//   node --experimental-strip-types --test src/features/goals/goal-cache.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";

import { QueryClient } from "@tanstack/react-query";

import { invalidateGoalTransactionQueries } from "./goal-cache.ts";

const USER = "user-1";
const GOAL = "goal-1";
const OTHER_GOAL = "goal-2";

const KEYS = {
  goals: ["goals", USER],
  goalTransactions: ["goals", "transactions", USER, GOAL],
  otherGoalTransactions: ["goals", "transactions", USER, OTHER_GOAL],
  goalProgress: ["analytics", "goal-progress", USER],
  accounts: ["accounts", USER],
  accountTransactions: ["accounts", "transactions", USER, "acc-1"],
  income: ["income", USER],
  expenses: ["expenses", USER],
  transfers: ["account-transfers", USER],
  budgets: ["budgets", USER],
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

test("a tracked success invalidates exactly Goals, this Goal's history and Goal Progress", async () => {
  const client = seededClient();

  await invalidateGoalTransactionQueries(client, USER, GOAL, false);

  assert.deepEqual(invalidated(client), ["goalProgress", "goalTransactions", "goals"]);
});

test("a linked success additionally invalidates Accounts, and only Accounts", async () => {
  const client = seededClient();

  await invalidateGoalTransactionQueries(client, USER, GOAL, true);

  assert.deepEqual(invalidated(client), ["accounts", "goalProgress", "goalTransactions", "goals"]);
});

test("Account transaction history, income, expenses, transfers, budgets and overview are never invalidated", async () => {
  const client = seededClient();

  await invalidateGoalTransactionQueries(client, USER, GOAL, true);

  const touched = invalidated(client);
  for (const untouched of [
    "accountTransactions", "income", "expenses", "transfers", "budgets", "overview",
    "budgetStatus", "otherGoalTransactions",
  ]) {
    assert.equal(touched.includes(untouched), false, untouched);
  }
});
