// VF-MOB-REFRESH-RETRY: the per-screen checklist is checked against the code.
// The Markdown table in docs/mvp/mf3-screen-checklist.md must list every route
// file, and each claim must be visible in the screen's source. The React Native
// screens cannot be mounted by the Node runner, so this is the structural half;
// the behavior is tested in lib/screen-refresh, lib/foreground-refetch and
// lib/query-view.
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import { stripComments } from "./financial-rules/financial-rule-forbidden-copy.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const MOBILE = join(HERE, "../..");
const APP = join(MOBILE, "app");
const SRC = join(MOBILE, "src");
const DOC = join(MOBILE, "../../docs/mvp/mf3-screen-checklist.md");

type Row = {
  route: string; source: string; klass: string; refresh: string; error: string; optional: string; status: string;
};

function rows(): Row[] {
  return readFileSync(DOC, "utf8")
    .split("\n")
    .filter((line) => line.startsWith("| `"))
    .map((line) => {
      const cells = line.split("|").slice(1, -1).map((cell) => cell.trim());

      assert.equal(cells.length, 11, `11 columns expected: ${line.slice(0, 60)}`);

      return {
        route: cells[0].replaceAll("`", ""),
        source: cells[1].replaceAll("`", ""),
        klass: cells[2],
        error: cells[7],
        refresh: cells[8],
        optional: cells[9],
        status: cells[10],
      };
    });
}

function routeFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);

    if (entry.isDirectory()) return routeFiles(path);

    return entry.name.endsWith(".tsx") && entry.name !== "_layout.tsx" ? [relative(APP, path)] : [];
  });
}

const source = (path: string) => stripComments(readFileSync(join(SRC, path.replace(/^features\//, "features/")), "utf8"));
// JSX usage, not an import or a comment: a screen that merely imports the shared
// components does not offer Retry.
const RETRY = /<(QueryBoundary|LoadError|RetryAction|InlineError|RetryButton|SectionRetry)\b|onRetry=|accessibilityLabel=\{?["`]Retry|>\s*(Retry|Try again)\s*</;

describe("the checklist covers every route", () => {
  it("lists each route file exactly once and nothing else", () => {
    const listed = rows().map((row) => row.route).sort();

    assert.deepEqual(listed, routeFiles(APP).sort());
    assert.equal(new Set(listed).size, listed.length);
  });

  it("names the required screens", () => {
    const text = rows().map((row) => row.route).join(" ");

    for (const needle of ["accounts", "income", "expenses", "transfers", "goals", "budgets", "categories", "index.tsx", "analytics", "overview", "receipts", "rules/index", "inbox/index", "inbox/proposals", "inbox/alerts", "preview", "history"]) {
      assert.ok(text.includes(needle), needle);
    }
  });

  it("every row is done", () => {
    for (const row of rows()) assert.equal(row.status, "done", row.route);
  });
});

describe("every claim is visible in the screen", () => {
  const withScreens = rows().filter((row) => row.source.endsWith(".tsx"));

  it("every list and dashboard has pull-to-refresh", () => {
    for (const row of rows().filter((r) => /^(list|dashboard)/.test(r.klass))) {
      assert.match(row.refresh, /^yes/, row.route);
      assert.match(source(row.source), /RefreshControl/, row.route);
    }
  });

  it("'yes' means a RefreshControl wired to a handler", () => {
    for (const row of withScreens.filter((r) => r.refresh.startsWith("yes"))) {
      const code = source(row.source);

      assert.match(code, /<RefreshControl/, row.route);
      assert.match(code, /onRefresh=\{/, row.route);
    }
  });

  it("the screens that refresh several queries use the coordinated hook (one pull at a time)", () => {
    const coordinated = [
      "features/dashboard/dashboard-screen.tsx", "features/accounts/accounts-screen.tsx", "features/income/income-screen.tsx",
      "features/budgets/budgets-screen.tsx", "features/categories/categories-screen.tsx", "features/goals/goals-screen.tsx",
      "features/transfers/transfers-screen.tsx", "features/expenses/expenses-screen.tsx", "features/analytics/analytics-screen.tsx",
      "features/analytics/financial-overview-screen.tsx", "features/accounts/account-detail-screen.tsx",
      "features/goals/goal-detail-screen.tsx", "features/financial-rules/inbox-screen.tsx",
    ];

    for (const path of coordinated) {
      assert.match(source(path), /useScreenRefresh\(/, path);
      assert.match(source(path), /refreshing=\{refresh\.refreshing\}/, path);
    }
  });

  it("every screen that loads data offers Retry on its PRIMARY load failure", () => {
    // Screens from MF-3 use the shared primary components; the Smart Rules screens
    // (F3-F6) and the overview keep their own Retry buttons.
    const PRIMARY = /<(QueryBoundary|LoadError|RetryAction)\b|<RetryButton\b/;

    for (const row of withScreens.filter((r) => !/^n\/a/.test(r.error))) {
      const code = source(row.source);

      assert.match(code, RETRY, row.route);

      if (!row.source.startsWith("features/financial-rules/")) {
        assert.match(code, PRIMARY, `${row.route}: the primary load failure needs Retry`);
      }
    }
  });

  it("no screen still shows a bare 'Unable to load' with no way to retry", () => {
    for (const row of withScreens) {
      const code = source(row.source);

      if (/Unable to load/.test(code)) {
        assert.match(code, RETRY, `${row.route} has a bare load-failure message`);
      }
    }
  });

  it("a failure that replaces a whole screen does so only while nothing is loaded", () => {
    for (const path of [
      "features/accounts/account-edit-screen.tsx", "features/budgets/budget-edit-screen.tsx", "features/categories/category-edit-screen.tsx",
      "features/goals/goal-edit-screen.tsx", "features/income/income-edit-screen.tsx", "features/expenses/expense-detail-screen.tsx",
      "features/receipts/receipt-review-screen.tsx",
    ]) {
      const code = source(path);

      assert.doesNotMatch(code, /if \(error\) \{/, `${path}: an error must not replace a loaded form`);
      assert.match(code, /if \(error && \w+ === undefined\)/, path);
    }

    assert.match(source("features/goals/goal-priorities-screen.tsx"), /goalsQuery\.data === undefined \? goalsQuery\.error : null/);
    assert.match(source("features/accounts/account-detail-screen.tsx"), /accountsQuery\.data === undefined \? accountsQuery\.error : null/);
  });

  it("the shared components carry the accessibility metadata", () => {
    const states = source("components/query-states.tsx");

    assert.match(states, /\{\.\.\.retryA11y\(what, retrying\)\}/);
    assert.match(states, /\{\.\.\.loadingA11y\(what\)\}/);
    assert.ok((states.match(/accessibilityRole="alert"/g) ?? []).length >= 2);
    assert.match(states, /accessibilityLiveRegion="polite"/);
    assert.match(states, /disabled=\{retrying\}/);
  });

  it("Retry only ever calls a refetch, never a write", () => {
    const states = source("components/query-states.tsx");

    assert.doesNotMatch(states, /mutate|mutation|apiRequest|\bfetch\(|POST|PATCH|DELETE/);
    assert.equal((states.match(/onRetry=\{\(\) => void query\.refetch\(\)\}/g) ?? []).length, 2);
  });
});

describe("paged lists keep their paging when refreshed", () => {
  it("history and alerts refresh the infinite query itself, and not while a next page loads", () => {
    for (const path of ["features/financial-rules/rule-history-screen.tsx", "features/financial-rules/alerts-screen.tsx"]) {
      const code = source(path);

      assert.match(code, /refreshing=\{feed\.isRefetching && !feed\.isFetchingNextPage\}/, path);
      assert.match(code, /onRefresh=\{\(\) => void feed\.refetch\(\)\}/, path);
      assert.doesNotMatch(code, /resetQueries|removeQueries/, path);
    }
  });
});

describe("the Inbox indicator and the evaluation path are untouched", () => {
  it("Dashboard reads only the derived indicator and refreshes the Inbox sources with GETs", () => {
    const code = source("features/dashboard/dashboard-screen.tsx");

    assert.match(code, /inboxIndicatorPresentation\(inbox\.indicator\)/);
    assert.match(code, /refetcherOf\(inbox\.proposals\)/);
    assert.match(code, /refetcherOf\(inbox\.alerts\)/);
    assert.doesNotMatch(code, /deriveInboxIndicator|request\("(inbox_open|foreground)"\)/);
  });

  it("the Inbox still asks for exactly one evaluation per open and per pull", () => {
    const code = source("features/financial-rules/inbox-screen.tsx");

    assert.equal((code.match(/request\("inbox_open"\)/g) ?? []).length, 2, "on open and on pull, both through the same debounced trigger");
    assert.doesNotMatch(code, /evaluateRules|financialRulesService/);
  });

  it("the focus bridge is installed once, in the root layout", () => {
    const layout = readFileSync(join(APP, "_layout.tsx"), "utf8");

    assert.equal((layout.match(/installAppFocusRuntime\(\)/g) ?? []).length, 1);
    assert.match(layout, /useEffect\(\(\) => installAppFocusRuntime\(\), \[\]\)/);
  });
});
