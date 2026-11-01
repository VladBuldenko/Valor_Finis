// VF-020F4: the single evaluation host, mounted with the real TanStack hooks
// and the real SessionScope / SessionQueryClient.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { QueryClient } from "@tanstack/react-query";
import { createElement, type ReactElement } from "react";
import TestRenderer from "react-test-renderer";

import { act } from "../../lib/mounted-test-support.ts";
import { SessionQueryClient } from "../../lib/session-query-client.ts";
import { SessionScope } from "../../lib/session-scope.ts";
import { financialRuleKeys } from "./financial-rule-query-keys.ts";
import { RulesEvaluationProvider, useRulesEvaluation, type RulesEvaluationContextValue } from "./rules-evaluation-provider.ts";
import type { RuleEvaluationResult } from "./financial-rule.types.ts";

const result = (over: Partial<RuleEvaluationResult> = {}): RuleEvaluationResult => ({
  processed: 0, deferred: 0, failed_retryable: 0, dead: 0, blocked: false, outcomes: {},
  alerts_available: true, alerts_created: 0, alerts_resolved: 0, alerts_failed: false, ...over,
});

const sleep = (ms: number) => act(async () => { await new Promise((resolve) => setTimeout(resolve, ms)); });

function world() {
  const holder = new SessionQueryClient();
  const listeners = new Set<(state: string) => void>();
  const subscribed = { total: 0 };
  const calls: { user: string }[] = [];
  const signals: AbortSignal[] = [];
  const gates: { resolve: (value: RuleEvaluationResult) => void; reject: (error: unknown) => void }[] = [];
  const seen: { value: RulesEvaluationContextValue | null } = { value: null };
  let currentUser: string | null = "user-a";
  const state = { app: "active" };

  const subscribeAppState = (listener: (next: string) => void) => {
    listeners.add(listener);
    subscribed.total += 1;

    return () => { listeners.delete(listener); };
  };
  const evaluate = (signal: AbortSignal) => {
    signals.push(signal);
    calls.push({ user: currentUser ?? "none" });

    return new Promise<RuleEvaluationResult>((resolve, reject) => { gates.push({ resolve, reject }); });
  };
  const getAppState = () => state.app;

  function Probe(): null {
    seen.value = useRulesEvaluation();

    return null;
  }

  // debounceMs lets a test hold a session's own session-ready evaluation back
  // (a very large value) or let it start promptly, instead of racing a timer.
  const tree = (userId: string | null, debounceMs = 5): ReactElement =>
    createElement(SessionScope, { holder },
      createElement(RulesEvaluationProvider, {
        userId, isCurrentClient: holder.isCurrent, evaluate, subscribeAppState, getAppState,
        timing: { debounceMs, cooldownMs: 200 },
      }, createElement(Probe)));

  return {
    holder, listeners, subscribed, calls, signals, gates, seen, state, tree,
    setUser: (user: string | null) => { currentUser = user; },
    emit: (next: string) => { state.app = next; listeners.forEach((listener) => listener(next)); },
  };
}

async function waitFor(condition: () => boolean): Promise<void> {
  for (let i = 0; i < 200 && !condition(); i += 1) {
    await sleep(10);
  }
  assert.ok(condition(), "condition was not reached");
}

async function mount(w: ReturnType<typeof world>, user: string | null) {
  let renderer!: TestRenderer.ReactTestRenderer;

  await act(async () => { renderer = TestRenderer.create(w.tree(user)); });

  return renderer;
}

describe("one host per authenticated session", () => {
  it("session ready triggers exactly one evaluation; one AppState listener exists", async () => {
    const w = world();
    const renderer = await mount(w, "user-a");

    assert.equal(w.listeners.size, 1);
    await sleep(30);
    assert.equal(w.calls.length, 1);
    assert.equal(w.seen.value?.status, "pending");
    await act(async () => { w.gates[0].resolve(result()); });
    assert.equal(w.seen.value?.status, "succeeded");
    await act(async () => { renderer.unmount(); });
    assert.equal(w.listeners.size, 0, "listener removed on unmount");
  });

  it("unmounting disposes the trigger: a pending request never fires and a running one is aborted (no rotation needed)", async () => {
    const early = world();
    const first = await mount(early, "user-a");

    await act(async () => { first.unmount(); });
    await sleep(30);
    assert.equal(early.calls.length, 0, "the pending debounce was cancelled");

    const running = world();
    const second = await mount(running, "user-a");

    await sleep(30);
    assert.equal(running.signals[0].aborted, false);
    await act(async () => { second.unmount(); });
    assert.equal(running.signals[0].aborted, true, "the in-flight request is aborted");
  });

  it("a signed-out host creates no trigger, listener or request", async () => {
    const w = world();

    await mount(w, null);
    assert.equal(w.listeners.size, 0);
    assert.equal(w.seen.value?.request("inbox_open"), "ignored_signed_out");
    await sleep(30);
    assert.equal(w.calls.length, 0);
    assert.equal(w.seen.value?.status, "not_attempted");
  });

  it("re-rendering the same session does not create a second trigger or listener", async () => {
    const w = world();
    const renderer = await mount(w, "user-a");

    for (let i = 0; i < 4; i += 1) {
      await act(async () => { renderer.update(w.tree("user-a")); });
    }

    assert.equal(w.listeners.size, 1);
    assert.equal(w.subscribed.total, 1);
  });
});

describe("deduplication across the three sources", () => {
  it("session-ready + foreground + Inbox open within the debounce window -> one request", async () => {
    const w = world();

    await mount(w, "user-a");
    assert.equal(w.seen.value?.request("inbox_open"), "coalesced");
    await act(async () => { w.emit("background"); w.emit("active"); });
    await sleep(30);
    assert.equal(w.calls.length, 1);
  });

  it("Inbox open and foreground after a run respect the cooldown; income does not", async () => {
    const w = world();

    await mount(w, "user-a");
    await sleep(30);
    await act(async () => { w.gates[0].resolve(result()); });
    assert.equal(w.seen.value?.request("inbox_open"), "ignored_cooldown");
    await act(async () => { w.emit("background"); w.emit("active"); });
    await sleep(30);
    assert.equal(w.calls.length, 1);
    assert.equal(w.seen.value?.request("income_recorded"), "scheduled");
    await sleep(30);
    assert.equal(w.calls.length, 2);
  });

  it("income recorded during a run schedules exactly one trailing evaluation", async () => {
    const w = world();

    await mount(w, "user-a");
    await sleep(30);
    assert.equal(w.seen.value?.request("income_recorded"), "coalesced");
    assert.equal(w.seen.value?.request("income_recorded"), "coalesced");
    await act(async () => { w.gates[0].resolve(result()); });
    await sleep(30);
    assert.equal(w.calls.length, 2);
    await act(async () => { w.gates[1].resolve(result()); });
    await sleep(30);
    assert.equal(w.calls.length, 2, "no further trailing run");
  });
});

describe("session rotation, sign-out and stale responses", () => {
  it("rotation disposes the old trigger and listener; the new session gets its own", async () => {
    const w = world();
    const renderer = await mount(w, "user-a");

    await sleep(30);
    assert.equal(w.listeners.size, 1);
    w.holder.rotate();
    w.setUser("user-b");
    await act(async () => { renderer.update(w.tree("user-b")); });
    assert.equal(w.listeners.size, 1, "exactly one listener after rotation");
    assert.equal(w.subscribed.total, 2);
    await sleep(30);
    assert.deepEqual(w.calls.map((call) => call.user), ["user-a", "user-b"]);
    assert.equal(w.seen.value?.status, "pending");
  });

  it("A's late answer after sign-out touches nothing of B's: no status, no invalidation, no extra POST", async () => {
    const w = world();
    const renderer = await mount(w, "user-a");

    await waitFor(() => w.calls.length === 1);

    const oldClient: QueryClient = w.holder.get();

    w.holder.rotate();
    w.setUser(null);
    await act(async () => { renderer.update(w.tree(null)); });
    assert.equal(w.signals[0].aborted, true, "sign-out aborted A's request");
    assert.equal(w.listeners.size, 0);
    w.setUser("user-b");
    w.holder.rotate();
    // B's own session-ready evaluation is held back (huge debounce), so B has
    // deterministically not started anything when A's answer arrives.
    await act(async () => { renderer.update(w.tree("user-b", 600_000)); });

    const next = w.holder.get();

    next.setQueryData(financialRuleKeys.proposalList("user-b"), {});
    next.setQueryData(financialRuleKeys.proposalList("user-a"), {});
    oldClient.setQueryData(financialRuleKeys.proposalList("user-a"), {});
    await act(async () => { w.gates[0].resolve(result({ processed: 3, outcomes: { executed: 1 } })); });
    assert.equal(next.getQueryState(financialRuleKeys.proposalList("user-b"))?.isInvalidated, false);
    assert.equal(next.getQueryState(financialRuleKeys.proposalList("user-a"))?.isInvalidated, false);
    assert.equal(oldClient.getQueryState(financialRuleKeys.proposalList("user-a"))?.isInvalidated, false, "the stale answer did not even invalidate the old client");
    assert.equal(w.seen.value?.status, "not_attempted", "user A's answer set no status for user B");
    assert.equal(w.calls.length, 1, "no POST was made for B yet, and none was duplicated");
    await act(async () => { renderer.unmount(); });
  });

  it("B enters pending on its own and completes independently of A's late answer", async () => {
    const w = world();
    const renderer = await mount(w, "user-a");

    await waitFor(() => w.calls.length === 1);
    w.holder.rotate();
    w.setUser("user-b");
    await act(async () => { renderer.update(w.tree("user-b")); });
    // Wait for B's own request instead of assuming how fast its timer fires.
    await waitFor(() => w.calls.length === 2);
    assert.deepEqual(w.calls.map((call) => call.user), ["user-a", "user-b"]);
    assert.equal(w.signals[0].aborted, true, "A's trigger was disposed");
    assert.equal(w.seen.value?.status, "pending");

    const next = w.holder.get();

    next.setQueryData(financialRuleKeys.proposalList("user-b"), {});
    await act(async () => { w.gates[0].resolve(result({ processed: 3 })); });
    assert.equal(w.seen.value?.status, "pending", "A's answer did not complete B");
    assert.equal(next.getQueryState(financialRuleKeys.proposalList("user-b"))?.isInvalidated, false);
    await act(async () => { w.gates[1].resolve(result({ processed: 1 })); });
    assert.equal(w.seen.value?.status, "succeeded");
    assert.equal(next.getQueryState(financialRuleKeys.proposalList("user-b"))?.isInvalidated, true, "B's own result invalidates B's cache");
    await sleep(60);
    assert.equal(w.calls.length, 2, "no duplicate evaluation POST");
    assert.equal(w.listeners.size, 1);
  });

  it("sign-out disposes everything and the next user starts with no recorded status", async () => {
    const w = world();
    const renderer = await mount(w, "user-a");

    await sleep(30);
    await act(async () => { w.gates[0].resolve(result()); });
    assert.equal(w.seen.value?.status, "succeeded");
    await act(async () => { renderer.update(w.tree(null)); });
    assert.equal(w.listeners.size, 0);
    assert.equal(w.seen.value?.status, "not_attempted");
  });
});

describe("results and failures", () => {
  it("a current result with changes invalidates the evaluated set for this user only", async () => {
    const w = world();

    await mount(w, "user-a");
    w.holder.get().setQueryData(financialRuleKeys.proposalList("user-a"), {});
    w.holder.get().setQueryData(financialRuleKeys.ruleList("user-a"), []);
    await sleep(30);
    await act(async () => { w.gates[0].resolve(result({ processed: 1 })); });
    assert.equal(w.holder.get().getQueryState(financialRuleKeys.proposalList("user-a"))?.isInvalidated, true);
    assert.equal(w.holder.get().getQueryState(financialRuleKeys.ruleList("user-a"))?.isInvalidated, false);
  });

  it("an evaluation that processed nothing invalidates nothing", async () => {
    const w = world();

    await mount(w, "user-a");
    w.holder.get().setQueryData(financialRuleKeys.proposalList("user-a"), {});
    await sleep(30);
    await act(async () => { w.gates[0].resolve(result()); });
    assert.equal(w.holder.get().getQueryState(financialRuleKeys.proposalList("user-a"))?.isInvalidated, false);
  });

  it("a failed request is 'failed', never 'succeeded', and is not retried", async () => {
    const w = world();

    await mount(w, "user-a");
    await sleep(30);
    await act(async () => { w.gates[0].reject(new Error("network")); });
    assert.equal(w.seen.value?.status, "failed");
    await sleep(60);
    assert.equal(w.calls.length, 1);
  });

  it("a blocked or partly failed drain is 'incomplete', not a clean success", async () => {
    for (const over of [{ blocked: true }, { dead: 1 }, { failed_retryable: 1 }, { alerts_failed: true }]) {
      const w = world();

      await mount(w, "user-a");
      await sleep(30);
      await act(async () => { w.gates[0].resolve(result(over)); });
      assert.equal(w.seen.value?.status, "incomplete", JSON.stringify(over));
    }
  });
});
