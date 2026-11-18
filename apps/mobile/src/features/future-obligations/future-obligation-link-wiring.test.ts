// VF-GOALS-PLANNING-002C2: wiring of "Linked expenses" into the app. Source checks in the
// project's usual style (React Native components cannot be mounted in the Node
// runner) plus a real TanStack QueryClient for cache behavior: the request contract,
// the query keys, loading/error/Retry, refresh, double-tap protection, the way a
// link and an unlink refresh the screens, and that no existing workflow changed.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import { QueryClient } from "@tanstack/react-query";

import { invalidateExpenseQueries } from "../expenses/expense-cache.ts";
import { invalidateIncomeQueries } from "../income/income-cache.ts";
import { invalidateFutureObligationQueries } from "./future-obligation-cache.ts";
import { invalidateReconciliationQueries } from "./future-obligation-link-cache.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..", "..", "..");
const strip = (text: string) => text.replace(/\/\/.*$/gm, "");
const code = (file: string) => strip(readFileSync(join(HERE, file), "utf8"));
const appFile = (path: string) => readFileSync(join(ROOT, "app", "(app)", path), "utf8");

describe("request contract", () => {
  const service = code("future-obligation-link.service.ts");

  it("reads the overview and the candidates with plain, abortable GETs", () => {
    assert.match(service, /apiRequest<ReconciliationOverview>\("\/api\/v1\/future-obligations\/reconciliation", \{\s*signal,?\s*\}\)/);
    assert.match(service, /`\/api\/v1\/future-obligations\/\$\{obligationId\}\/occurrence-candidates\?due_date=\$\{encodeURIComponent\(dueDate\)\}`,\s*\{ signal \}/);
  });

  it("links with POST and unlinks with DELETE of exactly one link", () => {
    assert.match(service, /`\/api\/v1\/future-obligations\/\$\{obligationId\}\/occurrence-links`,\s*\{\s*method: "POST",\s*body: JSON\.stringify\(input\)/);
    assert.match(service, /`\/api\/v1\/future-obligations\/\$\{obligationId\}\/occurrence-links\/\$\{linkId\}`,\s*\{ method: "DELETE" \}/);
  });

  it("sends only the due date and the expense id: the backend decides everything else", () => {
    const types = code("future-obligation-link.types.ts");

    assert.match(types, /export type OccurrenceLinkInput = \{\s*due_date: string;\s*expense_id: string;\s*\};/);
  });

  it("does no number handling", () => {
    assert.doesNotMatch(service, /parseFloat|Number\(|parseInt|\.toFixed|Math\./);
  });

  it("the response types mirror the backend contract", () => {
    const types = code("future-obligation-link.types.ts");

    for (const field of [
      "link_id", "expense_id", "expense_date", "linked_at", "linked_expense", "obligation_status", "is_past",
      "window_start", "window_end", "candidates", "candidate_limit", "excluded", "different_currency",
      "different_amount", "already_linked", "dated_in_future", "due_date", "obligation_id",
    ]) {
      assert.match(types, new RegExp(`\\b${field}\\b`), field);
    }
  });
});

describe("the screens", () => {
  const list = code("future-obligation-occurrences-screen.tsx");
  const detail = code("future-obligation-occurrence-screen.tsx");

  it("use the bills cache family with the user id in every key", () => {
    for (const source of [list, detail]) {
      for (const match of source.match(/queryKey: \[[^\]]*\]/g) ?? []) {
        assert.match(match, /"future-obligations", (session\?\.user\.id|userId), "(reconciliation|candidates)"/, match);
      }
    }
  });

  it("the list has loading, error, Retry and an empty state, and pull-to-refresh", () => {
    assert.match(list, /<QueryBoundary\s+query=\{overviewQuery\}\s+what="bill dates"/);
    assert.match(list, /isEmpty=\{\(overview\) => overview\.occurrences\.length === 0\}/);
    assert.match(list, /empty=\{LINKS_EMPTY\}/);
    assert.match(list, /useScreenRefresh\(\(\) => \[refetcherOf\(overviewQuery\)\]\)/);
    assert.match(list, /<RefreshControl refreshing=\{refresh\.refreshing\} onRefresh=\{refresh\.onRefresh\} \/>/);
  });

  it("each date opens the date screen with the bill and the due date", () => {
    assert.match(list, /pathname: "\/goals\/bills\/occurrence"/);
    assert.match(list, /params: \{ obligationId: occurrence\.obligation_id, dueDate: occurrence\.due_date \}/);
    // <Link asChild> must wrap a child with ONE style object (an array crashes the screen).
    assert.match(list, /style=\{styles\.card\}/);
    assert.doesNotMatch(list, /style=\{\[/);
  });

  it("the date screen has loading, error and Retry for the date and for the picker, and refreshes the date", () => {
    assert.match(detail, /<QueryBoundary query=\{overviewQuery\} what="bill date"/);
    assert.match(detail, /<QueryBoundary query=\{candidatesQuery\} what="expenses to link"/);
    assert.match(detail, /useScreenRefresh\(\(\) => \[refetcherOf\(overviewQuery\)\]\)/);
  });

  it("reads the candidates only while the picker is open, for one date", () => {
    assert.match(detail, /enabled: Boolean\(session\) && picking && Boolean\(obligationId\) && Boolean\(dueDate\)/);
    assert.match(detail, /queryKey: \["future-obligations", userId, "candidates", obligationId, dueDate\]/);
  });

  it("offers the picker only for a bill that is active and a date without a link", () => {
    assert.match(detail, /occurrence\.obligation_status === "active" \?/);
    assert.match(detail, /accessibilityLabel="Link existing expense"/);
    assert.match(detail, /accessibilityLabel="Remove link"/);
    assert.match(detail, /linked !== null \? \(/);
  });

  it("lets the user inspect the linked expense on the existing expense screen", () => {
    assert.match(detail, /pathname: "\/expenses\/\[id\]", params: \{ id: linked\.expense_id \}/);
  });

  it("link and unlink are confirmed, send one request, and ignore a second tap while busy", () => {
    assert.equal((detail.match(/\blinkMutation\.mutate\(/g) ?? []).length, 1);
    assert.equal((detail.match(/unlinkMutation\.mutate\(/g) ?? []).length, 1);
    assert.match(detail, /const busy = linkMutation\.isPending \|\| unlinkMutation\.isPending;/);
    assert.match(detail, /function handleChoose[\s\S]*?if \(busy\) \{\s*return;\s*\}/);
    assert.match(detail, /function handleUnlink[\s\S]*?if \(busy \|\| linked === null\) \{\s*return;\s*\}/);
    assert.equal((detail.match(/disabled=\{busy\}/g) ?? []).length, 3);
    assert.match(detail, /linkConfirmation\(occurrence, candidate\)/);
    assert.match(detail, /unlinkConfirmation\(occurrence\)/);
    assert.match(detail, /style: "destructive", onPress: \(\) => unlinkMutation\.mutate\(linked\.link_id\)/);
  });

  it("a refused or failed write says why and re-reads what is on screen", () => {
    assert.match(detail, /Alert\.alert\("Link failed", getApiErrorMessage\(mutationError, "Unable to link the expense\."\)\)/);
    assert.match(detail, /Alert\.alert\("Remove failed", getApiErrorMessage\(mutationError, "Unable to remove the link\."\)\)/);
    assert.equal((detail.match(/await invalidateReconciliationQueries\(queryClient, userId\);/g) ?? []).length, 4);
  });

  it("closes the picker after a successful link and never adds a link locally", () => {
    assert.match(detail, /onSuccess: async \(\) => \{\s*setPicking\(false\);/);
    assert.doesNotMatch(detail, /setQueryData|setQueriesData/);
    assert.doesNotMatch(list, /setQueryData|setQueriesData/);
  });

  it("states a date that is gone instead of showing a stale one", () => {
    assert.match(detail, /if \(occurrence === null\) \{\s*return <Text style=\{styles\.overviewText\}>\{OCCURRENCE_GONE\}<\/Text>;/);
  });

  it("shows no paid, confirmed or overdue status of its own", () => {
    for (const source of [list, detail]) {
      assert.doesNotMatch(source, />\s*Paid\s*</i);
      assert.doesNotMatch(source, /overdue|unpaid|outstanding/i);
    }
  });
});

describe("navigation and placement", () => {
  it("registers both routes with titles, under the Goals bills area", () => {
    const layout = appFile("_layout.tsx");

    for (const [name, title] of [["goals/bills/links", "Linked Expenses"], ["goals/bills/occurrence", "Bill Date"]]) {
      assert.match(layout, new RegExp(`name="${name}"\\s+options=\\{\\{\\s+title: "${title}"`), name);
    }

    assert.match(appFile("goals/bills/links.tsx"), /FutureObligationOccurrencesScreen/);
    assert.match(appFile("goals/bills/occurrence.tsx"), /FutureObligationOccurrenceScreen/);
  });

  it("the bills screen links to the new list and is otherwise unchanged", () => {
    const bills = code("future-obligations-screen.tsx");

    assert.match(bills, /<Link href="\/goals\/bills\/links" asChild>/);
    assert.match(bills, /accessibilityLabel="Link expenses to bills"/);
    assert.match(bills, /useScreenRefresh\(\(\) => \[refetcherOf\(upcomingQuery\), refetcherOf\(listQuery\)\]\)/);
    assert.doesNotMatch(bills, /reconciliation|candidates|linkOccurrence/);
  });

  it("the Goals screen and the Goal plan, history and savings views know nothing about links", () => {
    for (const file of ["goals-screen.tsx", "goal-savings-overview-view.ts", "goal-plan-view.ts", "goal-history-view.ts"]) {
      assert.doesNotMatch(readFileSync(join(HERE, "..", "goals", file), "utf8"), /occurrence|linked_expense|reconciliation/i, file);
    }
  });

  it("the bills list, upcoming projection and card never read the link views", () => {
    for (const file of ["future-obligation-view.ts", "upcoming-bills-card.tsx", "future-obligation-form.tsx"]) {
      assert.doesNotMatch(code(file), /linked_expense|reconciliation|occurrence-links/, file);
    }
  });
});

describe("cache invalidation (real QueryClient, the app's key shapes)", () => {
  const USER = "user-1";
  const KEYS = {
    reconciliation: ["future-obligations", USER, "reconciliation"],
    candidates: ["future-obligations", USER, "candidates", "rent", "2026-11-30"],
    upcoming: ["future-obligations", USER, "upcoming"],
    list: ["future-obligations", USER, "list"],
    otherUsersReconciliation: ["future-obligations", "user-2", "reconciliation"],
    otherUsersCandidates: ["future-obligations", "user-2", "candidates", "rent", "2026-11-30"],
    goalList: ["goals", USER],
    goalOverview: ["goals", USER, "savings-overview"],
    accounts: ["accounts", USER],
    income: ["income", USER],
    budgets: ["budgets", USER],
  };

  function seeded() {
    const client = new QueryClient();

    for (const key of Object.values(KEYS)) {
      client.setQueryData(key, {});
    }

    client.setQueryData(["expenses", USER], {});
    client.setQueryData(["analytics", "financial-overview", USER], {});

    return client;
  }

  const invalidated = (client: QueryClient) =>
    Object.entries(KEYS)
      .filter(([, key]) => client.getQueryState(key)?.isInvalidated)
      .map(([name]) => name)
      .sort();

  it("a link or an unlink re-reads the overview and the candidates, and nothing else", async () => {
    const client = seeded();

    await invalidateReconciliationQueries(client, USER);

    assert.deepEqual(invalidated(client), ["candidates", "reconciliation"]);
    // The bills list and the upcoming projection do not change with a link.
    assert.equal(client.getQueryState(KEYS.upcoming)?.isInvalidated, false);
    assert.equal(client.getQueryState(["expenses", USER])?.isInvalidated, false);
  });

  it("an Expense change re-reads the link views, but not the bills list or the projection", async () => {
    const client = seeded();

    await invalidateExpenseQueries(client, USER, false);

    assert.deepEqual(invalidated(client), ["candidates", "goalOverview", "reconciliation"]);
    assert.equal(client.getQueryState(["expenses", USER])?.isInvalidated, true);
    assert.equal(client.getQueryState(KEYS.upcoming)?.isInvalidated, false);
    assert.equal(client.getQueryState(KEYS.list)?.isInvalidated, false);
  });

  it("a bill edit re-reads the whole bills family, which includes the link views", async () => {
    const client = seeded();

    await invalidateFutureObligationQueries(client, USER);

    assert.deepEqual(invalidated(client), ["candidates", "list", "reconciliation", "upcoming"]);
  });

  it("an Income change does not touch the link views", async () => {
    const client = seeded();

    await invalidateIncomeQueries(client, USER, true);

    assert.equal(client.getQueryState(KEYS.reconciliation)?.isInvalidated, false);
    assert.equal(client.getQueryState(KEYS.candidates)?.isInvalidated, false);
  });

  it("never touches another user's cache, or a signed-out session's", async () => {
    const client = seeded();

    await invalidateReconciliationQueries(client, USER);
    await invalidateExpenseQueries(client, USER, true);

    assert.equal(client.getQueryState(KEYS.otherUsersReconciliation)?.isInvalidated, false);
    assert.equal(client.getQueryState(KEYS.otherUsersCandidates)?.isInvalidated, false);

    const signedOut = seeded();

    await invalidateReconciliationQueries(signedOut, undefined);

    assert.deepEqual(invalidated(signedOut), []);
  });
});
