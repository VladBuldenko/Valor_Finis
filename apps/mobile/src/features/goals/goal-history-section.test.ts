// VF-GOALS-PLANNING-002A: wiring of the history comparison into the app. Source
// checks in the project's usual style (React Native components cannot be
// mounted in the Node runner) plus a real TanStack QueryClient for cache
// invalidation: the request contract, the query key and when it runs, where the
// section sits, loading/error/retry, refresh, accessibility, and that no
// existing workflow changed.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import { QueryClient } from "@tanstack/react-query";

import { invalidateExpenseQueries } from "../expenses/expense-cache.ts";
import { invalidateIncomeQueries } from "../income/income-cache.ts";
import { invalidateConfirmedReceiptQueries } from "../receipts/receipt-confirm-recovery.ts";
import { invalidateTransferQueries } from "../transfers/transfer-cache.ts";
import { invalidateGoalTransactionQueries } from "./goal-cache.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const code = (file: string) => readFileSync(join(HERE, file), "utf8").replace(/\/\/.*$/gm, "");

describe("request contract", () => {
  const service = code("goal.service.ts");
  const call = service.slice(service.indexOf("export async function getGoalHistoryComparison"));

  it("is a plain, abortable GET of /goals/{id}/plan/history-comparison", () => {
    assert.match(call, /`\/api\/v1\/goals\/\$\{goalId\}\/plan\/history-comparison`/);
    assert.match(call, /\{ signal \}/);
    assert.doesNotMatch(call, /method:|body:/);
  });

  it("does no number handling", () => {
    assert.doesNotMatch(call, /parseFloat|Number\(|parseInt|\.toFixed|Math\./);
  });

  it("the response type mirrors the backend contract", () => {
    const types = code("goal.types.ts");

    for (const field of [
      "analysis_period_start", "analysis_period_end", "months_used", "average_monthly_income", "average_monthly_expenses",
      "average_monthly_net_flow", "required_per_installment", "historical_difference", "difference_direction",
      "limitations", "has_activity", "included_in_average", "unresolved_income_count", "unresolved_expense_count",
      "goal_currency", "base_currency",
    ]) {
      assert.match(types, new RegExp(`\\b${field}\\b`), field);
    }

    for (const status of ["comparable", "insufficient_data", "currency_mismatch", "no_required_installment"]) {
      assert.match(types, new RegExp(`\\| "${status}"|"${status}"`), status);
    }
  });
});

describe("the query", () => {
  const plan = code("goal-plan-section.tsx");

  it("sits under the Goal cache prefix every Goal transaction invalidates", () => {
    assert.match(plan, /queryKey: \["goals", userId, "history-comparison", goalId\]/);
  });

  it("runs alongside the plan and stops once the plan is known not to be ready", () => {
    assert.match(plan, /const historyWanted = planStatus === undefined \|\| planStatus === "ready";/);
    assert.match(plan, /enabled: Boolean\(userId\) && historyWanted,/);
  });

  it("is shown only for a ready plan, inside the plan's own loading/error boundary", () => {
    assert.match(plan, /plan\.plan_status === "ready" \? <GoalHistorySection query=\{historyQuery\} \/> : null/);
    assert.ok(plan.indexOf("<GoalHistorySection") > plan.indexOf('<QueryBoundary query={planQuery} what="goal plan">'));
    assert.ok(plan.indexOf("<GoalHistorySection") > plan.indexOf("{PLAN_ASSUMPTION}"));
    assert.ok(plan.indexOf("<GoalHistorySection") < plan.indexOf("{WHAT_IF_TITLE}"));
  });
});

describe("the section", () => {
  const section = code("goal-history-section.tsx");

  it("has its own loading, error and Retry boundary, so a failure never blanks the plan", () => {
    assert.match(section, /<QueryBoundary query=\{query\} what="financial history comparison">/);
  });

  it("shows only what the view helpers derive from the backend response", () => {
    assert.match(section, /historySentences\(comparison\)/);
    assert.match(section, /historyMonthRows\(comparison\)/);
    assert.match(section, /\{HISTORY_NOT_MODELLED\}/);
    assert.match(section, /\{HISTORY_DISCLAIMER\}/);
    assert.match(section, /\{HISTORY_TITLE\}/);
    assert.doesNotMatch(section, /parseFloat|Number\(|parseInt|\.toFixed|Math\.|\bBigInt\b/);
  });

  it("is accessible: a header, and a spoken label for each month row", () => {
    assert.match(section, /accessibilityRole="header"/);
    assert.match(section, /accessibilityLabel=\{`\$\{row\.label\}: \$\{row\.value\}`\}/);
  });

  it("creates nothing: no mutation, no write method", () => {
    assert.doesNotMatch(section, /useMutation|\.mutate\(|createGoalTransaction|updateGoal|PATCH|DELETE|POST/);
  });
});

describe("the Goal detail screen", () => {
  const screen = code("goal-detail-screen.tsx");

  it("pull-to-refresh re-reads the comparison with the rest of the Goal, only while it is wanted", () => {
    assert.match(screen, /goalPlan\.historyWanted \? \[refetcherOf\(goalPlan\.historyQuery\)\] : \[\]/);
  });

  it("the existing workflows are unchanged", () => {
    assert.equal((screen.match(/createTransactionMutation\.mutate\(/g) ?? []).length, 1);
    assert.match(screen, /disabled=\{!canSubmitTransaction\}/);
    assert.match(screen, /invalidateGoalTransactionQueries\(\s*queryClient,\s*session\?\.user\.id,\s*id,/);
    assert.match(screen, /<GoalPlanSection model=\{goalPlan\} \/>/);
  });
});

describe("cache invalidation (real QueryClient, the app's key shapes)", () => {
  const USER = "user-1";
  const KEYS = {
    history: ["goals", USER, "history-comparison", "goal-1"],
    otherGoalsHistory: ["goals", USER, "history-comparison", "goal-2"],
    plan: ["goals", USER, "plan", "goal-1", "base"],
    goalList: ["goals", USER],
    otherUsersHistory: ["goals", "user-2", "history-comparison", "goal-1"],
  };

  function seeded() {
    const client = new QueryClient();

    for (const key of Object.values(KEYS)) {
      client.setQueryData(key, {});
    }

    return client;
  }

  const invalidated = (client: QueryClient) =>
    Object.entries(KEYS)
      .filter(([, key]) => client.getQueryState(key)?.isInvalidated)
      .map(([name]) => name)
      .sort();

  it("an Income or Expense change (or a confirmed Receipt) re-reads every Goal's comparison, and only that of the Goal family", async () => {
    for (const run of [
      (client: QueryClient) => invalidateIncomeQueries(client, USER, false),
      (client: QueryClient) => invalidateExpenseQueries(client, USER, true),
      (client: QueryClient) => invalidateConfirmedReceiptQueries(client, USER, false),
    ]) {
      const client = seeded();

      await run(client);

      assert.deepEqual(invalidated(client), ["history", "otherGoalsHistory"]);
    }
  });

  it("a Goal contribution, reservation or withdrawal re-reads it too, through the Goal prefix", async () => {
    const client = seeded();

    await invalidateGoalTransactionQueries(client, USER, "goal-1", false);

    assert.ok(invalidated(client).includes("history"));
    assert.ok(invalidated(client).includes("plan"));
  });

  it("a Transfer changes neither income nor expenses, so it does not refresh the comparison", async () => {
    for (const touchedLedger of [false, true]) {
      const client = seeded();

      await invalidateTransferQueries(client, USER, touchedLedger);

      assert.ok(!invalidated(client).includes("history"), `ledger=${touchedLedger}`);
    }
  });

  it("never touches another user's cache, or a signed-out session's", async () => {
    const client = seeded();

    await Promise.all([invalidateIncomeQueries(client, USER, true), invalidateExpenseQueries(client, USER, true)]);

    assert.equal(client.getQueryState(KEYS.otherUsersHistory)?.isInvalidated, false);

    const signedOut = seeded();

    await invalidateIncomeQueries(signedOut, undefined, true);

    assert.deepEqual(invalidated(signedOut), []);
  });
});
