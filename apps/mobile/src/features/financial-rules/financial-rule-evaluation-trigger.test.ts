import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { QueryClient } from "@tanstack/react-query";

import {
  createEvaluationTrigger,
  createRulesEvaluationTrigger,
  watchForeground,
  type CancelTimer,
  type EvaluationTriggerDeps,
} from "./financial-rule-evaluation-trigger.ts";
import { financialRuleKeys } from "./financial-rule-query-keys.ts";
import type { RuleEvaluationResult } from "./financial-rule.types.ts";

const result = (over: Partial<RuleEvaluationResult> = {}): RuleEvaluationResult => ({
  processed: 0, deferred: 0, failed_retryable: 0, dead: 0, blocked: false, outcomes: {},
  alerts_available: true, alerts_created: 0, alerts_resolved: 0, alerts_failed: false, ...over,
});

// Manual clock and timers: nothing runs until the test says so.
function clock() {
  let time = 1_000_000;
  const timers: { at: number; run: () => void; live: boolean }[] = [];

  return {
    now: () => time,
    setTimer: (run: () => void, ms: number): CancelTimer => {
      const timer = { at: time + ms, run, live: true };

      timers.push(timer);

      return () => { timer.live = false; };
    },
    advance(ms: number) {
      time += ms;

      for (const timer of timers) {
        if (timer.live && timer.at <= time) {
          timer.live = false;
          timer.run();
        }
      }
    },
    pending: () => timers.filter((timer) => timer.live).length,
  };
}

function gate<T>() {
  let resolve: (value: T) => void = () => undefined;
  let reject: (error: unknown) => void = () => undefined;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });

  return { promise, resolve, reject };
}

const tick = () => new Promise<void>((done) => setImmediate(done));

function setup(over: Partial<EvaluationTriggerDeps> = {}) {
  const time = clock();
  const calls: AbortSignal[] = [];
  const results: [RuleEvaluationResult, string][] = [];
  const errors: unknown[] = [];
  let current = true;
  const gates: ReturnType<typeof gate<RuleEvaluationResult>>[] = [];
  const trigger = createEvaluationTrigger({
    userId: "user-a",
    isCurrent: () => current,
    evaluate: (signal) => {
      calls.push(signal);
      const g = gate<RuleEvaluationResult>();

      gates.push(g);

      return g.promise;
    },
    onResult: (value, userId) => { results.push([value, userId]); },
    onError: (error) => { errors.push(error); },
    debounceMs: 750,
    cooldownMs: 30_000,
    now: time.now,
    setTimer: time.setTimer,
    ...over,
  });

  return { trigger, time, calls, results, errors, gates, setCurrent: (value: boolean) => { current = value; } };
}

describe("debounce and dedupe", () => {
  it("collapses a burst into one request after the debounce window", async () => {
    const t = setup();

    assert.equal(t.trigger.request("foreground"), "scheduled");
    assert.equal(t.trigger.request("inbox_open"), "coalesced");
    assert.equal(t.trigger.request("foreground"), "coalesced");
    assert.equal(t.calls.length, 0);
    t.time.advance(749);
    assert.equal(t.calls.length, 0);
    t.time.advance(1);
    assert.equal(t.calls.length, 1);
  });

  it("never runs two evaluations at once", async () => {
    const t = setup();

    t.trigger.request("foreground");
    t.time.advance(750);
    assert.equal(t.trigger.request("inbox_open"), "coalesced");
    t.time.advance(60_000);
    assert.equal(t.calls.length, 1);
    t.gates[0].resolve(result());
    await tick();
    assert.equal(t.calls.length, 1);
  });

  it("income recorded during a run earns exactly one trailing run", async () => {
    const t = setup();

    t.trigger.request("foreground");
    t.time.advance(750);
    assert.equal(t.trigger.request("income_recorded"), "coalesced");
    assert.equal(t.trigger.request("income_recorded"), "coalesced");
    assert.equal(t.trigger.getState().trailing, true);
    t.gates[0].resolve(result());
    await tick();
    assert.equal(t.trigger.getState().scheduled, true);
    t.time.advance(750);
    assert.equal(t.calls.length, 2);
    t.gates[1].resolve(result());
    await tick();
    t.time.advance(60_000);
    assert.equal(t.calls.length, 2, "the trailing run does not loop");
    assert.equal(t.time.pending(), 0);
  });

  it("foreground and inbox_open respect the cooldown; income_recorded does not", async () => {
    const t = setup();

    t.trigger.request("foreground");
    t.time.advance(750);
    t.gates[0].resolve(result());
    await tick();
    t.time.advance(10_000);
    assert.equal(t.trigger.request("foreground"), "ignored_cooldown");
    assert.equal(t.trigger.request("inbox_open"), "ignored_cooldown");
    assert.equal(t.trigger.request("income_recorded"), "scheduled");
    t.time.advance(750);
    assert.equal(t.calls.length, 2);
    t.gates[1].resolve(result());
    await tick();
    t.time.advance(30_000);
    assert.equal(t.trigger.request("foreground"), "scheduled");
  });
});

describe("session ownership", () => {
  it("a signed-out trigger never sends anything", () => {
    const t = setup({ userId: null });

    for (const reason of ["foreground", "inbox_open", "income_recorded"] as const) {
      assert.equal(t.trigger.request(reason), "ignored_signed_out");
    }

    t.time.advance(120_000);
    assert.equal(t.calls.length, 0);
    assert.equal(t.time.pending(), 0);
  });

  it("a stale session (client rotated) is ignored", () => {
    const t = setup();

    t.setCurrent(false);
    assert.equal(t.trigger.request("foreground"), "ignored_signed_out");
  });

  it("the session ending before the debounce fires cancels the request", () => {
    const t = setup();

    t.trigger.request("foreground");
    t.setCurrent(false);
    t.time.advance(750);
    assert.equal(t.calls.length, 0);
  });

  it("a result arriving after the session changed updates nothing", async () => {
    const t = setup();

    t.trigger.request("foreground");
    t.time.advance(750);
    t.setCurrent(false);
    t.gates[0].resolve(result({ processed: 3 }));
    await tick();
    assert.equal(t.results.length, 0);
    assert.equal(t.trigger.getState().running, false);
  });

  it("dispose cancels the timer, aborts the request and ignores later calls", async () => {
    const t = setup();

    t.trigger.request("foreground");
    t.trigger.dispose();
    assert.equal(t.time.pending(), 0);
    assert.equal(t.trigger.request("foreground"), "disposed");

    const running = setup();

    running.trigger.request("foreground");
    running.time.advance(750);
    running.trigger.dispose();
    assert.equal(running.calls[0].aborted, true);
    running.gates[0].resolve(result({ processed: 1 }));
    await tick();
    assert.equal(running.results.length, 0);
    running.time.advance(120_000);
    assert.equal(running.calls.length, 1);
  });

  it("the result is delivered together with the user it belongs to", async () => {
    const t = setup();

    t.trigger.request("foreground");
    t.time.advance(750);
    t.gates[0].resolve(result({ processed: 1 }));
    await tick();
    assert.deepEqual(t.results.map(([, user]) => user), ["user-a"]);
  });
});

describe("failures are never retried", () => {
  it("an error is reported once and the trigger can be used again after the cooldown", async () => {
    const t = setup();

    t.trigger.request("foreground");
    t.time.advance(750);
    t.gates[0].reject(new Error("network"));
    await tick();
    assert.equal(t.errors.length, 1);
    t.time.advance(120_000);
    assert.equal(t.calls.length, 1, "no automatic retry");
    assert.equal(t.trigger.request("foreground"), "scheduled");
    t.time.advance(750);
    assert.equal(t.calls.length, 2);
  });

  it("a failure during a trailing request does not loop", async () => {
    const t = setup();

    t.trigger.request("foreground");
    t.time.advance(750);
    t.trigger.request("income_recorded");
    t.gates[0].reject(new Error("boom"));
    await tick();
    t.time.advance(750);
    assert.equal(t.calls.length, 2);
    t.gates[1].reject(new Error("boom"));
    await tick();
    t.time.advance(120_000);
    assert.equal(t.calls.length, 2);
  });
});

describe("foreground watcher", () => {
  function fakeAppState() {
    const listeners = new Set<(state: string) => void>();

    return {
      subscribe: (listener: (state: string) => void) => {
        listeners.add(listener);

        return () => { listeners.delete(listener); };
      },
      emit: (state: string) => listeners.forEach((listener) => listener(state)),
      count: () => listeners.size,
    };
  }

  it("requests only when the app becomes active from background or inactive", () => {
    const app = fakeAppState();
    const reasons: string[] = [];

    watchForeground(app.subscribe, { request: (reason) => { reasons.push(reason); return "scheduled"; } });
    app.emit("active");
    app.emit("inactive");
    app.emit("active");
    app.emit("background");
    app.emit("background");
    app.emit("active");
    assert.deepEqual(reasons, ["foreground", "foreground"]);
  });

  it("starting in the background waits for the first activation", () => {
    const app = fakeAppState();
    const reasons: string[] = [];

    watchForeground(app.subscribe, { request: (reason) => { reasons.push(reason); return "scheduled"; } }, "background");
    app.emit("active");
    assert.deepEqual(reasons, ["foreground"]);
  });

  it("unsubscribes cleanly", () => {
    const app = fakeAppState();
    const stop = watchForeground(app.subscribe, { request: () => "scheduled" });

    assert.equal(app.count(), 1);
    stop();
    assert.equal(app.count(), 0);
  });

  it("repeated foregrounding through the real trigger sends one request per cooldown", async () => {
    const t = setup();
    const app = fakeAppState();

    watchForeground(app.subscribe, t.trigger, "background");

    for (let i = 0; i < 5; i += 1) {
      app.emit("active");
      app.emit("background");
    }

    t.time.advance(750);
    assert.equal(t.calls.length, 1);
  });
});

describe("wired to the cache", () => {
  it("a current result invalidates exactly the evaluated set for that user", async () => {
    const client = new QueryClient();
    const time = clock();
    const outcome = gate<RuleEvaluationResult>();

    client.setQueryData(financialRuleKeys.proposalList("user-a"), {});
    client.setQueryData(financialRuleKeys.ruleList("user-a"), []);
    client.setQueryData(financialRuleKeys.proposalList("user-b"), {});

    const trigger = createRulesEvaluationTrigger({
      userId: "user-a",
      queryClient: client,
      isCurrent: () => true,
      evaluate: () => outcome.promise,
      now: time.now,
      setTimer: time.setTimer,
    });

    trigger.request("inbox_open");
    time.advance(750);
    outcome.resolve(result({ processed: 1 }));
    await tick();
    await tick();
    assert.equal(client.getQueryState(financialRuleKeys.proposalList("user-a"))?.isInvalidated, true);
    assert.equal(client.getQueryState(financialRuleKeys.ruleList("user-a"))?.isInvalidated, false);
    assert.equal(client.getQueryState(financialRuleKeys.proposalList("user-b"))?.isInvalidated, false);
  });
});
