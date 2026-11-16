// VF-GOALS-PLANNING-002C1: wiring of Upcoming bills into the app. Source checks in the
// project's usual style (React Native components cannot be mounted in the Node
// runner) plus a real TanStack QueryClient for cache behavior: the request
// contract, the query keys, where the section sits, loading/error/Retry, refresh,
// duplicate-submit protection, accessibility, and that no existing workflow changed.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import { QueryClient } from "@tanstack/react-query";

import { invalidateExpenseQueries } from "../expenses/expense-cache.ts";
import { invalidateIncomeQueries } from "../income/income-cache.ts";
import { invalidateGoalTransactionQueries } from "../goals/goal-cache.ts";
import { invalidateFutureObligationQueries } from "./future-obligation-cache.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..", "..", "..");
const strip = (text: string) => text.replace(/\/\/.*$/gm, "");
const code = (file: string) => strip(readFileSync(join(HERE, file), "utf8"));
const goalsCode = (file: string) => strip(readFileSync(join(HERE, "..", "goals", file), "utf8"));
const appFile = (path: string) => readFileSync(join(ROOT, "app", "(app)", path), "utf8");

describe("request contract", () => {
  const service = code("future-obligation.service.ts");

  it("reads the list and the projection with plain, abortable GETs", () => {
    assert.match(service, /apiRequest<FutureObligation\[\]>\("\/api\/v1\/future-obligations", \{\s*signal,?\s*\}\)/);
    assert.match(service, /apiRequest<UpcomingObligations>\("\/api\/v1\/future-obligations\/upcoming", \{\s*signal,?\s*\}\)/);
  });

  it("creates with POST and updates (including archive and restore) with PATCH of only the sent fields", () => {
    assert.match(service, /"\/api\/v1\/future-obligations", \{\s*method: "POST",\s*body: JSON\.stringify\(input\)/);
    assert.match(service, /`\/api\/v1\/future-obligations\/\$\{obligationId\}`/);
    assert.match(service, /method: "PATCH"/);
    assert.doesNotMatch(service, /method: "DELETE"/);
  });

  it("does no number handling", () => {
    assert.doesNotMatch(service, /parseFloat|Number\(|parseInt|\.toFixed|Math\./);
  });

  it("the response types mirror the backend contract", () => {
    const types = code("future-obligation.types.ts");

    for (const field of [
      "first_due_date", "final_due_date", "next_due_date", "client_request_id", "base_currency_total", "totals_by_currency",
      "occurrence_count", "occurrences", "excluded_currencies", "is_base_total_complete", "base_currency_window_total",
      "horizon_months", "window_start", "window_end", "obligation_id", "due_date", "period_start", "period_end",
    ]) {
      assert.match(types, new RegExp(`\\b${field}\\b`), field);
    }

    assert.match(types, /"one_time" \| "monthly"/);
    assert.match(types, /"active" \| "archived"/);
  });
});

describe("the screens", () => {
  const list = code("future-obligations-screen.tsx");
  const create = code("future-obligation-create-screen.tsx");
  const edit = code("future-obligation-edit-screen.tsx");
  const card = code("upcoming-bills-card.tsx");

  it("use one cache family, with the user id in every key", () => {
    for (const source of [list, create, edit, card]) {
      for (const match of source.match(/queryKey: \[[^\]]*\]/g) ?? []) {
        assert.match(match, /"future-obligations", session\?\.user\.id, "(upcoming|list)"/, match);
      }
    }

    assert.match(list, /queryKey: \["future-obligations", session\?\.user\.id, "upcoming"\]/);
    assert.match(list, /queryKey: \["future-obligations", session\?\.user\.id, "list"\]/);
  });

  it("the list has loading, error and Retry boundaries for the projection and for the bills, and refreshes both", () => {
    assert.match(list, /<QueryBoundary query=\{upcomingQuery\} what="upcoming bills">/);
    assert.match(list, /query=\{listQuery\}\s+what="bills"/);
    assert.match(list, /useScreenRefresh\(\(\) => \[refetcherOf\(upcomingQuery\), refetcherOf\(listQuery\)\]\)/);
    assert.match(list, /<RefreshControl refreshing=\{refresh\.refreshing\} onRefresh=\{refresh\.onRefresh\} \/>/);
  });

  it("the list has an empty state and separate current and archived views", () => {
    assert.match(list, /isEmpty=\{\(bills\) => !bills\.some\(matches\)\}/);
    assert.match(list, /empty=\{view === "archived" \? BILLS_ARCHIVED_EMPTY : BILLS_EMPTY\}/);
    assert.match(list, /bill\.status === "archived" : bill\.status === "active"|view === "archived" \? bill\.status === "archived" : bill\.status === "active"/);
  });

  it("offers both kinds of bill, edit, archive (with a confirmation) and restore", () => {
    assert.match(list, /schedule: "monthly"/);
    assert.match(list, /schedule: "one_time"/);
    assert.match(list, /pathname: "\/goals\/bills\/\[id\]\/edit"/);
    assert.match(list, /archiveConfirmation\(bill\.name\)/);
    assert.match(list, /mutate\(\{ id: bill\.id, status: "archived" \}\)/);
    assert.match(list, /mutate\(\{ id: bill\.id, status: "active" \}\)/);
  });

  it("archive and restore guard against a double tap and refresh through the bills cache only", () => {
    assert.match(list, /if \(archiveMutation\.isPending\) \{\s*return;\s*\}/);
    assert.match(list, /disabled=\{archiveMutation\.isPending\}/);
    assert.match(list, /invalidateFutureObligationQueries\(queryClient, session\?\.user\.id\)/);
    assert.match(list, /Alert\.alert\("Update failed"/);
  });

  it("create sends one idempotent request per tap and keeps the key across a failed attempt", () => {
    assert.match(create, /createSubmitGuard\(\)/);
    assert.match(create, /if \(createMutation\.isPending \|\| submitGuardRef\.current\.isBusy\(\)\) \{\s*return;\s*\}/);
    assert.match(create, /resolveCreateAttempt\(/);
    assert.match(create, /Crypto\.randomUUID\(\)/);
    assert.match(create, /toFutureObligationCreateInput\(attempt\)/);
    assert.equal((create.match(/createMutation\.mutate\(/g) ?? []).length, 1);
    assert.match(create, /onSettled: \(\) => \{\s*submitGuardRef\.current\.release\(\);/);
    assert.match(create, /createAttemptsRef\.current = \[\];/);
    assert.match(create, /describeCreateFailure\(mutationError, "bill", /);
  });

  it("create validates before sending, shows the message, and a rejected form never holds the guard", () => {
    assert.match(create, /validateFutureObligationForm\(values\)/);
    assert.match(create, /Alert\.alert\("Check the bill", validationError\)/);
    assert.ok(create.indexOf("validateFutureObligationForm(values)") < create.indexOf("submitGuardRef.current.tryEnter()"));
  });

  it("create refreshes the bills cache on success and returns to the previous screen", () => {
    assert.match(create, /await invalidateFutureObligationQueries\(queryClient, session\?\.user\.id\);\s*router\.back\(\)/);
  });

  it("create opens with the kind the user chose and today's local date", () => {
    assert.match(create, /scheduleParam === "one_time" \? "one_time" : "monthly"/);
    assert.match(create, /firstDueDate: localIsoDate\(new Date\(\)\)/);
  });

  it("edit loads the bill from the list, sends only changed fields, and archives or restores", () => {
    assert.match(edit, /select: \(obligations\) => obligations\.find\(\(candidate\) => candidate\.id === id\)/);
    assert.match(edit, /const changes = buildUpdatePayload\(obligation, values\)/);
    assert.match(edit, /const hasChanges = Object\.keys\(changes\)\.length > 0/);
    assert.match(edit, /if \(updateMutation\.isPending \|\| !hasChanges \|\| values === null\) \{\s*return;\s*\}/);
    assert.match(edit, /mutate\(\{ status: "active" \}\)/);
    assert.match(edit, /mutate\(\{ status: "archived" \}\)/);
    assert.match(edit, /archiveConfirmation\(obligation\.name\)/);
  });

  it("edit shows loading, a load error with Retry, and not-found states", () => {
    assert.match(edit, /<LoadingState what="bill" \/>/);
    assert.match(edit, /<LoadError what="bill"/);
    assert.match(edit, /Bill not found\./);
  });

  it("edit refreshes the bills cache on success and reports a failure without closing the form", () => {
    assert.match(edit, /await invalidateFutureObligationQueries\(queryClient, session\?\.user\.id\);\s*router\.back\(\)/);
    assert.match(edit, /Alert\.alert\("Update failed", getApiErrorMessage\(mutationError, "Unable to update the bill\."\)\)/);
  });

  it("the card has its own loading, error and Retry, and links to the screen and to adding a bill", () => {
    assert.match(card, /<QueryBoundary query=\{query\} what="upcoming bills">/);
    assert.match(card, /href="\/goals\/bills"/);
    assert.match(card, /pathname: "\/goals\/bills\/new"/);
  });

  it("a Link asChild never wraps a child with an array of styles (expo-router throws at render)", () => {
    // Found by the real-UI smoke check: <Link asChild><Pressable style={[a, b]}> crashes the screen.
    for (const source of [list, create, edit, card]) {
      assert.doesNotMatch(source, /<Link[^>]*asChild[^>]*>\s*<Pressable[^>]*style=\{\[/s);
    }
  });

  it("nothing pays, reserves or records an expense: no Expense, Account or Goal write is imported", () => {
    for (const source of [list, create, edit, card]) {
      assert.doesNotMatch(source, /expense\.service|createExpense|account\.service|createGoalTransaction|goal\.service|income\.service/);
    }
  });

  it("none of them does money arithmetic", () => {
    for (const source of [list, create, edit, card, code("future-obligation-form.tsx")]) {
      assert.doesNotMatch(source, /parseFloat|Number\(|parseInt|\.toFixed|Math\.|\bBigInt\b|\.reduce\(/);
    }
  });

  it("is accessible: headers, labelled inputs and buttons, spoken labels for the headline and month rows", () => {
    const form = code("future-obligation-form.tsx");

    assert.ok((list.match(/accessibilityRole="header"/g) ?? []).length >= 2);
    assert.match(list, /accessibilityLabel=\{`\$\{headline\.label\}: \$\{headline\.amount\}`\}/);
    assert.match(list, /accessibilityLabel=\{`\$\{group\.label\}: \$\{group\.value\}`\}/);
    assert.match(list, /accessibilityLabel=\{`Edit \$\{bill\.name\}`\}/);
    assert.match(card, /accessibilityLabel="Open upcoming bills"/);

    for (const label of ["Bill name", "Bill amount", "Bill currency", "First due date", "Last due date", "Bill note"]) {
      assert.match(form, new RegExp(`accessibilityLabel[^\\n]*${label}`), label);
    }

    assert.match(create, /accessibilityLabel="Save bill"/);
    assert.match(edit, /accessibilityLabel="Save changes"/);
  });

  it("long data-driven paragraphs use the explicit-line-height styles (iOS text clipping)", () => {
    for (const source of [list, card]) {
      assert.doesNotMatch(source, /styles\.(secondaryText|helperText)\b/);
    }

    assert.match(list, /styles\.overviewText/);
    assert.match(card, /styles\.overviewHelperText/);
  });
});

describe("the form", () => {
  const form = code("future-obligation-form.tsx");

  it("lets the user choose the kind of bill only on create, and shows it as fixed text on edit", () => {
    assert.match(form, /onScheduleChange\?: \(schedule: ObligationSchedule\) => void/);
    assert.match(form, /\(this cannot be changed\)/);
  });

  it("shows the last due date only for a monthly bill, and the not-paid note always", () => {
    assert.match(form, /\{isMonthly \? \(\s*<View style=\{styles\.formGroup\}>\s*<Text style=\{styles\.label\}>Last due date/);
    assert.match(form, /\{FORM_NOT_PAID\}/);
  });

  it("explains the clamped day, the optional end and that currencies are never added", () => {
    assert.match(form, /In a shorter month it falls on the last day of that month/);
    assert.match(form, /Leave blank if the bill has no end date/);
    assert.match(form, /Different currencies are never added together/);
  });
});

describe("navigation and placement", () => {
  it("registers the three routes with titles, under the Goals area", () => {
    const layout = appFile("_layout.tsx");

    for (const [name, title] of [["goals/bills/index", "Upcoming Bills"], ["goals/bills/new", "Add Bill"], ["goals/bills/[id]/edit", "Edit Bill"]]) {
      assert.match(layout, new RegExp(`name="${name.replace(/[[\]]/g, "\\$&")}"\\s+options=\\{\\{\\s+title: "${title}"`), name);
    }

    assert.match(appFile("goals/bills/index.tsx"), /FutureObligationsScreen/);
    assert.match(appFile("goals/bills/new.tsx"), /FutureObligationCreateScreen/);
    assert.match(appFile("goals/bills/[id]/edit.tsx"), /FutureObligationEditScreen/);
  });

  const screen = goalsCode("goals-screen.tsx");

  it("the Goals screen shows the bills card right after Savings plans, in the current view only", () => {
    const savings = screen.indexOf("<GoalSavingsOverviewSection query={savingsOverviewQuery} />");
    const bills = screen.indexOf("<UpcomingBillsCard query={upcomingBillsQuery} />");

    assert.ok(savings > 0 && bills > savings);
    assert.ok(bills < screen.indexOf("query={goalsQuery}"));
    assert.match(screen, /\{listView === "current" \? <UpcomingBillsCard query=\{upcomingBillsQuery\} \/> : null\}/);
  });

  it("the bills card has its own query and cache family, and joins pull-to-refresh", () => {
    assert.match(screen, /queryKey: \["future-obligations", session\?\.user\.id, "upcoming"\]/);
    assert.match(screen, /queryFn: \(\{ signal \}\) => getUpcomingObligations\(signal\)/);
    assert.match(screen, /refetcherOf\(savingsOverviewQuery\),\s*refetcherOf\(upcomingBillsQuery\),/);
  });

  it("the Savings plans overview and the Goal plan are untouched: they know nothing about bills", () => {
    for (const file of ["goal-savings-overview-view.ts", "goal-savings-overview-section.tsx", "goal-plan-view.ts", "goal-plan-section.tsx", "goal-history-view.ts", "goal-history-section.tsx"]) {
      assert.doesNotMatch(goalsCode(file), /future-obligation|FutureObligation|upcomingBills|Upcoming bills/i, file);
    }
  });

  it("the Goals list workflows are unchanged: the same delete guard and refreshes", () => {
    assert.equal((screen.match(/deleteGoalMutation\.mutate\(/g) ?? []).length, 1);
    assert.match(screen, /if \(deleteGoalMutation\.isPending\) \{\s*return;\s*\}/);
    assert.match(screen, /<QueryBoundary\s+query=\{goalsQuery\}/);
  });
});

describe("cache invalidation (real QueryClient, the app's key shapes)", () => {
  const USER = "user-1";
  const KEYS = {
    upcoming: ["future-obligations", USER, "upcoming"],
    list: ["future-obligations", USER, "list"],
    otherUsersUpcoming: ["future-obligations", "user-2", "upcoming"],
    goalList: ["goals", USER],
    goalOverview: ["goals", USER, "savings-overview"],
    goalHistory: ["goals", USER, "history-comparison", "g1"],
    goalPlan: ["goals", USER, "plan", "g1", "base"],
    accounts: ["accounts", USER],
    expenses: ["expenses", USER],
    income: ["income", USER],
    budgets: ["budgets", USER],
    analytics: ["analytics", "financial-overview", USER],
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

  it("a bill change re-reads the bills list and the projection, and nothing else", async () => {
    const client = seeded();

    await invalidateFutureObligationQueries(client, USER);

    assert.deepEqual(invalidated(client), ["list", "upcoming"]);
  });

  it("never touches another user's cache, or a signed-out session's", async () => {
    const client = seeded();

    await invalidateFutureObligationQueries(client, USER);

    assert.equal(client.getQueryState(KEYS.otherUsersUpcoming)?.isInvalidated, false);

    const signedOut = seeded();

    await invalidateFutureObligationQueries(signedOut, undefined);

    assert.deepEqual(invalidated(signedOut), []);
  });

  it("Goal, Income and Expense changes do not refresh the bills (they are a separate forecast input)", async () => {
    for (const run of [
      (client: QueryClient) => invalidateGoalTransactionQueries(client, USER, "g1", true),
      (client: QueryClient) => invalidateIncomeQueries(client, USER, true),
      (client: QueryClient) => invalidateExpenseQueries(client, USER, true),
    ]) {
      const client = seeded();

      await run(client);

      assert.ok(!invalidated(client).includes("upcoming"));
      assert.ok(!invalidated(client).includes("list"));
    }
  });

  it("a Goal list or prefix invalidation does not reach the bills cache", () => {
    const client = seeded();

    void client.invalidateQueries({ queryKey: ["goals", USER] });

    assert.deepEqual(invalidated(client).filter((name) => name === "upcoming" || name === "list"), []);
  });

  it("the bills cache helper is the only invalidation the bill screens use", () => {
    for (const file of ["future-obligations-screen.tsx", "future-obligation-create-screen.tsx", "future-obligation-edit-screen.tsx"]) {
      const source = code(file);

      assert.doesNotMatch(source, /invalidateQueries/, file);
      assert.match(source, /invalidateFutureObligationQueries/, file);
    }
  });
});
