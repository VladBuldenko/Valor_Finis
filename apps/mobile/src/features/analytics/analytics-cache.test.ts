// Which Analytics query families each mutation refreshes (VF-MVP-CORE-006), with a real TanStack QueryClient
// and the app's real key shapes. Separates the operations that SHOULD change Analytics from the ones that
// must not (so a Transfer or a Goal reservation never causes pointless refetches), and proves another
// user's cache is never touched.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { QueryClient } from "@tanstack/react-query";

import { invalidateExpenseQueries } from "../expenses/expense-cache.ts";
import { invalidateGoalTransactionQueries } from "../goals/goal-cache.ts";
import { invalidateIncomeQueries } from "../income/income-cache.ts";
import { invalidateConfirmedReceiptQueries } from "../receipts/receipt-confirm-recovery.ts";
import { invalidateTransferQueries } from "../transfers/transfer-cache.ts";

const USER = "user-1";

const ANALYTICS = {
  monthlySummary: ["analytics", "monthly-summary", USER, 2026, 11],
  categorySummary: ["analytics", "category-summary", USER, 2026, 11],
  spendingTrend: ["analytics", "spending-trend", USER, "month", 6],
  categoryTrend: ["analytics", "category-trend", USER, "month", 6, null],
  spendingForecast: ["analytics", "spending-forecast", USER],
  financialOverview: ["analytics", "financial-overview", USER, 2026, 11],
  incomeExpenseTrend: ["analytics", "income-expense-trend", USER, 6],
  budgetStatus: ["analytics", "budget-status", USER],
  goalProgress: ["analytics", "goal-progress", USER],
};

const OTHER = {
  otherUsersOverview: ["analytics", "financial-overview", "user-2", 2026, 11],
  otherUsersBudgetStatus: ["analytics", "budget-status", "user-2"],
};

function seeded() {
  const client = new QueryClient();

  for (const key of [...Object.values(ANALYTICS), ...Object.values(OTHER)]) {
    client.setQueryData(key, {});
  }

  return client;
}

function refreshedAnalytics(client: QueryClient): string[] {
  return Object.entries({ ...ANALYTICS, ...OTHER })
    .filter(([, key]) => client.getQueryState(key)?.isInvalidated)
    .map(([name]) => name)
    .sort();
}

const SPENDING_VIEWS = [
  "budgetStatus",
  "categorySummary",
  "categoryTrend",
  "financialOverview",
  "incomeExpenseTrend",
  "monthlySummary",
  "spendingForecast",
  "spendingTrend",
];

describe("operations that change Analytics", () => {
  it("an Expense create/edit/delete refreshes every spending view, Budget status and the Overview, never Goal progress", async () => {
    const client = seeded();

    await invalidateExpenseQueries(client, USER, false);

    assert.deepEqual(refreshedAnalytics(client), SPENDING_VIEWS);
  });

  it("a confirmed Receipt creates an Expense, so it refreshes exactly the same views", async () => {
    const client = seeded();

    await invalidateConfirmedReceiptQueries(client, USER, true);

    assert.deepEqual(refreshedAnalytics(client), SPENDING_VIEWS);
  });

  it("an Income create/edit/delete refreshes only the Overview and the income/expense trend", async () => {
    const client = seeded();

    await invalidateIncomeQueries(client, USER, false);

    assert.deepEqual(refreshedAnalytics(client), ["financialOverview", "incomeExpenseTrend"]);
  });

  it("a Goal contribution, reservation or withdrawal refreshes only Goal progress", async () => {
    for (const isLinked of [false, true]) {
      const client = seeded();

      await invalidateGoalTransactionQueries(client, USER, "goal-1", isLinked);

      assert.deepEqual(refreshedAnalytics(client), ["goalProgress"], `linked=${isLinked}`);
    }
  });
});

describe("operations that must NOT change Analytics", () => {
  it("a Transfer (planned, posted, manually posted or deleted) refreshes no Analytics view at all", async () => {
    for (const touchedLedger of [false, true]) {
      const client = seeded();

      await invalidateTransferQueries(client, USER, touchedLedger);

      assert.deepEqual(refreshedAnalytics(client), [], `ledger=${touchedLedger}`);
    }
  });
});

describe("session isolation", () => {
  it("never refreshes another user's Analytics, whatever the mutation", async () => {
    const client = seeded();

    await Promise.all([
      invalidateExpenseQueries(client, USER, true),
      invalidateIncomeQueries(client, USER, true),
      invalidateGoalTransactionQueries(client, USER, "goal-1", true),
      invalidateTransferQueries(client, USER, true),
      invalidateConfirmedReceiptQueries(client, USER, true),
    ]);

    for (const name of Object.keys(OTHER)) {
      assert.equal(client.getQueryState(OTHER[name as keyof typeof OTHER])?.isInvalidated, false, name);
    }
  });

  it("a signed-out session (no user id) matches no user's keys", async () => {
    const client = seeded();

    await invalidateExpenseQueries(client, undefined, true);

    assert.deepEqual(refreshedAnalytics(client), []);
  });
});
