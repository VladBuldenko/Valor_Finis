// MF2-SR07: HTTP 401 handling is bound to the authentication generation, and
// the sign-out SIDE EFFECT is guarded, not just the decision in front of it.
// Ordering is controlled with deferred promises.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { createAuthLab, deferred, tick } from "./auth-test-support.ts";
import type { RefreshResult, SessionIdentity } from "./session-lifecycle.ts";

const A1: SessionIdentity = { userId: "user-a", accessToken: "a-token-1" };
const A2: SessionIdentity = { userId: "user-a", accessToken: "a-token-2" };
const B1: SessionIdentity = { userId: "user-b", accessToken: "b-token-1" };

describe("SR07-T01: a stale 'who is signed in' answer cannot sign out B", () => {
  it("refresh rejected for A, then B is adopted; a late lookup claiming A is irrelevant", async () => {
    const refresh = deferred<RefreshResult>();
    const w = createAuthLab({ initial: A1, refresh: () => refresh.promise });
    // The old design asked the auth layer who is signed in at this point. Any
    // such lookup that is still pending when B arrives and then answers "A"...
    const staleLookup = deferred<SessionIdentity | null>();
    const result = w.lifecycle.handleUnauthorized(A1, w.proofFor(A1));

    await tick();
    w.event(B1); // the boundary adopts B while the 401 investigation is running
    refresh.resolve({ status: "rejected" });
    staleLookup.resolve(A1); // ...completes with the obsolete A

    assert.equal(await result, "stale");
    assert.equal(w.lab.signOutCalls, 0, "the sign-out side effect never ran");
    assert.deepEqual(w.lab.signedOutUsers, []);
    assert.equal(w.lab.current, B1, "B is still signed in");
    assert.equal(w.boundary.snapshot().userId, "user-b");
  });
});

describe("SR07-T02: A -> B -> A", () => {
  for (const [name, returning] of [["a new token", A2], ["the very same token", A1]] as const) {
    it(`an old generation cannot sign out the later A session (${name})`, async () => {
      const refresh = deferred<RefreshResult>();
      const w = createAuthLab({ initial: A1, refresh: () => refresh.promise });
      const firstGenerationProof = w.proofFor(A1);
      const result = w.lifecycle.handleUnauthorized(A1, firstGenerationProof);

      await tick();
      w.event(B1);
      w.event(returning); // user id (and even the token) match the first generation again
      refresh.resolve({ status: "rejected" });

      assert.equal(await result, "stale");
      assert.equal(w.lab.signOutCalls, 0);
      assert.equal(w.lab.current, returning, "the second A generation is untouched");
      assert.equal(firstGenerationProof.stillOwns(), false);
    });
  }

  it("a 401 of the second A generation is handled normally", async () => {
    const w = createAuthLab({ initial: A1, refresh: async () => ({ status: "rejected" }) });

    w.event(B1);
    w.event(A2);

    assert.equal(await w.lifecycle.handleUnauthorized(A2, w.proofFor(A2)), "signed-out");
    assert.deepEqual(w.lab.signedOutUsers, ["user-a"]);
  });
});

describe("SR07-T03: A token refresh during an ongoing 401 investigation", () => {
  it("a successful refresh keeps the session and signs nobody out", async () => {
    const refresh = deferred<RefreshResult>();
    const w = createAuthLab({ initial: A1, refresh: () => refresh.promise });
    const result = w.lifecycle.handleUnauthorized(A1, w.proofFor(A1));

    await tick();
    w.event(A2); // TOKEN_REFRESHED arrives from the refresh itself
    refresh.resolve({ status: "refreshed", session: A2 });

    assert.equal(await result, "refreshed");
    assert.equal(w.lab.signOutCalls, 0);
    assert.equal(w.lab.current, A2);
    assert.equal(w.lab.resets, 0, "a same-user refresh rotates nothing");
  });

  it("a refreshed token that arrives before a 'rejected' answer is never signed out", async () => {
    const refresh = deferred<RefreshResult>();
    const w = createAuthLab({ initial: A1, refresh: () => refresh.promise });
    const result = w.lifecycle.handleUnauthorized(A1, w.proofFor(A1));

    await tick();
    w.event(A2); // another path refreshed the session meanwhile
    refresh.resolve({ status: "rejected" });

    assert.equal(await result, "stale");
    assert.equal(w.lab.signOutCalls, 0);
    assert.equal(w.lab.current, A2);
  });
});

describe("SR07-T04: two simultaneous 401s followed by an account switch", () => {
  it("share one investigation; neither can sign out B", async () => {
    const refresh = deferred<RefreshResult>();
    const w = createAuthLab({ initial: A1, refresh: () => refresh.promise });
    const proof = w.proofFor(A1);
    const first = w.lifecycle.handleUnauthorized(A1, proof);
    const second = w.lifecycle.handleUnauthorized(A1, proof);

    await tick();
    assert.equal(w.lab.refreshCalls, 1, "deduplicated");
    w.event(B1);
    refresh.resolve({ status: "rejected" });

    assert.deepEqual([await first, await second], ["stale", "stale"]);
    assert.equal(w.lab.signOutCalls, 0);
    assert.equal(w.lab.current, B1);
  });

  it("401s of different generations with the same token are not merged", async () => {
    const refresh = deferred<RefreshResult>();
    const w = createAuthLab({ initial: A1, refresh: () => refresh.promise });
    const old = w.lifecycle.handleUnauthorized(A1, w.proofFor(A1));

    await tick();
    w.event(B1);
    w.event(A1); // same user and same token string, new generation

    const current = w.lifecycle.handleUnauthorized(A1, w.proofFor(A1));

    await tick();
    assert.equal(w.lab.refreshCalls, 1, "the second generation's refresh waits in the queue behind the first");
    refresh.resolve({ status: "rejected" });

    assert.equal(await old, "stale");
    assert.equal(await current, "signed-out");
    assert.equal(w.lab.refreshCalls, 2, "separate investigations, never merged");
    assert.deepEqual(w.lab.signedOutUsers, ["user-a"], "only the current generation was ended");
  });
});

describe("SR07-T05: the account changes while session-ending work is in progress", () => {
  it("sign-out already running: B's sign-in waits for it, so B is not signed out", async () => {
    const gate = deferred<void>();
    const w = createAuthLab({
      initial: A1,
      refresh: async () => ({ status: "rejected" }),
      signOutGate: gate,
    });
    const ending = w.lifecycle.handleUnauthorized(A1, w.proofFor(A1));

    await tick(); // A's sign-out is now running (held by the gate)
    const signingIn = w.signIn(B1); // the user logs in as B meanwhile: queued behind it

    await tick();
    assert.equal(w.lab.current?.userId, "user-a", "B cannot take over while A's sign-out runs");
    gate.resolve();

    assert.equal(await ending, "signed-out");
    await signingIn;
    assert.deepEqual(w.lab.signedOutUsers, ["user-a"], "the side effect hit A, not B");
    assert.equal(w.lab.current, B1, "B is signed in afterwards");
  });

  it("B's sign-in already running: A's queued sign-out re-checks and does nothing", async () => {
    const loginGate = deferred<void>();
    const w = createAuthLab({ initial: A1, refresh: async () => ({ status: "rejected" }) });
    const signingIn = w.signIn(B1, loginGate); // B's login starts first and is slow
    const ending = w.lifecycle.handleUnauthorized(A1, w.proofFor(A1));

    await tick();
    assert.equal(w.lab.signOutCalls, 0, "sign-out is queued behind the login");
    loginGate.resolve();
    await signingIn;

    assert.equal(await ending, "stale");
    assert.equal(w.lab.signOutCalls, 0, "the side effect never ran");
    assert.equal(w.lab.current, B1);
  });

  it("an auth event outside the queue while sign-out waits is still caught by the final check", async () => {
    const blocker = deferred<void>();
    const w = createAuthLab({ initial: A1, refresh: async () => ({ status: "rejected" }) });
    const busy = w.queue.run(() => blocker.promise); // some other auth operation holds the queue
    const ending = w.lifecycle.handleUnauthorized(A1, w.proofFor(A1));

    await tick();
    w.event(B1); // B arrives by a path that is not queued
    blocker.resolve();
    await busy;

    assert.equal(await ending, "stale", "ownership is checked when the side effect would start");
    assert.equal(w.lab.signOutCalls, 0);
    assert.equal(w.lab.current, B1);
  });

  it("B's sign-in queued DURING the refresh round trip runs before A's sign-out: only the in-slot check stops it", async () => {
    const refresh = deferred<RefreshResult>();
    const w = createAuthLab({ initial: A1, refresh: () => refresh.promise });
    const handling = w.lifecycle.handleUnauthorized(A1, w.proofFor(A1));

    await tick(); // the refresh slot is running; A is still the owner
    const signingIn = w.signIn(B1); // queued behind the refresh

    refresh.resolve({ status: "rejected" }); // post-refresh check passes (B has not run yet)...
    await signingIn; // ...then B's sign-in runs BEFORE A's sign-out slot

    assert.equal(await handling, "stale", "the sign-out slot re-checked ownership and stood down");
    assert.equal(w.lab.signOutCalls, 0);
    assert.equal(w.lab.current, B1);
  });

  it("a failing auth operation does not block the queue behind it", async () => {
    const w = createAuthLab({ initial: A1, refresh: async () => ({ status: "rejected" }) });

    await assert.rejects(w.queue.run(async () => { throw new Error("sign-in failed"); }));
    assert.equal(await w.lifecycle.handleUnauthorized(A1, w.proofFor(A1)), "signed-out");
  });
});

describe("SR07-T06: a genuine invalid current session still signs out", () => {
  it("ends the session once, and the boundary becomes 'nobody'", async () => {
    const w = createAuthLab({ initial: A1, refresh: async () => ({ status: "rejected" }) });

    assert.equal(await w.lifecycle.handleUnauthorized(A1, w.proofFor(A1)), "signed-out");
    assert.deepEqual(w.lab.signedOutUsers, ["user-a"]);
    assert.equal(w.lab.current, null);
    assert.equal(w.boundary.snapshot().userId, null);
    assert.equal(w.lab.resets, 1);
  });

  it("many simultaneous 401s of a genuinely invalid session sign out exactly once", async () => {
    const w = createAuthLab({
      initial: A1,
      refresh: async () => {
        await tick();

        return { status: "rejected" };
      },
    });
    const proof = w.proofFor(A1);
    const results = await Promise.all(Array.from({ length: 10 }, () => w.lifecycle.handleUnauthorized(A1, proof)));

    assert.deepEqual(results, Array(10).fill("signed-out"));
    assert.equal(w.lab.signOutCalls, 1);
  });

  it("an auth layer that already ended the session while rejecting leaves nothing to sign out", async () => {
    const w = createAuthLab({ initial: A1, refresh: async () => ({ status: "rejected" }) });
    const proof = w.proofFor(A1);

    w.event(null); // Supabase removed the dead session itself
    assert.equal(await w.lifecycle.handleUnauthorized(A1, proof), "stale");
    assert.equal(w.lab.signOutCalls, 0);
  });
});

describe("the boundary tracks the authoritative token", () => {
  it("ownsToken follows same-user refreshes and generations", () => {
    const w = createAuthLab({ initial: A1 });
    const snapshot = w.boundary.snapshot();

    assert.equal(w.boundary.ownsToken(snapshot, "user-a", "a-token-1"), true);
    w.event(A2);
    assert.equal(w.boundary.ownsToken(snapshot, "user-a", "a-token-1"), false, "superseded token");
    assert.equal(w.boundary.ownsToken(snapshot, "user-a", "a-token-2"), true, "same generation, current token");
    w.event(B1);
    w.event(A2);
    assert.equal(w.boundary.ownsToken(snapshot, "user-a", "a-token-2"), false, "later generation");
  });

  it("a signed-out boundary owns no token", () => {
    const w = createAuthLab({ initial: A1 });
    const snapshot = w.boundary.snapshot();

    w.event(null);
    assert.equal(w.boundary.ownsToken(snapshot, "user-a", "a-token-1"), false);
  });
});
