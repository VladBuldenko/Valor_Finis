// VF-MOB-REFRESH-RETRY: loading/empty/error/retry/refresh with the REAL TanStack
// hooks and the real useScreenRefresh, mounted by the Node runner.
import assert from "node:assert/strict";
import { describe, it, mock } from "node:test";

import { QueryClient, QueryClientProvider, useMutation, useQuery } from "@tanstack/react-query";
import { createElement, type ReactElement } from "react";
import TestRenderer from "react-test-renderer";

import { act } from "./mounted-test-support.ts";
import { boundaryView, combinedPhase, type BoundaryView } from "./query-view.ts";
import { createRefreshCoordinator, refetcherOf, useScreenRefresh, type ScreenRefresh } from "./screen-refresh.ts";

type Gate = { resolve: (value: string[]) => void; reject: (error: unknown) => void };
const sleep = (ms = 10) => act(async () => { await new Promise((resolve) => setTimeout(resolve, ms)); });

// A scripted read: every call is a gate the test settles.
function source() {
  const gates: Gate[] = [];

  return {
    gates,
    fetch: () => new Promise<string[]>((resolve, reject) => { gates.push({ resolve, reject }); }),
  };
}

function world(keys: string[] = ["a"]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const sources = Object.fromEntries(keys.map((key) => [key, source()]));
  const seen: { views: Record<string, BoundaryView>; refresh: ScreenRefresh | null; queries: Record<string, ReturnType<typeof useQuery<string[]>>> } = {
    views: {}, refresh: null, queries: {},
  };
  const mutationFn = mock.fn(async () => "written");

  function Probe(): null {
    // Hooks are called unconditionally; "b" is simply disabled when unused.
    const first = useQuery<string[]>({ queryKey: ["screen", keys[0]], queryFn: sources[keys[0]].fetch });
    const second = useQuery<string[]>({
      queryKey: ["screen", keys[1] ?? "unused"],
      queryFn: sources[keys[1] ?? keys[0]].fetch,
      enabled: keys.length > 1,
    });
    const queries: Record<string, typeof first> = { [keys[0]]: first };

    if (keys.length > 1) {
      queries[keys[1]] = second;
    }

    for (const key of keys) {
      const query = queries[key];

      void [query.data, query.isError, query.isFetching, query.error];
      seen.views[key] = boundaryView(query, (data) => data.length === 0);
      seen.queries[key] = query;
    }

    seen.refresh = useScreenRefresh(() => keys.map((key) => refetcherOf(queries[key])));
    useMutation({ mutationFn });

    return null;
  }

  const tree = (): ReactElement => createElement(QueryClientProvider, { client }, createElement(Probe));

  return {
    client, sources, seen, mutationFn,
    async mount() {
      let renderer!: TestRenderer.ReactTestRenderer;

      await act(async () => { renderer = TestRenderer.create(tree()); });
      await sleep();

      return renderer;
    },
    async settle(key: string, index: number, value: string[] | Error) {
      await act(async () => {
        if (value instanceof Error) {
          sources[key].gates[index].reject(value);
        } else {
          sources[key].gates[index].resolve(value);
        }
      });
      await sleep();
    },
    async pull() { await act(async () => { seen.refresh?.onRefresh(); }); await sleep(); },
    async retry(key: string) { await act(async () => { void seen.queries[key].refetch(); }); await sleep(); },
  };
}

describe("loading -> data / empty / error", () => {
  it("loading, then data", async () => {
    const w = await world(); await w.mount();
    assert.equal(w.seen.views.a.kind, "loading");
    await w.settle("a", 0, ["x"]);
    assert.equal(w.seen.views.a.kind, "content");
  });

  it("loading, then a genuine empty result", async () => {
    const w = world(); await w.mount();
    await w.settle("a", 0, []);
    assert.deepEqual(w.seen.views.a, { kind: "empty", refreshError: false });
  });

  it("loading, then an error: Retry is offered and it is not empty", async () => {
    const w = world(); await w.mount();
    await w.settle("a", 0, new Error("boom"));
    assert.equal(w.seen.views.a.kind, "error");
  });

  it("Retry re-runs the failed READ and recovers", async () => {
    const w = world(); await w.mount();
    await w.settle("a", 0, new Error("boom"));
    await w.retry("a");
    assert.equal(w.sources.a.gates.length, 2, "exactly one more read");
    await w.settle("a", 1, ["x"]);
    assert.equal(w.seen.views.a.kind, "content");
    assert.equal(w.mutationFn.mock.callCount(), 0);
  });

  it("Retry that fails again stays an error and can be retried again", async () => {
    const w = world(); await w.mount();
    await w.settle("a", 0, new Error("one"));
    await w.retry("a");
    await w.settle("a", 1, new Error("two"));
    assert.equal(w.seen.views.a.kind, "error");
    await w.retry("a");
    assert.equal(w.sources.a.gates.length, 3);
    await w.settle("a", 2, ["ok"]);
    assert.equal(w.seen.views.a.kind, "content");
  });
});

describe("pull to refresh", () => {
  it("shows a real refreshing state, keeps the data, then settles", async () => {
    const w = world(); await w.mount();
    await w.settle("a", 0, ["x"]);
    await w.pull();
    assert.equal(w.seen.refresh?.refreshing, true);
    assert.equal(w.seen.views.a.kind, "content", "data stays while refreshing");
    await w.settle("a", 1, ["x", "y"]);
    assert.equal(w.seen.refresh?.refreshing, false);
    assert.deepEqual(w.seen.queries.a.data, ["x", "y"]);
  });

  it("a failed refresh keeps the previous data and reports the failure", async () => {
    const w = world(); await w.mount();
    await w.settle("a", 0, ["x"]);
    await w.pull();
    await w.settle("a", 1, new Error("down"));
    assert.deepEqual(w.seen.queries.a.data, ["x"]);
    assert.deepEqual(w.seen.views.a, { kind: "content", refreshError: true });
    assert.equal(w.seen.refresh?.refreshing, false);
    await w.retry("a");
    await w.settle("a", 2, ["z"]);
    assert.deepEqual(w.seen.views.a, { kind: "content", refreshError: false });
  });

  it("a failed refresh of an empty list stays the genuine empty state with the notice", async () => {
    const w = world(); await w.mount();
    await w.settle("a", 0, []);
    await w.pull();
    await w.settle("a", 1, new Error("down"));
    assert.deepEqual(w.seen.views.a, { kind: "empty", refreshError: true });
  });

  it("several queries refresh together; one failing leaves the others' data", async () => {
    const w = world(["a", "b"]); await w.mount();
    await w.settle("a", 0, ["a1"]);
    await w.settle("b", 0, ["b1"]);
    await w.pull();
    assert.equal(w.sources.a.gates.length, 2);
    assert.equal(w.sources.b.gates.length, 2);
    await w.settle("a", 1, ["a2"]);
    assert.equal(w.seen.refresh?.refreshing, true, "still refreshing until every read ended");
    await w.settle("b", 1, new Error("down"));
    assert.equal(w.seen.refresh?.refreshing, false);
    assert.deepEqual(w.seen.queries.a.data, ["a2"]);
    assert.deepEqual(w.seen.queries.b.data, ["b1"]);
  });

  it("partial failure while loading: the secondary error does not hide the primary data", async () => {
    const w = world(["main", "extra"]); await w.mount();
    await w.settle("main", 0, ["row"]);
    await w.settle("extra", 0, new Error("down"));
    assert.equal(w.seen.views.main.kind, "content");
    assert.equal(w.seen.views.extra.kind, "error");
    assert.equal(combinedPhase([w.seen.queries.main, w.seen.queries.extra]), "error");
  });

  it("repeated pulls while one refresh runs cause no extra requests (no storm)", async () => {
    const w = world(["a", "b"]); await w.mount();
    await w.settle("a", 0, ["a"]);
    await w.settle("b", 0, ["b"]);
    for (let i = 0; i < 6; i += 1) await w.pull();
    assert.deepEqual([w.sources.a.gates.length, w.sources.b.gates.length], [2, 2]);
    await w.settle("a", 1, ["a"]);
    await w.settle("b", 1, ["b"]);
    await w.pull();
    assert.deepEqual([w.sources.a.gates.length, w.sources.b.gates.length], [3, 3], "a new pull works once the last one ended");
  });

  it("a pull while the same read is already in flight reuses it instead of restarting it", async () => {
    const w = world(); await w.mount();
    await w.settle("a", 0, ["x"]);
    await w.retry("a");                    // a read is now in flight
    assert.equal(w.sources.a.gates.length, 2);
    await w.pull();
    assert.equal(w.sources.a.gates.length, 2, "cancelRefetch:false -> no second request");
    await w.settle("a", 1, ["y"]);
  });

  it("refreshing never starts a mutation", async () => {
    const w = world(["a", "b"]); await w.mount();
    await w.settle("a", 0, ["a"]);
    await w.settle("b", 0, ["b"]);
    await w.pull();
    await w.settle("a", 1, new Error("down"));
    await w.settle("b", 1, ["b"]);
    assert.equal(w.mutationFn.mock.callCount(), 0);
    assert.equal(w.client.getMutationCache().getAll().length, 0, "no mutation was created");
  });

  it("leaving the screen mid-refresh is safe", async () => {
    const w = world(); const renderer = await w.mount();
    await w.settle("a", 0, ["x"]);
    await w.pull();
    await act(async () => { renderer.unmount(); });
    await act(async () => { w.sources.a.gates[1].resolve(["y"]); });
    await sleep();
  });
});

describe("the refresh coordinator", () => {
  it("runs once at a time, survives a throwing or rejecting refetcher, and frees itself", async () => {
    const coordinator = createRefreshCoordinator();
    const calls: string[] = [];
    const first = coordinator.run(() => [
      () => { calls.push("throws"); throw new Error("sync"); },
      () => { calls.push("rejects"); return Promise.reject(new Error("async")); },
      async () => { calls.push("ok"); },
    ]);

    assert.ok(first);
    assert.equal(coordinator.isRunning(), true);
    assert.equal(coordinator.run(() => [async () => { calls.push("second"); }]), null);
    await first;
    await sleep(0);
    assert.deepEqual(calls, ["throws", "rejects", "ok"]);
    assert.equal(coordinator.isRunning(), false);
    assert.ok(coordinator.run(() => []));
  });

  it("refetcherOf asks not to cancel an in-flight read", async () => {
    const received: unknown[] = [];

    await refetcherOf({ refetch: async (options) => { received.push(options); } })();
    assert.deepEqual(received, [{ cancelRefetch: false }]);
  });
});
