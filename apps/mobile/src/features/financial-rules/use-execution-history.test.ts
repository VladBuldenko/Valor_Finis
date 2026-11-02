// VF-020F6: the history query, mounted with the real TanStack hooks under the
// real SessionScope / SessionQueryClient. The service is a scripted fake whose
// answers the test releases one by one, so ordering is never left to timers.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement, type ReactElement } from "react";
import TestRenderer from "react-test-renderer";

import { act } from "../../lib/mounted-test-support.ts";
import { SessionQueryClient } from "../../lib/session-query-client.ts";
import { SessionScope } from "../../lib/session-scope.ts";
import { historyKeyFilters, type HistoryFilters } from "./execution-history-data.ts";
import { applyRuleInvalidation } from "./financial-rule-invalidation.ts";
import { financialRuleKeys } from "./financial-rule-query-keys.ts";
import type { RuleExecutionFilters, RuleExecutionList } from "./financial-rule.types.ts";
import { RULE_1, ids, page } from "./history-fixtures.test-support.ts";
import { useExecutionHistory } from "./use-execution-history.ts";

type Call = { user: string | null; filters: RuleExecutionFilters; signal: AbortSignal | undefined };
type Gate = { resolve: (value: RuleExecutionList) => void; reject: (error: unknown) => void };

const NONE: HistoryFilters = { ruleId: null, status: null };
const sleep = (ms: number) => act(async () => { await new Promise((resolve) => setTimeout(resolve, ms)); });

function world() {
  const holder = new SessionQueryClient();
  const calls: Call[] = [];
  const gates: Gate[] = [];
  const seen: { value: ReturnType<typeof useExecutionHistory> | null } = { value: null };

  function Probe(props: { userId: string | null; filters: HistoryFilters }): null {
    const result = useExecutionHistory({
      userId: props.userId,
      filters: props.filters,
      listExecutions: (filters, signal) => {
        calls.push({ user: props.userId, filters, signal });

        return new Promise<RuleExecutionList>((resolve, reject) => { gates.push({ resolve, reject }); });
      },
    });
    const { feed } = result;

    // TanStack re-renders only for the result fields a component reads, so the
    // probe reads what the screen reads.
    void [feed.isError, feed.isFetchNextPageError, feed.isFetchingNextPage, feed.hasNextPage, feed.isRefetching, feed.fetchStatus];
    seen.value = result;

    return null;
  }

  const tree = (userId: string | null, filters: HistoryFilters = NONE): ReactElement =>
    createElement(SessionScope, { holder }, createElement(Probe, { userId, filters }));

  return {
    holder, calls, gates, seen, tree,
    async mount(userId: string | null, filters: HistoryFilters = NONE) {
      let renderer!: TestRenderer.ReactTestRenderer;

      await act(async () => { renderer = TestRenderer.create(tree(userId, filters)); });
      await sleep(10);

      return renderer;
    },
    async serve(index: number, value: RuleExecutionList) {
      await act(async () => { gates[index].resolve(value); });
      await sleep(10);
    },
    async fail(index: number) {
      await act(async () => { gates[index].reject(new Error("boom")); });
      await sleep(10);
    },
    async more() {
      await act(async () => { void seen.value?.feed.fetchNextPage(); });
      await sleep(10);
    },
    ids: () => seen.value?.merged?.items.map((e) => e.id) ?? [],
  };
}

describe("first page", () => {
  it("asks for 20 rows from offset 0 with the filters, passes the abort signal, and does nothing else on its own", async () => {
    const w = world();

    await w.mount("user-a", { ruleId: RULE_1, status: "blocked" });
    assert.equal(w.calls.length, 1);
    assert.deepEqual(w.calls[0].filters, { limit: 20, offset: 0, rule_id: RULE_1, status: "blocked" });
    assert.ok(w.calls[0].signal instanceof AbortSignal);
    await w.serve(0, page(ids(20), 45, 0));
    assert.equal(w.ids().length, 20);
    await sleep(60);
    assert.equal(w.calls.length, 1, "no automatic second request");
    assert.equal(w.seen.value?.feed.hasNextPage, true);
  });

  it("an unmounted screen aborts its request", async () => {
    const w = world();
    const renderer = await w.mount("user-a");

    await act(async () => { renderer.unmount(); });
    assert.equal(w.calls[0].signal?.aborted, true);
  });
});

describe("load more", () => {
  it("the next offset is the number of rows received; a row repeated by a shifted page is shown once", async () => {
    const w = world();

    await w.mount("user-a");
    await w.serve(0, page(ids(20), 45, 0));
    await w.more();
    assert.equal(w.calls[1].filters.offset, 20);
    // A run recorded meanwhile pushed e19 onto the second page.
    await w.serve(1, page(["e19", ...ids(19, 20)], 46, 20));

    assert.equal(w.ids().length, 39);
    assert.equal(new Set(w.ids()).size, 39, "no duplicate id across the page boundary");
    assert.equal(w.seen.value?.merged?.duplicatesDropped, 1);
    await w.more();
    assert.equal(w.calls[2].filters.offset, 40, "20 + 20 received, not 39 shown");
    await w.serve(2, page(ids(6, 39), 46, 40));
    assert.equal(w.seen.value?.feed.hasNextPage, false);
    assert.equal(w.seen.value?.merged?.hasMore, false);
  });

  it("an empty page ends paging instead of asking again", async () => {
    const w = world();

    await w.mount("user-a");
    await w.serve(0, page(ids(20), 45, 0));
    await w.more();
    await w.serve(1, page([], 45, 20));
    assert.equal(w.seen.value?.feed.hasNextPage, false);
    assert.equal(w.seen.value?.merged?.stalled, true);
  });

  it("a failed later page keeps the loaded rows, and its retry asks for the same offset", async () => {
    const w = world();

    await w.mount("user-a");
    await w.serve(0, page(ids(20), 45, 0));
    await w.more();
    await w.fail(1);

    assert.equal(w.seen.value?.feed.isFetchNextPageError, true);
    assert.equal(w.ids().length, 20, "loaded history is preserved");
    await w.more();
    assert.equal(w.calls[2].filters.offset, 20);
    await w.serve(2, page(ids(20, 20), 45, 20));
    assert.equal(w.ids().length, 40);
    assert.equal(w.seen.value?.feed.isFetchNextPageError, false);
  });
});

describe("empty is not failed", () => {
  it("a successful empty answer has data and no error", async () => {
    const w = world();

    await w.mount("user-a");
    await w.serve(0, page([], 0, 0));
    assert.deepEqual([w.seen.value?.merged?.items.length, w.seen.value?.feed.isError], [0, false]);
  });

  it("a failed first load has no data at all (so it can never read as empty)", async () => {
    const w = world();

    await w.mount("user-a");
    await w.fail(0);
    assert.equal(w.seen.value?.merged, null);
    assert.equal(w.seen.value?.feed.isError, true);
  });
});

describe("filters", () => {
  it("changing the filter restarts at offset 0 and a late answer for the old filter never shows", async () => {
    const w = world();
    const renderer = await w.mount("user-a", { ruleId: RULE_1, status: null });

    await act(async () => { renderer.update(w.tree("user-a", { ruleId: null, status: "blocked" })); });
    await sleep(10);
    assert.equal(w.calls.length, 2);
    assert.deepEqual(w.calls[1].filters, { limit: 20, offset: 0, status: "blocked" });

    await w.serve(1, page(ids(3, 0, "b"), 3, 0));
    await w.serve(0, page(ids(5, 0, "a"), 5, 0));

    assert.deepEqual(w.ids(), ["b0", "b1", "b2"]);

    const client = w.holder.get();
    const rowsOf = (filters: HistoryFilters) =>
      (client.getQueryData<{ pages: RuleExecutionList[] }>(financialRuleKeys.executionHistory("user-a", historyKeyFilters(filters))))
        ?.pages.flatMap((p) => p.items.map((e) => e.id)) ?? [];

    assert.ok(rowsOf({ ruleId: RULE_1, status: null }).every((id) => id.startsWith("a")), "old filter entry holds only its own rows");
    assert.ok(rowsOf({ ruleId: null, status: "blocked" }).every((id) => id.startsWith("b")));
  });

  it("each filter pair keeps its own cached pages", async () => {
    const w = world();
    const renderer = await w.mount("user-a");

    await w.serve(0, page(ids(20), 45, 0));
    await w.more();
    await w.serve(1, page(ids(20, 20), 45, 20));
    await act(async () => { renderer.update(w.tree("user-a", { ruleId: null, status: "expired" })); });
    await sleep(10);
    await w.serve(2, page(ids(2, 0, "x"), 2, 0));
    assert.deepEqual(w.ids(), ["x0", "x1"], "the new filter starts empty of the old rows");
  });
});

describe("refresh and invalidation", () => {
  it("a refresh re-reads the loaded pages with GET list calls only, in order", async () => {
    const w = world();

    await w.mount("user-a");
    await w.serve(0, page(ids(20), 45, 0));
    await w.more();
    await w.serve(1, page(ids(20, 20), 45, 20));
    await act(async () => { void w.seen.value?.feed.refetch(); });
    await sleep(10);
    assert.equal(w.calls[2].filters.offset, 0);
    await w.serve(2, page(ids(20), 46, 0));
    assert.equal(w.calls[3].filters.offset, 20);
    await w.serve(3, page(ids(20, 20), 46, 20));
    assert.equal(w.ids().length, 40);
    assert.ok(w.calls.every((call) => call.filters.limit === 20));
  });

  it("the existing rule events refresh the open history; an evaluation that changed nothing does not", async () => {
    const w = world();

    await w.mount("user-a");
    await w.serve(0, page(ids(2), 2, 0));

    await act(async () => {
      await applyRuleInvalidation(w.holder.get(), "user-a", {
        type: "evaluated",
        result: { processed: 0, deferred: 0, failed_retryable: 0, dead: 0, blocked: false, outcomes: {}, alerts_available: true, alerts_created: 0, alerts_resolved: 0, alerts_failed: false },
      });
    });
    await sleep(10);
    assert.equal(w.calls.length, 1);

    await act(async () => { void applyRuleInvalidation(w.holder.get(), "user-a", { type: "rule_status_changed", ruleId: RULE_1, action: "pause" }); });
    await sleep(10);
    assert.equal(w.calls.length, 2);
    assert.equal(w.calls[1].filters.offset, 0);
  });
});

describe("session ownership", () => {
  it("signed out: no request is made and nothing is shown", async () => {
    const w = world();

    await w.mount(null);
    await sleep(40);
    assert.equal(w.calls.length, 0);
    assert.equal(w.seen.value?.merged, null);
    assert.equal(w.seen.value?.feed.fetchStatus, "idle");
  });

  it("user A's answer arriving after user B signed in changes nothing in B's view or cache", async () => {
    const w = world();
    const renderer = await w.mount("user-a");

    await w.serve(0, page(ids(20, 0, "a"), 45, 0));
    await w.more();                       // A's second page is in flight
    const oldClient = w.holder.get();

    await act(async () => { w.holder.rotate(); renderer.update(w.tree("user-b")); });
    await sleep(10);
    assert.notEqual(w.holder.get(), oldClient);
    assert.equal(w.calls[2].user, "user-b");
    assert.equal(w.calls[2].filters.offset, 0, "B starts at the first page");

    await w.serve(1, page(ids(20, 20, "a"), 45, 20));   // A's late answer
    assert.ok(w.ids().length === 0, "B has not received anything from A");
    await w.serve(2, page(ids(2, 0, "b"), 2, 0));
    assert.deepEqual(w.ids(), ["b0", "b1"]);

    const newCache = w.holder.get().getQueryCache().getAll();

    assert.ok(newCache.every((query) => query.queryKey[1] !== "user-a"), "no entry of A in B's cache");

    const rows = newCache.flatMap((query) =>
      ((query.state.data as { pages?: RuleExecutionList[] } | undefined)?.pages ?? []).flatMap((p) => p.items.map((e) => e.id)),
    );

    assert.deepEqual(rows, ["b0", "b1"], "only B's rows are in B's cache");
  });

  it("sign-out drops the history and requests nothing for the signed-out screen", async () => {
    const w = world();
    const renderer = await w.mount("user-a");

    await w.serve(0, page(ids(2), 2, 0));
    await act(async () => { w.holder.rotate(); renderer.update(w.tree(null)); });
    await sleep(20);
    assert.equal(w.calls.length, 1);
    assert.equal(w.seen.value?.merged, null);
    assert.equal(w.holder.get().getQueryCache().getAll().filter((q) => q.queryKey[0] === "rule-executions").length, 0);
  });

  it("the same filters for two users are two different entries", async () => {
    const w = world();

    await w.mount("user-a");
    await w.serve(0, page(ids(1, 0, "a"), 1, 0));
    const keyA = financialRuleKeys.executionHistory("user-a", historyKeyFilters(NONE));
    const keyB = financialRuleKeys.executionHistory("user-b", historyKeyFilters(NONE));

    assert.ok(w.holder.get().getQueryData(keyA), "A's rows are stored under A's key");
    assert.equal(w.holder.get().getQueryData(keyB), undefined);
  });

  it("even on ONE shared QueryClient (no rotation), B never sees A's cached rows", async () => {
    // The key layer alone: the session layer is deliberately taken away.
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const calls: { user: string | null; offset: number | undefined }[] = [];
    const gates: Gate[] = [];
    const seen: { value: ReturnType<typeof useExecutionHistory> | null } = { value: null };

    function Probe(props: { userId: string | null }): null {
      const result = useExecutionHistory({
        userId: props.userId,
        filters: NONE,
        listExecutions: (filters) => {
          calls.push({ user: props.userId, offset: filters.offset });

          return new Promise<RuleExecutionList>((resolve, reject) => { gates.push({ resolve, reject }); });
        },
      });

      void [result.feed.isError, result.feed.fetchStatus];
      seen.value = result;

      return null;
    }

    const tree = (userId: string | null) => createElement(QueryClientProvider, { client }, createElement(Probe, { userId }));
    let renderer!: TestRenderer.ReactTestRenderer;

    await act(async () => { renderer = TestRenderer.create(tree("user-a")); });
    await sleep(10);
    await act(async () => { gates[0].resolve(page(ids(3, 0, "a"), 3, 0)); });
    await sleep(10);
    assert.equal(seen.value?.merged?.items.length, 3);

    await act(async () => { renderer.update(tree("user-b")); });
    await sleep(10);
    assert.equal(seen.value?.merged, null, "B starts with nothing from A");
    assert.deepEqual(calls.map((c) => c.user), ["user-a", "user-b"]);
  });
});
