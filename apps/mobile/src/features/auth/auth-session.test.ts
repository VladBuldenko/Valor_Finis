// MF2-SR08: the AuthProvider effect's lifecycle. An obsolete provider instance
// (unmounted, or superseded by a newer one) must never change the global
// session boundary or publish state.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { SessionBoundary } from "../../api/session-boundary.ts";
import { SessionQueryClient } from "../../lib/session-query-client.ts";
import type { AuthState } from "./auth-coordinator.ts";
import { startAuthSession } from "./auth-session.ts";
import { createFakeAuth, session, type FakeSession } from "./auth-test-support.ts";

const tick = (ms = 5) => new Promise((resolve) => setTimeout(resolve, ms));

function lab() {
  const holder = new SessionQueryClient();
  const resets = { count: 0 };
  const boundary = new SessionBoundary(() => {
    resets.count += 1;
    holder.rotate();
  });
  const auth = createFakeAuth();
  const published: { who: string; state: AuthState<FakeSession> }[] = [];

  // One "provider effect": returns its cleanup, like useEffect's.
  function mountProvider(who: string): () => void {
    return startAuthSession<FakeSession>({
      auth: auth.client,
      boundary,
      publish: (state) => published.push({ who, state }),
    });
  }

  const publishedBy = (who: string) => published.filter((entry) => entry.who === who);

  return { holder, boundary, resets, auth, mountProvider, published, publishedBy };
}

describe("SR08-T01: an unmounted provider's restore resolves after the new provider adopted B", () => {
  it("the boundary stays on B and the old provider publishes nothing", async () => {
    const w = lab();
    const cleanupOld = w.mountProvider("old"); // old loadSession() for A is pending (restore #0)

    cleanupOld(); // unmount: effect cleanup

    w.mountProvider("new");
    w.auth.emit(session("user-b")); // authoritative event, delivered to the new provider

    const ownerBefore = w.boundary.snapshot().userId;
    const resetsBefore = w.resets.count;

    w.auth.resolveRestore(0, session("user-a")); // the OLD restore resolves with A
    await tick();

    assert.equal(ownerBefore, "user-b");
    assert.equal(w.boundary.snapshot().userId, "user-b", "the old restore did not take over");
    assert.equal(w.resets.count, resetsBefore, "and caused no reset");
    assert.deepEqual(w.publishedBy("old"), []);
    assert.equal(w.publishedBy("new").at(-1)?.state.session?.user.id, "user-b");
  });
});

describe("SR08-T02: a late auth-event callback of a disposed subscription", () => {
  it("is inert: no boundary change, no published state", async () => {
    const w = lab();
    const cleanupOld = w.mountProvider("old");

    w.auth.emit(session("user-b")); // the provider is alive: B adopted
    cleanupOld();
    w.mountProvider("new");

    const callbackOfOld = w.auth.registered[0];
    const publishedBefore = w.published.length;

    callbackOfOld("EVENT", session("user-a")); // arrives after unsubscribe
    callbackOfOld("EVENT", null);

    assert.equal(w.boundary.snapshot().userId, "user-b");
    assert.equal(w.published.length, publishedBefore);
  });

  it("a superseded provider that was never cleaned up is inert too (newest authority wins)", () => {
    const w = lab();

    w.mountProvider("first");
    w.mountProvider("second"); // claims the authority; "first" is not cleaned up
    w.auth.registered[0]("EVENT", session("user-a")); // first's callback fires
    w.auth.registered[1]("EVENT", session("user-b"));

    assert.equal(w.boundary.snapshot().userId, "user-b");
    assert.deepEqual(w.publishedBy("first"), []);
  });
});

describe("SR08-T04: signed-out state is not overwritten by an obsolete restore", () => {
  it("a sign-out on the active provider survives the old restore resolving with A", async () => {
    const w = lab();
    const cleanupOld = w.mountProvider("old");

    cleanupOld();
    w.mountProvider("new");
    w.auth.emit(session("user-a"));
    w.auth.emit(null); // sign-out

    w.auth.resolveRestore(0, session("user-a")); // obsolete restore says A
    w.auth.resolveRestore(1, session("user-a")); // and the new provider's own restore started before the sign-out
    await tick();

    assert.equal(w.boundary.snapshot().userId, null, "still signed out");
    assert.equal(w.publishedBy("new").at(-1)?.state.session, null);
    assert.equal(w.publishedBy("old").length, 0);
  });
});

describe("SR08-T05: the active provider restores a valid user", () => {
  it("adopts the restored session in the boundary first, then publishes it", async () => {
    const w = lab();

    w.mountProvider("only");
    assert.equal(w.published.length, 0, "loading until the restore answers");
    w.auth.resolveRestore(0, session("user-a"));
    await tick();

    assert.equal(w.boundary.snapshot().userId, "user-a");
    assert.deepEqual(w.publishedBy("only").map((entry) => [entry.state.session?.user.id, entry.state.isLoading]), [
      ["user-a", false],
    ]);
    assert.equal(w.boundary.ownsToken(w.boundary.snapshot(), "user-a", "token-user-a"), true);
  });

  it("a restore that finds no session ends loading as signed out", async () => {
    const w = lab();

    w.mountProvider("only");
    w.auth.resolveRestore(0, null);
    await tick();

    assert.deepEqual(w.publishedBy("only").map((entry) => [entry.state.session, entry.state.isLoading]), [[null, false]]);
  });

  it("an event that arrives before the restore wins over it (event-over-restore precedence)", async () => {
    const w = lab();

    w.mountProvider("only");
    w.auth.emit(session("user-b"));
    w.auth.resolveRestore(0, session("user-a"));
    await tick();

    assert.equal(w.boundary.snapshot().userId, "user-b");
  });

  it("a failing restore ends loading as signed out and reports the error", async () => {
    const w = lab();
    const errors: unknown[] = [];
    const failing = {
      ...w.auth.client,
      getSession: () => Promise.reject(new Error("storage unavailable")),
    };

    startAuthSession<FakeSession>({
      auth: failing,
      boundary: w.boundary,
      publish: (state) => w.published.push({ who: "failing", state }),
      onRestoreError: (error) => errors.push(error),
    });
    await tick();

    assert.equal(errors.length, 1);
    assert.deepEqual(w.publishedBy("failing").map((entry) => entry.state.session), [null]);
  });
});

describe("SR08-T06: a token refresh does not rotate the QueryClient", () => {
  it("same-user events only move the token", async () => {
    const w = lab();

    w.mountProvider("only");
    w.auth.resolveRestore(0, session("user-a", "token-1"));
    await tick();

    const generation = w.holder.getSnapshot().generation;
    const client = w.holder.get();

    w.auth.emit(session("user-a", "token-2")); // TOKEN_REFRESHED
    w.auth.emit(session("user-a", "token-3"));

    assert.equal(w.holder.getSnapshot().generation, generation);
    assert.equal(w.holder.get(), client);
    assert.equal(w.resets.count, 0);

    const snapshot = w.boundary.snapshot();

    assert.equal(w.boundary.ownsToken(snapshot, "user-a", "token-3"), true);
    assert.equal(w.boundary.ownsToken(snapshot, "user-a", "token-1"), false, "superseded token no longer owns");
  });
});

describe("the event handler makes no Supabase Auth call", () => {
  it("delivering events does not call getSession or subscribe again", () => {
    const w = lab();

    w.mountProvider("only");

    const before = { ...w.auth.calls };

    w.auth.emit(session("user-a"));
    w.auth.emit(null);
    w.auth.emit(session("user-b"));

    assert.deepEqual(w.auth.calls, before);
  });
});

describe("authority", () => {
  it("only the newest claim is active; release makes a claim inert", () => {
    const boundary = new SessionBoundary(() => undefined);
    const first = boundary.claimAuthority();
    const second = boundary.claimAuthority();

    assert.equal(first.isActive(), false);
    assert.equal(first.applyAuthEvent("user-a", "t"), false);
    assert.equal(boundary.snapshot().userId, null);
    assert.equal(second.isActive(), true);
    assert.equal(second.applyAuthEvent("user-b", "t"), true);

    second.release();
    assert.equal(second.isActive(), false);
    assert.equal(second.applyAuthEvent("user-c", "t"), false);
    assert.equal(boundary.snapshot().userId, "user-b");
  });
});
