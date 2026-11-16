// VF-GOALS-PLANNING-002B: wiring of the savings overview into the Goals list.
// Source checks in the project's usual style (React Native components cannot be
// mounted in the Node runner) plus a real TanStack QueryClient for cache
// invalidation: the request contract, the query key and refresh, where the
// section sits, loading/error/retry isolation, accessibility, and that no
// existing Goals workflow changed.
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
import { invalidateGoalHistoryQueries, invalidateGoalTransactionQueries } from "./goal-cache.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const code = (file: string) => readFileSync(join(HERE, file), "utf8").replace(/\/\/.*$/gm, "");

describe("request contract", () => {
  const service = code("goal.service.ts");
  const call = service.slice(service.indexOf("export async function getGoalSavingsOverview"));

  it("is a plain, abortable GET of /goals/savings-overview with no parameters", () => {
    assert.match(call, /"\/api\/v1\/goals\/savings-overview"/);
    assert.match(call, /\{\s*signal,?\s*\}/);
    assert.doesNotMatch(call, /method:|body:/);
  });

  it("does no number handling", () => {
    assert.doesNotMatch(call, /parseFloat|Number\(|parseInt|\.toFixed|Math\./);
  });

  it("the response type mirrors the backend contract", () => {
    const types = code("goal.types.ts");

    for (const field of [
      "horizon_months", "is_total_complete", "planned_goals", "continues_after_window", "required_per_installment",
      "installment_count", "total_required", "planned_goal_count", "contributions", "historical_difference",
      "difference_direction", "exclusions", "no_target_date", "target_date_passed", "other_currency", "other_currencies",
      "already_funded", "history", "months_used", "average_monthly_net_flow", "limitations", "installment_date",
    ]) {
      assert.match(types, new RegExp(`\\b${field}\\b`), field);
    }

    for (const status of ["comparable", "insufficient_data", "no_planned_goals"]) {
      assert.match(types, new RegExp(`"${status}"`), status);
    }

    for (const limitation of ["other_currency_goals_excluded", "goals_without_target_date", "goals_with_passed_target_date", "future_obligations_not_modelled"]) {
      assert.match(types, new RegExp(`"${limitation}"`), limitation);
    }
  });
});

describe("the Goals screen", () => {
  const screen = code("goals-screen.tsx");

  it("reads the overview under the Goal cache prefix every Goal change invalidates", () => {
    assert.match(screen, /queryKey: \["goals", session\?\.user\.id, "savings-overview"\]/);
    assert.match(screen, /queryFn: \(\{ signal \}\) => getGoalSavingsOverview\(signal\)/);
    assert.match(screen, /enabled: Boolean\(session\),\s*\}\);\s*const refresh/);
  });

  it("pull-to-refresh re-reads the overview with the list and the progress", () => {
    assert.match(screen, /refetcherOf\(goalsQuery\),\s*refetcherOf\(goalProgressQuery\),\s*refetcherOf\(savingsOverviewQuery\),/);
  });

  it("shows the section above the list, in the current view only, and creates no new screen", () => {
    const at = screen.indexOf("<GoalSavingsOverviewSection query={savingsOverviewQuery} />");

    assert.ok(at > screen.indexOf('href="/goals/priorities"'));
    assert.ok(at < screen.indexOf("<QueryBoundary\n          query={goalsQuery}") || at < screen.indexOf("query={goalsQuery}"));
    assert.match(screen, /\{listView === "current" \? <GoalSavingsOverviewSection query=\{savingsOverviewQuery\} \/> : null\}/);
  });

  it("the Goal list does not depend on the overview, so a failed overview never hides the Goals", () => {
    const list = screen.slice(screen.indexOf("<QueryBoundary\n          query={goalsQuery}"));
    const listBoundary = list.slice(0, list.indexOf("{(goals) => ("));

    assert.doesNotMatch(listBoundary, /savingsOverview/);
    assert.match(screen, /<QueryBoundary\s+query=\{goalsQuery\}\s+what="goals"/);
    assert.doesNotMatch(screen.replace(/const savingsOverviewQuery[\s\S]*?\}\);\s*const refresh/, ""), /savingsOverviewQuery\.(isError|isLoading|data)/);
  });

  it("the existing workflows are unchanged: the same delete guard and the same cache refreshes", () => {
    assert.equal((screen.match(/deleteGoalMutation\.mutate\(/g) ?? []).length, 1);
    assert.match(screen, /if \(deleteGoalMutation\.isPending\) \{\s*return;\s*\}/);
    assert.match(screen, /queryKey: \["goals", session\?\.user\.id\],/);
    assert.match(screen, /queryKey: \["analytics", "goal-progress", session\?\.user\.id\],/);
    assert.match(screen, /<QueryBoundary\s+query=\{goalsQuery\}/);
    assert.match(screen, /InlineError/);
  });
});

describe("the section", () => {
  const section = code("goal-savings-overview-section.tsx");

  it("has its own loading, error and Retry boundary", () => {
    assert.match(section, /<QueryBoundary query=\{query\} what="savings plans">/);
  });

  it("renders nothing when there is nothing to plan or flag", () => {
    assert.match(section, /if \(query\.data !== undefined && !hasOverviewContent\(query\.data\)\) \{\s*return null;\s*\}/);
  });

  it("shows only what the view helpers derive from the backend response, and always the assumption, limits and disclaimer", () => {
    for (const helper of ["overviewHeadline", "overviewSummaryLines", "overviewComparisonLines", "overviewNotices", "overviewContributionRows", "overviewMonthRows", "overviewContinuesNote"]) {
      assert.match(section, new RegExp(`${helper}\\(overview\\)`), helper);
    }

    assert.match(section, /\{OVERVIEW_ASSUMPTION\}/);
    assert.match(section, /\{OVERVIEW_NOT_MODELLED\}/);
    assert.match(section, /\{OVERVIEW_DISCLAIMER\}/);
    assert.match(section, /\{OVERVIEW_TITLE\}/);
    assert.doesNotMatch(section, /parseFloat|Number\(|parseInt|\.toFixed|Math\.|\bBigInt\b|\.reduce\(/);
  });

  it("is accessible: headers, a spoken label for the headline and for each Goal and month row", () => {
    assert.ok((section.match(/accessibilityRole="header"/g) ?? []).length >= 3);
    assert.match(section, /accessibilityLabel=\{`\$\{headline\.label\}: \$\{headline\.amount\}`\}/);
    assert.equal((section.match(/accessibilityLabel=\{`\$\{row\.label\}: \$\{row\.value\}`\}/g) ?? []).length, 2);
  });

  it("is visually consistent with the Goal cards: the same card, name and amount styles", () => {
    assert.match(section, /<View style=\{styles\.card\}>/);
    assert.match(section, /styles\.name/);
    assert.match(section, /styles\.amount/);
    assert.doesNotMatch(section, /StyleSheet\.create/);
  });

  it("creates nothing: no mutation, no write method", () => {
    assert.doesNotMatch(section, /useMutation|\.mutate\(|createGoalTransaction|updateGoal|PATCH|DELETE|POST/);
  });

  it("sets an explicit line height on every paragraph, so iOS measures and draws the same lines", () => {
    // Without one, the iOS Simulator (iOS 26, Expo Go) clipped the last line of
    // long, data-driven sentences at the card's right edge ("...Update its d").
    const styleSource = code("goals.styles.ts");

    for (const name of ["overviewText", "overviewHelperText"]) {
      assert.match(styleSource, new RegExp(`${name}: \\{[^}]*lineHeight: \\d+`), name);
    }

    assert.doesNotMatch(section, /styles\.(secondaryText|helperText|label)\b/);
    assert.match(section, /styles\.overviewText/);
    assert.match(section, /styles\.overviewHelperText/);
    assert.match(section, /styles\.overviewLabel/);
    assert.doesNotMatch(section, /allowFontScaling=\{false\}/);
  });
});

describe("cache invalidation (real QueryClient, the app's key shapes)", () => {
  const USER = "user-1";
  const KEYS = {
    overview: ["goals", USER, "savings-overview"],
    history: ["goals", USER, "history-comparison", "goal-1"],
    plan: ["goals", USER, "plan", "goal-1", "base"],
    goalList: ["goals", USER],
    goalTransactions: ["goals", "transactions", USER, "goal-1"],
    otherUsersOverview: ["goals", "user-2", "savings-overview"],
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

  it("an Income or Expense change (or a confirmed Receipt) re-reads the overview and the Goal comparisons, and nothing else of the Goal family", async () => {
    for (const run of [
      (client: QueryClient) => invalidateIncomeQueries(client, USER, false),
      (client: QueryClient) => invalidateExpenseQueries(client, USER, true),
      (client: QueryClient) => invalidateConfirmedReceiptQueries(client, USER, false),
      (client: QueryClient) => invalidateGoalHistoryQueries(client, USER),
    ]) {
      const client = seeded();

      await run(client);

      assert.deepEqual(invalidated(client), ["history", "overview"]);
    }
  });

  it("a Goal contribution, reservation or withdrawal re-reads the overview through the Goal prefix", async () => {
    for (const isLinked of [false, true]) {
      const client = seeded();

      await invalidateGoalTransactionQueries(client, USER, "goal-1", isLinked);

      assert.ok(invalidated(client).includes("overview"), `linked=${isLinked}`);
    }
  });

  it("creating, editing, deleting or reordering Goals invalidates the Goal prefix, which covers the overview", () => {
    for (const file of ["goal-create-screen.tsx", "goal-edit-screen.tsx", "goal-priorities-screen.tsx", "goals-screen.tsx"]) {
      assert.match(code(file), /queryKey: \["goals", (session\?\.user\.id|userId)\]/, file);
    }

    const client = seeded();

    void client.invalidateQueries({ queryKey: ["goals", USER] });

    assert.ok(invalidated(client).includes("overview"));
    assert.ok(!invalidated(client).includes("otherUsersOverview"));
  });

  it("a Transfer changes neither income nor expenses, so it does not refresh the overview", async () => {
    for (const touchedLedger of [false, true]) {
      const client = seeded();

      await invalidateTransferQueries(client, USER, touchedLedger);

      assert.ok(!invalidated(client).includes("overview"), `ledger=${touchedLedger}`);
    }
  });

  it("never touches another user's cache, or a signed-out session's", async () => {
    const client = seeded();

    await Promise.all([invalidateIncomeQueries(client, USER, true), invalidateExpenseQueries(client, USER, true)]);

    assert.equal(client.getQueryState(KEYS.otherUsersOverview)?.isInvalidated, false);

    const signedOut = seeded();

    await invalidateGoalHistoryQueries(signedOut, undefined);

    assert.deepEqual(invalidated(signedOut), []);
  });
});
