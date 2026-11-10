// MF-4: the password-recovery state and the root route decision. Pure.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { createRecoveryState, decideRootRoute } from "./recovery-state.ts";

describe("recovery state", () => {
  it("idle -> verifying -> active -> idle", () => {
    const state = createRecoveryState();
    const attempt = state.begin();

    assert.deepEqual(state.getSnapshot(), { phase: "verifying" });
    assert.equal(state.activate(attempt, "user-a"), true);
    assert.deepEqual(state.getSnapshot(), { phase: "active", userId: "user-a" });
    state.complete("user-a");
    assert.deepEqual(state.getSnapshot(), { phase: "idle" });
  });

  it("only the newest attempt may activate or finish", () => {
    const state = createRecoveryState();
    const older = state.begin();
    const newer = state.begin();

    assert.equal(state.isCurrent(older), false);
    assert.equal(state.activate(older, "user-a"), false);
    state.finish(older);
    assert.deepEqual(state.getSnapshot(), { phase: "verifying" }, "a stale finish changes nothing");
    assert.equal(state.activate(newer, "user-b"), true);
    assert.deepEqual(state.getSnapshot(), { phase: "active", userId: "user-b" });
  });

  it("a late activation after the attempt finished is refused", () => {
    const state = createRecoveryState();
    const attempt = state.begin();

    state.finish(attempt);
    assert.equal(state.activate(attempt, "user-a"), false);
    assert.deepEqual(state.getSnapshot(), { phase: "idle" });
  });

  it("a new attempt closes the gate while it runs, and a failed attempt restores the earlier recovery", () => {
    const state = createRecoveryState();

    state.activate(state.begin(), "user-a");

    const attempt = state.begin();

    assert.deepEqual(state.getSnapshot(), { phase: "verifying" });
    state.finish(attempt);
    assert.deepEqual(state.getSnapshot(), { phase: "active", userId: "user-a" });
  });

  it("a successful newer attempt replaces the earlier recovery", () => {
    const state = createRecoveryState();

    state.activate(state.begin(), "user-a");
    assert.equal(state.activate(state.begin(), "user-b"), true);
    assert.deepEqual(state.getSnapshot(), { phase: "active", userId: "user-b" });
  });

  it("keepRecovery: a superseded recovery session stays gated, whichever way the newer attempt ends", () => {
    const state = createRecoveryState();
    const older = state.begin();
    const newer = state.begin();

    state.keepRecovery("user-a"); // the older attempt's session arrived while the newer runs
    state.finish(newer);
    assert.deepEqual(state.getSnapshot(), { phase: "active", userId: "user-a" });
    assert.equal(state.activate(older, "user-a"), false);

    const idle = createRecoveryState();

    idle.finish(idle.begin());
    idle.keepRecovery("user-a"); // arrives after the newer attempt already finished
    assert.deepEqual(idle.getSnapshot(), { phase: "active", userId: "user-a" });
  });

  it("a remembered recovery is dropped when another user takes over, and completes with the password", () => {
    const state = createRecoveryState();

    state.activate(state.begin(), "user-a");

    const attempt = state.begin();

    state.reconcile("user-b");
    state.finish(attempt);
    assert.equal(state.getSnapshot().phase, "idle");

    state.activate(state.begin(), "user-a");

    const again = state.begin();

    state.complete("user-a"); // password changed while another link was being verified
    state.finish(again);
    assert.equal(state.getSnapshot().phase, "idle");
  });

  it("belongs to one user: another user, or nobody, ends it; the same user does not", () => {
    const state = createRecoveryState();

    state.activate(state.begin(), "user-a");
    state.reconcile("user-a");
    assert.equal(state.getSnapshot().phase, "active");
    state.reconcile("user-b");
    assert.equal(state.getSnapshot().phase, "idle");

    state.activate(state.begin(), "user-a");
    state.reconcile(null);
    assert.equal(state.getSnapshot().phase, "idle");
  });

  it("reconcile never ends a verifying attempt (the session it produces is not here yet)", () => {
    const state = createRecoveryState();

    state.begin();
    state.reconcile(null);
    assert.equal(state.getSnapshot().phase, "verifying");
  });

  it("complete only ends the recovery of the same user", () => {
    const state = createRecoveryState();

    state.activate(state.begin(), "user-a");
    state.complete("user-b");
    assert.equal(state.getSnapshot().phase, "active");
  });

  it("notifies subscribers only on a change and keeps the snapshot reference stable otherwise", () => {
    const state = createRecoveryState();
    let calls = 0;
    const unsubscribe = state.subscribe(() => { calls += 1; });
    const first = state.getSnapshot();

    state.reconcile("x");
    state.finish(0);
    assert.equal(calls, 0);
    assert.equal(state.getSnapshot(), first);
    state.begin();
    assert.equal(calls, 1);
    unsubscribe();
    state.begin();
    assert.equal(calls, 1);
  });
});

describe("root route decision (protected routes)", () => {
  const idle = { phase: "idle" } as const;

  it("loading while auth initializes or a link is being verified", () => {
    assert.equal(decideRootRoute({ isLoading: true, userId: null, recovery: idle }), "loading");
    assert.equal(decideRootRoute({ isLoading: false, userId: "a", recovery: { phase: "verifying" } }), "loading");
    assert.equal(decideRootRoute({ isLoading: false, userId: null, recovery: { phase: "verifying" } }), "loading");
  });

  it("signed out, app and recovery", () => {
    assert.equal(decideRootRoute({ isLoading: false, userId: null, recovery: idle }), "signed-out");
    assert.equal(decideRootRoute({ isLoading: false, userId: "a", recovery: idle }), "app");
    assert.equal(decideRootRoute({ isLoading: false, userId: "a", recovery: { phase: "active", userId: "a" } }), "recovery");
  });

  it("a recovery of another user never turns this session into a recovery", () => {
    assert.equal(decideRootRoute({ isLoading: false, userId: "b", recovery: { phase: "active", userId: "a" } }), "app");
  });

  it("an active recovery with nobody signed in is signed out", () => {
    assert.equal(decideRootRoute({ isLoading: false, userId: null, recovery: { phase: "active", userId: "a" } }), "signed-out");
  });
});
