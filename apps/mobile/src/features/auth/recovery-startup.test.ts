// MF-4 restart safety: what startup does about a recovery that was in progress when
// the process ended. Fakes only; the real-auth-js restarts are in
// auth-recovery-integration.test.ts.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { createRecoveryPersistence, type MarkerRead, type RecoveryMarker } from "./recovery-persistence.ts";
import { createRecoveryState } from "./recovery-state.ts";
import { bindRecoveryPersistence, createStartupResolver, decideStartupAction, resolveRecoveryAtStartup } from "./recovery-startup.ts";
import { memoryStorage } from "./recovery-test-support.ts";

const active = (userId: string): MarkerRead => ({ kind: "marker", marker: { v: 1, phase: "active", userId } });
const verifying = (priorUserId: string | null, recoveryUserId: string | null): MarkerRead => ({
  kind: "marker",
  marker: { v: 1, phase: "verifying", priorUserId, recoveryUserId } as RecoveryMarker,
});

describe("decideStartupAction", () => {
  it("no marker: nothing to do, whatever the session", () => {
    assert.deepEqual(decideStartupAction({ kind: "none" }, null), { kind: "none" });
    assert.deepEqual(decideStartupAction({ kind: "none" }, "u-1"), { kind: "none" });
  });

  it("active marker: resumed only for the same restored user, otherwise the record is stale", () => {
    assert.deepEqual(decideStartupAction(active("u-1"), "u-1"), { kind: "resume", userId: "u-1" });
    assert.deepEqual(decideStartupAction(active("u-1"), null), { kind: "clear" });
    assert.deepEqual(decideStartupAction(active("u-1"), "u-2"), { kind: "clear" });
  });

  it("verifying marker: no session clears; the recovery's own user resumes; the unchanged prior user is kept", () => {
    assert.deepEqual(decideStartupAction(verifying(null, null), null), { kind: "clear" });
    assert.deepEqual(decideStartupAction(verifying("a", "r"), "r"), { kind: "resume", userId: "r" });
    assert.deepEqual(decideStartupAction(verifying("a", null), "a"), { kind: "clear" });
  });

  it("verifying marker with a session nobody can explain: end it (fail closed)", () => {
    assert.deepEqual(decideStartupAction(verifying(null, null), "x"), { kind: "end_session" });
    assert.deepEqual(decideStartupAction(verifying("a", null), "x"), { kind: "end_session" });
    assert.deepEqual(decideStartupAction(verifying("a", "r"), "x"), { kind: "end_session" });
  });

  it("a restore that FAILED is not 'no session': keep any record and judge again later", () => {
    for (const read of [active("u-1"), verifying(null, null), { kind: "unreadable" } as MarkerRead]) {
      assert.deepEqual(decideStartupAction(read, null, true), { kind: "defer" });
    }

    assert.deepEqual(decideStartupAction({ kind: "none" }, null, true), { kind: "none" });
    assert.deepEqual(decideStartupAction(active("u-1"), "u-1", true), { kind: "resume", userId: "u-1" }, "with a session the failure flag is irrelevant");
  });

  it("unreadable marker: end any session, clear when there is none", () => {
    assert.deepEqual(decideStartupAction({ kind: "unreadable" }, null), { kind: "clear" });
    assert.deepEqual(decideStartupAction({ kind: "unreadable" }, "u-1"), { kind: "end_session" });
  });
});

function setup(options: { marker?: RecoveryMarker | string; current?: string | null; end?: (userId: string) => Promise<"signed-out" | "stale"> } = {}) {
  const m = memoryStorage();

  if (options.marker !== undefined) {
    m.data.set("valorfinis.password-recovery.v1", typeof options.marker === "string" ? options.marker : JSON.stringify(options.marker));
  }

  const persistence = createRecoveryPersistence(m.storage);
  const recovery = createRecoveryState({ initialPhase: "resolving" });
  const state = { current: options.current ?? null as string | null };
  const ended: string[] = [];
  const deps = {
    persistence,
    recovery,
    currentUserId: () => state.current,
    endRestoredSession: async (userId: string) => {
      ended.push(userId);

      if (options.end) {
        return options.end(userId);
      }

      state.current = null;

      return "signed-out" as const;
    },
  };

  return { m, persistence, recovery, state, ended, deps };
}

describe("resolveRecoveryAtStartup", () => {
  it("starts closed: resolving until resolved", () => {
    const w = setup();

    assert.equal(w.recovery.getSnapshot().phase, "resolving");
  });

  it("no marker: opens (idle) without touching storage or the session", async () => {
    const w = setup({ current: "u-1" });

    await resolveRecoveryAtStartup(w.deps, "u-1");
    assert.equal(w.recovery.getSnapshot().phase, "idle");
    assert.deepEqual(w.m.log, []);
    assert.deepEqual(w.ended, []);
  });

  it("an active recovery with its session is resumed: the reset screen, never the app", async () => {
    const w = setup({ marker: { v: 1, phase: "active", userId: "u-1" }, current: "u-1" });

    await resolveRecoveryAtStartup(w.deps, "u-1");
    assert.deepEqual(w.recovery.getSnapshot(), { phase: "active", userId: "u-1" });
    assert.deepEqual(w.ended, []);
  });

  it("an active record without a session is cleared (the recovery is over): signed out", async () => {
    const w = setup({ marker: { v: 1, phase: "active", userId: "u-1" }, current: null });

    await resolveRecoveryAtStartup(w.deps, null);
    assert.equal(w.recovery.getSnapshot().phase, "idle");
    assert.equal(w.m.data.size, 0);
  });

  it("a recovery that belongs to a different current user is dropped", async () => {
    const w = setup({ marker: { v: 1, phase: "active", userId: "u-1" }, current: "u-2" });

    await resolveRecoveryAtStartup(w.deps, "u-2");
    assert.equal(w.recovery.getSnapshot().phase, "idle");
    assert.equal(w.m.data.size, 0);
    assert.deepEqual(w.ended, [], "user 2's own session is left alone");
  });

  it("an incomplete record with an unexplained session ends that session, then clears the record", async () => {
    const w = setup({ marker: { v: 1, phase: "verifying", priorUserId: null, recoveryUserId: null }, current: "u-9" });

    await resolveRecoveryAtStartup(w.deps, "u-9");
    assert.deepEqual(w.ended, ["u-9"]);
    assert.equal(w.recovery.getSnapshot().phase, "idle");
    assert.equal(w.m.data.size, 0);
    assert.equal(w.state.current, null);
  });

  it("the record outlives the session: it is removed only AFTER the session is gone", async () => {
    let markerAtEnd: number | null = null;
    const w = setup({
      marker: { v: 1, phase: "verifying", priorUserId: null, recoveryUserId: null },
      current: "u-9",
      end: async () => {
        markerAtEnd = w.m.data.size;
        w.state.current = null;

        return "signed-out";
      },
    });

    await resolveRecoveryAtStartup(w.deps, "u-9");
    assert.equal(markerAtEnd, 1, "the record was still there while the session was being ended");
    assert.equal(w.m.data.size, 0);
  });

  it("an unreadable record with a session fails closed; with none it clears", async () => {
    const withSession = setup({ marker: "{corrupt", current: "u-1" });

    await resolveRecoveryAtStartup(withSession.deps, "u-1");
    assert.deepEqual(withSession.ended, ["u-1"]);
    assert.equal(withSession.recovery.getSnapshot().phase, "idle");

    const without = setup({ marker: "{corrupt", current: null });

    await resolveRecoveryAtStartup(without.deps, null);
    assert.equal(without.m.data.size, 0);
    assert.equal(without.recovery.getSnapshot().phase, "idle");

    const failing = setup({ current: "u-1" });

    failing.m.faults.read = true;
    await resolveRecoveryAtStartup(failing.deps, "u-1");
    assert.deepEqual(failing.ended, ["u-1"], "storage that cannot be read is not trusted");
  });

  it("when the session cannot be ended the app is NOT opened: the reset screen (with Cancel) is the fallback", async () => {
    const w = setup({
      marker: { v: 1, phase: "verifying", priorUserId: null, recoveryUserId: null },
      current: "u-9",
      end: async () => { throw new Error("storage failure"); },
    });

    await resolveRecoveryAtStartup(w.deps, "u-9");
    assert.deepEqual(w.recovery.getSnapshot(), { phase: "active", userId: "u-9" });
    assert.deepEqual(JSON.parse([...w.m.data.values()][0]), { v: 1, phase: "active", userId: "u-9" });
  });

  it("a session that changed while it was being ended ('stale') is not touched again", async () => {
    const w = setup({
      marker: { v: 1, phase: "verifying", priorUserId: null, recoveryUserId: null },
      current: "u-9",
      end: async () => { w.state.current = "u-2"; return "stale"; },
    });

    await resolveRecoveryAtStartup(w.deps, "u-9");
    assert.equal(w.recovery.getSnapshot().phase, "idle");
    assert.equal(w.state.current, "u-2");
  });

  it("a resumed recovery is dropped when the user signed out while the lookup ran", async () => {
    const w = setup({ marker: { v: 1, phase: "active", userId: "u-1" }, current: "u-1" });
    const read = w.persistence.read.bind(w.persistence);

    w.persistence.read = async () => { w.state.current = null; return read(); };
    await resolveRecoveryAtStartup(w.deps, "u-1");
    assert.equal(w.recovery.getSnapshot().phase, "idle", "a later ordinary sign-in as u-1 is not mistaken for a recovery");
  });

  it("a link that arrived during the resolution takes over afterwards, keeping a resumed recovery behind it", async () => {
    const w = setup({ marker: { v: 1, phase: "active", userId: "u-1" }, current: "u-1" });
    const attempt = w.recovery.begin();

    assert.equal(w.recovery.getSnapshot().phase, "resolving", "still closed");
    await resolveRecoveryAtStartup(w.deps, "u-1");
    assert.equal(w.recovery.getSnapshot().phase, "verifying");
    w.recovery.finish(attempt);
    assert.deepEqual(w.recovery.getSnapshot(), { phase: "active", userId: "u-1" }, "its failure leaves the resumed recovery in force");
  });

  it("never throws", async () => {
    const w = setup({ current: "u-1" });

    w.persistence.read = async () => { throw new Error("boom"); };
    await assert.doesNotReject(() => resolveRecoveryAtStartup(w.deps, "u-1"));
    assert.deepEqual(w.ended, ["u-1"]);
  });
});

describe("bindRecoveryPersistence", () => {
  const settle = () => new Promise((resolve) => setTimeout(resolve, 5));

  it("opening after the startup resolution does not remove a record it deferred", async () => {
    const m = memoryStorage();
    const persistence = createRecoveryPersistence(m.storage);
    const recovery = createRecoveryState({ initialPhase: "resolving" });

    await persistence.writeActive("u-1");
    bindRecoveryPersistence(recovery, persistence);
    recovery.finishResolving({ kind: "idle" }, null); // a deferral
    await settle();
    assert.deepEqual(await persistence.read(), { kind: "marker", marker: { v: 1, phase: "active", userId: "u-1" } });
  });

  it("records an active recovery and removes the record when it ends", async () => {
    const m = memoryStorage();
    const persistence = createRecoveryPersistence(m.storage);
    const recovery = createRecoveryState();

    bindRecoveryPersistence(recovery, persistence);
    recovery.activate(recovery.begin(), "u-1");
    await settle();
    assert.deepEqual(await persistence.read(), { kind: "marker", marker: { v: 1, phase: "active", userId: "u-1" } });
    recovery.complete("u-1");
    await settle();
    assert.deepEqual(await persistence.read(), { kind: "none" });
  });

  it("does not write while verifying (the handler writes that, awaited) and restores the active record after a failed attempt", async () => {
    const m = memoryStorage();
    const persistence = createRecoveryPersistence(m.storage);
    const recovery = createRecoveryState();

    bindRecoveryPersistence(recovery, persistence);
    recovery.activate(recovery.begin(), "u-1");
    await settle();

    const writes = m.log.length;
    const attempt = recovery.begin();

    await settle();
    assert.equal(m.log.length, writes, "nothing written for verifying");
    recovery.finish(attempt);
    await settle();
    assert.deepEqual(await persistence.read(), { kind: "marker", marker: { v: 1, phase: "active", userId: "u-1" } });
  });
});

describe("createStartupResolver", () => {
  it("resolves once; a deferred recovery is judged again, with the gate closed first, when a session appears", async () => {
    const w = setup({ marker: { v: 1, phase: "active", userId: "u-1" }, current: null });
    const resolver = createStartupResolver(w.deps);

    resolver.onAuthState(null, true);
    await resolver.whenDone();
    assert.equal(w.recovery.getSnapshot().phase, "deferred");
    assert.equal(w.m.data.size, 1, "the record was kept");

    resolver.onAuthState(null, false); // still nobody: nothing to re-judge
    assert.equal(w.recovery.getSnapshot().phase, "deferred");

    w.state.current = "u-1";
    resolver.onAuthState("u-1", false);
    assert.equal(w.recovery.getSnapshot().phase, "resolving", "closed synchronously, before anything can render the app");
    await resolver.whenDone();
    assert.deepEqual(w.recovery.getSnapshot(), { phase: "active", userId: "u-1" });
  });

  it("a deferred record that belongs to somebody else is cleared when that other user appears", async () => {
    const w = setup({ marker: { v: 1, phase: "active", userId: "u-1" }, current: null });
    const resolver = createStartupResolver(w.deps);

    resolver.onAuthState(null, true);
    await resolver.whenDone();
    w.state.current = "u-2";
    resolver.onAuthState("u-2", false);
    assert.equal(w.recovery.getSnapshot().phase, "resolving");
    await resolver.whenDone();
    assert.equal(w.recovery.getSnapshot().phase, "idle");
    assert.equal(w.m.data.size, 0);
  });

  it("is judged only once more: later sessions do not close the gate again", async () => {
    const w = setup({ marker: { v: 1, phase: "active", userId: "u-1" }, current: null });
    const resolver = createStartupResolver(w.deps);

    resolver.onAuthState(null, true);
    await resolver.whenDone();
    w.state.current = "u-2";
    resolver.onAuthState("u-2", false);
    await resolver.whenDone();
    resolver.onAuthState("u-3", false);
    assert.equal(w.recovery.getSnapshot().phase, "idle");
  });

  it("a failing link attempt while deferred leaves it deferred (and the record intact)", async () => {
    const w = setup({ marker: { v: 1, phase: "active", userId: "u-1" }, current: null });
    const resolver = createStartupResolver(w.deps);

    resolver.onAuthState(null, true);
    await resolver.whenDone();

    const attempt = w.recovery.begin();

    assert.equal(w.recovery.getSnapshot().phase, "verifying");
    await w.persistence.writeVerifying({ priorUserId: null, recoveryUserId: null });
    w.recovery.finish(attempt);
    assert.equal(w.recovery.getSnapshot().phase, "deferred", "never idle: the record is still unjudged");
    assert.deepEqual(JSON.parse([...w.m.data.values()][0]), { v: 1, phase: "verifying", priorUserId: null, recoveryUserId: "u-1" });
  });

  it("a session that appears while a link attempt runs is judged the moment the attempt ends", async () => {
    const w = setup({ marker: { v: 1, phase: "active", userId: "u-1" }, current: null });
    const resolver = createStartupResolver(w.deps);

    resolver.onAuthState(null, true);
    await resolver.whenDone();

    const attempt = w.recovery.begin();

    w.state.current = "u-1"; // the late session arrives mid-attempt
    resolver.onAuthState("u-1", false);
    assert.equal(w.recovery.getSnapshot().phase, "verifying", "closed: not judged yet, not the app");
    w.recovery.finish(attempt); // the attempt fails
    assert.equal(w.recovery.getSnapshot().phase, "resolving", "closed again, synchronously");
    await resolver.whenDone();
    assert.deepEqual(w.recovery.getSnapshot(), { phase: "active", userId: "u-1" });
  });

  it("without a deferral an ordinary later sign-in never closes the gate", async () => {
    const w = setup({ current: null });
    const resolver = createStartupResolver(w.deps);

    resolver.onAuthState(null, false);
    await resolver.whenDone();
    resolver.onAuthState("u-1", false);
    assert.equal(w.recovery.getSnapshot().phase, "idle");
  });
});
