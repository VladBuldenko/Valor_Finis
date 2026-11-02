// VF-MOB-REFRESH-RETRY: foreground refetch through the REAL focus manager and
// the REAL TanStack hooks, under the real SessionScope / SessionQueryClient /
// SessionBoundary / API transport with a scripted fetch. Supabase, the
// AuthProvider and Expo Router are deliberately not involved.
import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";

import { QueryClient, QueryClientProvider, focusManager, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createElement, useEffect, useState, useSyncExternalStore, type ReactElement, type ReactNode } from "react";
import TestRenderer from "react-test-renderer";

import { createApiTransport } from "../api/api-transport.ts";
import { SessionBoundary } from "../api/session-boundary.ts";
import type { SessionIdentity } from "../api/session-lifecycle.ts";
import { deriveInboxIndicator, sourceStateFromQuery } from "../features/financial-rules/inbox-data.ts";
import { page, ids } from "../features/financial-rules/history-fixtures.test-support.ts";
import { RulesEvaluationProvider } from "../features/financial-rules/rules-evaluation-provider.ts";
import { useExecutionHistory } from "../features/financial-rules/use-execution-history.ts";
import type { RuleEvaluationResult } from "../features/financial-rules/financial-rule.types.ts";
import { installAppFocus } from "./app-focus.ts";
import { USER_A, USER_A_SECOND, USER_B, act } from "./mounted-test-support.ts";
import { SessionQueryClient } from "./session-query-client.ts";
import { SessionScope } from "./session-scope.ts";

type Held = { user: string; release: () => void };
type Seen = { owner: string; n: number } | undefined;

const sleep = (ms = 15) => act(async () => { await new Promise((resolve) => setTimeout(resolve, ms)); });

// One AppState the bridge, the evaluation host and the test all share.
function appState(initial = "active") {
  const listeners = new Set<(state: string) => void>();
  const current = { value: initial };

  return {
    listeners,
    get: () => current.value,
    subscribe: (listener: (state: string) => void) => {
      listeners.add(listener);

      return () => { listeners.delete(listener); };
    },
    emit: async (state: string) => {
      current.value = state;
      await act(async () => { listeners.forEach((listener) => listener(state)); });
      await sleep();
    },
  };
}

function world(options: { staleTime?: number; holdGets?: boolean; signedIn?: boolean; unkeyed?: boolean } = {}) {
  const holder = new SessionQueryClient();
  const boundary = new SessionBoundary(() => holder.rotate());
  const auth: { session: SessionIdentity | null } = { session: options.signedIn === false ? null : USER_A };
  const authListeners = new Set<() => void>();
  const snapshot = { current: auth.session };
  const subscribeAuth = (listener: () => void) => { authListeners.add(listener); return () => { authListeners.delete(listener); }; };
  const http: { user: string; method: string; path: string; token: string }[] = [];
  const held: Held[] = [];
  const counters = { get: 0 };
  const flags = { hold: options.holdGets === true, failPost: false };
  const mutationRuns = { count: 0 };
  const probes: { owner: string; query: ReturnType<typeof useQuery<Seen>> | null; mutate: (() => void) | null; mounted: boolean }[] = [];

  const transport = createApiTransport({
    baseUrl: "https://api.test",
    boundary,
    sleep: async () => undefined,
    getSession: async () => auth.session,
    onUnauthorized: async () => undefined,
    fetch: async (url, init) => {
      const token = new Headers(init.headers).get("Authorization") ?? "";
      const user = token.includes("b-token") ? "user-b" : "user-a";
      const method = init.method ?? "GET";

      http.push({ user, method, path: url.replace("https://api.test", ""), token });

      if (method !== "GET") {
        if (flags.failPost) throw new TypeError("network down");

        return new Response(JSON.stringify({ ok: true }), { status: 200 });
      }

      counters.get += 1;
      const n = counters.get;

      if (flags.hold) {
        await new Promise<void>((resolve) => { held.push({ user, release: resolve }); });
      }

      return new Response(JSON.stringify({ owner: user, n }), { status: 200 });
    },
  });

  boundary.applyAuthEvent(auth.session?.userId ?? null, auth.session?.accessToken ?? null);

  function Probe(): ReactElement | null {
    const client = useQueryClient();
    const [record] = useState(() => {
      const created = { owner: auth.session?.userId ?? "none", query: null as ReturnType<typeof useQuery<Seen>> | null, mutate: null as (() => void) | null, mounted: true, client };

      probes.push(created);

      return created;
    });
    const query = useQuery<Seen>({
      queryKey: ["items"],
      queryFn: () => transport.request<{ owner: string; n: number }>("/api/v1/items"),
      staleTime: options.staleTime ?? 0,
    });
    const mutation = useMutation({
      mutationFn: () => { mutationRuns.count += 1; return transport.request("/api/v1/things", { method: "POST", body: "{}" }); },
    });

    void [query.data, query.isError, query.isFetching, mutation.isPending, mutation.isError];
    record.query = query;
    record.mutate = () => mutation.mutate();
    useEffect(() => () => { record.mounted = false; }, [record]);

    return null;
  }

  function AuthGate(props: { children?: ReactNode }): ReactElement | null {
    const session = useSyncExternalStore(subscribeAuth, () => snapshot.current);

    return session ? createElement("authenticated", null, props.children) : null;
  }

  function Unkeyed(props: { children?: ReactNode }): ReactElement {
    const [client, setClient] = useState(holder.get());

    useEffect(() => holder.subscribe(() => setClient(holder.get())), []);

    return createElement(QueryClientProvider, { client }, props.children);
  }

  const current = () => {
    const live = probes.filter((probe) => probe.mounted);

    if (live.length !== 1) throw new Error(`expected one mounted probe, found ${live.length}`);

    return live[0];
  };

  return {
    holder, boundary, auth, http, held, counters, flags, mutationRuns, probes, current,
    transport,
    async mount(extra?: (children: ReactNode) => ReactElement) {
      let renderer!: TestRenderer.ReactTestRenderer;
      const children = createElement(AuthGate, null, createElement(Probe));

      await act(async () => {
        renderer = TestRenderer.create(
          extra ? extra(children) : options.unkeyed ? createElement(Unkeyed, null, children) : createElement(SessionScope, { holder }, children),
        );
      });
      await sleep();

      return renderer;
    },
    async authEvent(session: SessionIdentity | null) {
      await act(async () => {
        auth.session = session;
        boundary.applyAuthEvent(session?.userId ?? null, session?.accessToken ?? null);
        snapshot.current = session;
        authListeners.forEach((listener) => listener());
      });
      await sleep();
    },
    async releaseAll() {
      await act(async () => { held.splice(0).forEach((h) => h.release()); });
      await sleep();
    },
  };
}

// The bridge under test, wired to the real focus manager.
function withBridge(state: ReturnType<typeof appState>) {
  return installAppFocus({ focusManager, subscribeAppState: state.subscribe, getAppState: state.get });
}

const cleanups: (() => void)[] = [];

afterEach(() => {
  cleanups.splice(0).forEach((cleanup) => cleanup());
  focusManager.setFocused(undefined);
});

describe("returning to the app refetches the active queries", () => {
  it("background -> active: one refetch of the mounted query", async () => {
    const state = appState(); const w = world();

    cleanups.push(withBridge(state));
    await w.mount();
    assert.equal(w.counters.get, 1);
    await state.emit("background");
    assert.equal(w.counters.get, 1, "leaving the app fetches nothing");
    await state.emit("active");
    assert.equal(w.counters.get, 2);
    assert.equal(w.current().query?.data?.n, 2);
  });

  it("inactive -> active counts too", async () => {
    const state = appState(); const w = world();

    cleanups.push(withBridge(state));
    await w.mount();
    await state.emit("inactive");
    await state.emit("active");
    assert.equal(w.counters.get, 2);
  });

  it("repeated 'active' events and a repeated background do not refetch again", async () => {
    const state = appState(); const w = world();

    cleanups.push(withBridge(state));
    await w.mount();
    await state.emit("active");
    await state.emit("active");
    assert.equal(w.counters.get, 1, "already active: nothing changed");
    await state.emit("background");
    await state.emit("background");
    await state.emit("active");
    await state.emit("active");
    assert.equal(w.counters.get, 2, "exactly one return -> one refetch");
  });

  it("without the bridge nothing refetches (React Native has no focus events of its own)", async () => {
    const state = appState(); const w = world();

    await w.mount();
    await state.emit("background");
    await state.emit("active");
    assert.equal(w.counters.get, 1);
  });

  it("fresh data is left alone (staleness policy is respected)", async () => {
    const state = appState(); const w = world({ staleTime: 60_000 });

    cleanups.push(withBridge(state));
    await w.mount();
    await state.emit("background");
    await state.emit("active");
    assert.equal(w.counters.get, 1);
  });

  it("only mounted (active) queries are refetched: a left screen is not", async () => {
    const state = appState(); const w = world();

    cleanups.push(withBridge(state));
    const renderer = await w.mount();

    await act(async () => { renderer.unmount(); });
    await state.emit("background");
    await state.emit("active");
    assert.equal(w.counters.get, 1);
  });

  it("a read already in flight is not duplicated by the foreground", async () => {
    const state = appState(); const w = world({ holdGets: true });

    cleanups.push(withBridge(state));
    await w.mount();
    assert.equal(w.http.length, 1);
    await state.emit("background");
    await state.emit("active");
    assert.equal(w.http.length, 1, "still the single in-flight read");
    await w.releaseAll();
    assert.equal(w.current().query?.data?.owner, "user-a");
  });

  it("cleanup stops it: no listener remains and a return refetches nothing", async () => {
    const state = appState(); const w = world();
    const stop = withBridge(state);

    await w.mount();
    assert.equal(state.listeners.size, 1);
    stop();
    assert.equal(state.listeners.size, 0);
    await state.emit("background");
    await state.emit("active");
    assert.equal(w.counters.get, 1);
  });
});

describe("signed out", () => {
  it("returning to the app makes no request at all", async () => {
    const state = appState(); const w = world({ signedIn: false });

    cleanups.push(withBridge(state));
    await w.mount();
    await state.emit("background");
    await state.emit("active");
    assert.deepEqual(w.http, []);
  });

  it("after sign-out the old user's query is not refetched on return", async () => {
    const state = appState(); const w = world();

    cleanups.push(withBridge(state));
    await w.mount();
    await w.authEvent(null);
    const before = w.http.length;

    await state.emit("background");
    await state.emit("active");
    assert.equal(w.http.length, before);
  });
});

describe("session ownership across a foreground", () => {
  it("A in flight -> sign-out -> B: A's late answer never reaches B, and B's foreground uses B's token only", async () => {
    const state = appState(); const w = world({ holdGets: true });

    cleanups.push(withBridge(state));
    await w.mount();
    const first = w.held.splice(0);          // A's read, still in flight

    await w.authEvent(null);
    await w.authEvent(USER_B);
    assert.equal(w.current().owner, "user-b");
    const bRead = w.held.splice(0);

    await act(async () => { first.forEach((h) => h.release()); });   // A's late response
    await sleep();
    assert.equal(w.current().query?.data, undefined, "B has nothing from A");
    await act(async () => { bRead.forEach((h) => h.release()); });
    await sleep();
    assert.equal(w.current().query?.data?.owner, "user-b");

    w.flags.hold = false;
    const before = w.http.length;

    await state.emit("background");
    await state.emit("active");
    const after = w.http.slice(before);

    assert.ok(after.length >= 1);
    assert.ok(after.every((call) => call.user === "user-b"), "no request under A's identity after the rotation");
    assert.equal(w.current().query?.data?.owner, "user-b");
  });

  it("A -> B -> A is a fresh session each time and never shows another user's data", async () => {
    const state = appState(); const w = world();

    cleanups.push(withBridge(state));
    await w.mount();
    assert.equal(w.current().query?.data?.owner, "user-a");
    await w.authEvent(null);
    await w.authEvent(USER_B);
    assert.equal(w.current().query?.data?.owner, "user-b");
    await w.authEvent(null);
    await w.authEvent(USER_A);
    await state.emit("background");
    await state.emit("active");
    assert.equal(w.current().query?.data?.owner, "user-a");
    assert.equal(w.probes.length, 3, "three sessions, three fresh probes");
  });

  it("a same-user token refresh does not rotate, remount or start a refetch loop", async () => {
    const state = appState(); const w = world();

    cleanups.push(withBridge(state));
    await w.mount();
    const client = w.holder.get();
    const before = w.http.length;

    await w.authEvent(USER_A_SECOND);
    await sleep(40);
    assert.equal(w.holder.get(), client, "same client");
    assert.equal(w.probes.length, 1, "no remount");
    assert.equal(w.http.length, before, "no request caused by the token change");
    await state.emit("background");
    await state.emit("active");
    assert.equal(w.http.length, before + 1, "one refetch for the return, under the new token");
    assert.ok(w.http[w.http.length - 1].token.includes("a-token-2"));
  });

  it("a foreground during session invalidation reaches no retired client: zero requests", async () => {
    const state = appState(); const w = world({ unkeyed: true });

    cleanups.push(withBridge(state));
    await w.mount();
    const old = w.holder.get();
    const before = w.http.length;

    // The session is invalidated (boundary rotates the client) while the old
    // subtree is still mounted, and the app returns to the foreground.
    await act(async () => { w.boundary.applyAuthEvent(null, null); });
    await state.emit("background");
    await state.emit("active");
    assert.notEqual(w.holder.get(), old);
    assert.equal(w.http.length, before, "the retired client's queries are inert");
  });
});

describe("a Retry or refresh captured before the user changed", () => {
  it("sends nothing: the retired client is inert even when a new user's session is live", async () => {
    const state = appState(); const w = world({ unkeyed: true });

    cleanups.push(withBridge(state));
    await w.mount();
    const staleRetry = w.current().query;       // what a Retry button or pull handler holds
    const old = w.holder.get();

    await w.authEvent(USER_B);                  // the boundary adopts B: A's client is retired
    assert.notEqual(w.holder.get(), old);
    const before = w.http.length;

    await act(async () => { void staleRetry?.refetch(); });
    await sleep(40);
    // B's session is live, so a request here would go out under B's token for
    // a screen that belongs to A.
    assert.equal(w.http.length, before, "the stale Retry sent nothing");
    await state.emit("background");
    await state.emit("active");
    assert.equal(w.http.slice(before).filter((call) => call.method !== "GET").length, 0);
  });
});

describe("writes are never retried or started by the foreground", () => {
  it("a failed POST is sent once, and returning to the app does not resend it", async () => {
    const state = appState(); const w = world();

    cleanups.push(withBridge(state));
    await w.mount();
    w.flags.failPost = true;
    await act(async () => { w.current().mutate?.(); });
    await sleep(40);
    const posts = () => w.http.filter((call) => call.method === "POST").length;

    assert.equal(posts(), 1, "one network attempt per explicit submit");
    await state.emit("background");
    await state.emit("active");
    await sleep(40);
    assert.equal(posts(), 1);
    assert.equal(w.mutationRuns.count, 1);
  });

  it("returning to the app starts no mutation and sends no write", async () => {
    const state = appState(); const w = world();

    cleanups.push(withBridge(state));
    await w.mount();
    for (let i = 0; i < 3; i += 1) {
      await state.emit("background");
      await state.emit("active");
    }

    assert.equal(w.mutationRuns.count, 0);
    assert.ok(w.http.every((call) => call.method === "GET"));
  });
});

describe("the rules evaluation keeps exactly one path", () => {
  const result: RuleEvaluationResult = {
    processed: 0, deferred: 0, failed_retryable: 0, dead: 0, blocked: false, outcomes: {},
    alerts_available: true, alerts_created: 0, alerts_resolved: 0, alerts_failed: false,
  };

  async function run(withFocusBridge: boolean) {
    const state = appState();
    const w = world();
    const evaluations: number[] = [];

    if (withFocusBridge) cleanups.push(withBridge(state));

    const scope = (children: ReactNode) =>
      createElement(SessionScope, { holder: w.holder },
        createElement(RulesEvaluationProvider, {
          userId: "user-a",
          isCurrentClient: w.holder.isCurrent,
          evaluate: async () => { evaluations.push(evaluations.length + 1); return result; },
          subscribeAppState: state.subscribe,
          getAppState: state.get,
          timing: { debounceMs: 1, cooldownMs: 0 },
        }, children));

    await w.mount(scope);
    await sleep(30);
    await state.emit("background");
    await state.emit("active");
    await sleep(30);
    await state.emit("active");
    await state.emit("active");
    await sleep(30);

    return { evaluations: evaluations.length, gets: w.counters.get };
  }

  it("the focus bridge adds no evaluation: the count equals the count without it", async () => {
    const without = await run(false);
    const withBridge = await run(true);

    assert.equal(withBridge.evaluations, without.evaluations);
    assert.ok(without.evaluations >= 1);
    assert.equal(without.gets, 1, "no focus bridge, no foreground refetch");
    assert.equal(withBridge.gets, 2, "the bridge adds only the read refetch");
  });

  it("repeated active events do not trigger further evaluations", async () => {
    const one = await run(true);

    assert.equal(one.evaluations, 2, "session-ready plus exactly one foreground");
  });
});


describe("paged lists keep their pages on return", () => {
  it("the history re-reads every loaded page, in order, with GETs only", async () => {
    const state = appState();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const requested: number[] = [];
    const seen: { value: ReturnType<typeof useExecutionHistory> | null } = { value: null };

    function Probe(): null {
      const result = useExecutionHistory({
        userId: "user-a",
        filters: { ruleId: null, status: null },
        listExecutions: async (filters) => {
          requested.push(filters.offset ?? -1);

          return page(ids(20, filters.offset ?? 0), 45, filters.offset ?? 0);
        },
      });

      void [result.feed.isError, result.feed.hasNextPage, result.feed.isFetchingNextPage, result.feed.isRefetching];
      seen.value = result;

      return null;
    }

    cleanups.push(withBridge(state));
    await act(async () => { TestRenderer.create(createElement(QueryClientProvider, { client }, createElement(Probe))); });
    await sleep();
    await act(async () => { void seen.value?.feed.fetchNextPage(); });
    await sleep();
    assert.deepEqual(requested, [0, 20]);
    assert.equal(seen.value?.merged?.items.length, 40);

    await state.emit("background");
    await state.emit("active");
    await sleep(40);
    assert.deepEqual(requested, [0, 20, 0, 20], "both pages re-read, first page first");
    assert.equal(seen.value?.merged?.items.length, 40, "no page was dropped");
    await state.emit("active");
    assert.equal(requested.length, 4, "a repeated 'active' adds nothing");
  });
});

describe("the Inbox indicator after a failed refresh", () => {
  const input = (proposalsStale: boolean) => ({
    proposals: sourceStateFromQuery({
      isError: proposalsStale, isSuccess: !proposalsStale,
      // Stale rows left over from before the failed refresh.
      data: { items: [{ status: "awaiting_confirmation", expires_at: "2099-01-01T00:00:00Z" }] as never[], total: 1, complete: true, pagesFetched: 1, available: true },
    }),
    alerts: { status: "success" as const, items: [], complete: true, available: true },
    evaluation: "succeeded" as const,
    now: 1_000,
  });

  it("a failed refresh does not let stale rows decide: unknown, never a false 'clear' or 'attention'", () => {
    assert.equal(deriveInboxIndicator(input(true)), "unknown");
  });

  it("the same rows from a successful read still mean 'attention'", () => {
    assert.equal(deriveInboxIndicator(input(false)), "attention");
  });
});
