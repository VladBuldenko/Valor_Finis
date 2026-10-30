import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { ApiError } from "./api-error.ts";
import { createAuthLab, deferred, tick } from "./auth-test-support.ts";
import { json, makeHarness, never } from "./api-test-support.ts";
import {
  classifyRefreshError,
  createSessionLifecycle,
  type RefreshResult,
  type SessionIdentity,
} from "./session-lifecycle.ts";

const A1: SessionIdentity = { userId: "user-a", accessToken: "a-token-1" };
const A2: SessionIdentity = { userId: "user-a", accessToken: "a-token-2" };
const B1: SessionIdentity = { userId: "user-b", accessToken: "b-token-1" };

describe("handleUnauthorized", () => {
  it("ends the session only when the auth server rejects the refresh", async () => {
    const w = createAuthLab({ initial: A1, refresh: async () => ({ status: "rejected" }) });

    assert.equal(await w.lifecycle.handleUnauthorized(A1, w.proofFor(A1)), "signed-out");
    assert.equal(w.lab.signOutCalls, 1);
    assert.deepEqual(w.lab.signedOutUsers, ["user-a"]);
  });

  it("keeps the session when the refresh gives a new token", async () => {
    const w = createAuthLab({ initial: A1, refresh: async () => ({ status: "refreshed", session: A2 }) });

    assert.equal(await w.lifecycle.handleUnauthorized(A1, w.proofFor(A1)), "refreshed");
    assert.equal(w.lab.signOutCalls, 0);
  });

  it("keeps the session when the auth server cannot be reached", async () => {
    const w = createAuthLab({ initial: A1, refresh: async () => ({ status: "unavailable" }) });

    assert.equal(await w.lifecycle.handleUnauthorized(A1, w.proofFor(A1)), "unconfirmed");
    assert.equal(w.lab.signOutCalls, 0);
  });

  it("does not trust a refresh that returns the very same token", async () => {
    const w = createAuthLab({ initial: A1, refresh: async () => ({ status: "refreshed", session: A1 }) });

    assert.equal(await w.lifecycle.handleUnauthorized(A1, w.proofFor(A1)), "unconfirmed");
    assert.equal(w.lab.signOutCalls, 0);
  });

  it("ignores an old token's 401 after the session was refreshed (token race)", async () => {
    const w = createAuthLab({ initial: A1 });
    const oldProof = w.proofFor(A1);

    w.event(A2); // TOKEN_REFRESHED
    assert.equal(await w.lifecycle.handleUnauthorized(A1, oldProof), "stale");
    assert.equal(w.lab.refreshCalls, 0);
    assert.equal(w.lab.signOutCalls, 0);
  });

  it("ignores a 401 from a previous user's session after an account switch", async () => {
    const w = createAuthLab({ initial: A1 });
    const oldProof = w.proofFor(A1);

    w.event(B1);
    assert.equal(await w.lifecycle.handleUnauthorized(A1, oldProof), "stale");
    assert.equal(w.lab.signOutCalls, 0);
    assert.equal(w.lab.current, B1);
  });

  it("ignores a 401 when nobody is signed in any more", async () => {
    const w = createAuthLab({ initial: A1 });
    const oldProof = w.proofFor(A1);

    w.event(null);
    assert.equal(await w.lifecycle.handleUnauthorized(A1, oldProof), "stale");
    assert.equal(w.lab.refreshCalls, 0);
  });

  it("shares one check between simultaneous 401s of the same token", async () => {
    const refresh = deferred<RefreshResult>();
    const w = createAuthLab({ initial: A1, refresh: () => refresh.promise });
    const proof = w.proofFor(A1);
    const results = [1, 2, 3, 4, 5].map(() => w.lifecycle.handleUnauthorized(A1, proof));

    await tick();
    refresh.resolve({ status: "rejected" });

    assert.deepEqual(await Promise.all(results), Array(5).fill("signed-out"));
    assert.equal(w.lab.refreshCalls, 1);
    assert.equal(w.lab.signOutCalls, 1);
  });

  it("runs a fresh check for a later 401 once the first has finished", async () => {
    const w = createAuthLab({ initial: A1, refresh: async () => ({ status: "unavailable" }) });
    const proof = w.proofFor(A1);

    await w.lifecycle.handleUnauthorized(A1, proof);
    await w.lifecycle.handleUnauthorized(A1, proof);
    assert.equal(w.lab.refreshCalls, 2);
  });

  it("does not look up the current session at all (no stale lookup can authorize anything)", () => {
    // The lifecycle's dependencies are exactly refreshSession and endSession.
    const lifecycle = createSessionLifecycle({
      refreshSession: async () => ({ status: "unavailable" }),
      endSession: async () => "stale",
    });

    assert.deepEqual(Object.keys(lifecycle), ["handleUnauthorized"]);
  });
});

describe("classifyRefreshError", () => {
  it("rejects only on explicit auth-server answers", () => {
    assert.equal(classifyRefreshError({ name: "AuthSessionMissingError" }), "rejected");

    for (const status of [400, 401, 403, 404, 422]) {
      assert.equal(classifyRefreshError({ name: "AuthApiError", status }), "rejected");
    }
  });

  it("treats network, server and rate-limit failures as unconfirmed", () => {
    assert.equal(classifyRefreshError({ name: "AuthRetryableFetchError", status: 0 }), "unavailable");

    for (const status of [429, 500, 502, 503]) {
      assert.equal(classifyRefreshError({ name: "AuthApiError", status }), "unavailable");
    }

    assert.equal(classifyRefreshError({}), "unavailable");
    assert.equal(classifyRefreshError({ name: "TypeError" }), "unavailable");
  });
});

// The transport and the lifecycle together, with a scripted auth world.
describe("HTTP 401 through the transport", () => {
  function setup(
    refresh: () => Promise<RefreshResult>,
    respond: Parameters<typeof makeHarness>[0]["respond"],
  ) {
    const lifecycleRef: { current: ReturnType<typeof createAuthLab> | null } = { current: null };
    const h = makeHarness({
      respond,
      session: async () => lifecycleRef.current?.lab.current ?? null,
      onUnauthorized: (used, proof) => {
        const w = lifecycleRef.current;

        if (!w) {
          throw new Error("lab missing");
        }

        return w.lifecycle.handleUnauthorized(used, proof);
      },
    });
    const w = createAuthLab({ initial: A1, refresh, boundary: h.boundary });

    lifecycleRef.current = w;

    return { w, h };
  }

  it("answers with an unauthorized ApiError and ends a confirmed-invalid session", async () => {
    const { w, h } = setup(
      async () => ({ status: "rejected" }),
      async () => json(401, { detail: "Invalid token" }),
    );

    await assert.rejects(h.transport.request("/x"), (error: unknown) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.kind, "unauthorized");
      assert.equal(error.status, 401);
      assert.equal(error.message, 'API request failed: 401 {"detail":"Invalid token"}');

      return true;
    });
    assert.equal(w.lab.signOutCalls, 1);
  });

  it("concurrent 401s sign out exactly once and all callers fail", async () => {
    const { w, h } = setup(
      async () => {
        await tick();

        return { status: "rejected" };
      },
      async () => json(401, { detail: "expired" }),
    );
    const results = await Promise.allSettled(
      Array.from({ length: 8 }, (_unused, index) => h.transport.request(`/x/${index}`)),
    );

    assert.ok(results.every((result) => result.status === "rejected"));
    assert.equal(w.lab.refreshCalls, 1);
    assert.equal(w.lab.signOutCalls, 1);
  });

  it("a late 401 for an old token does not sign out the refreshed session", async () => {
    const release = deferred<Response>();
    const { w, h } = setup(async () => ({ status: "rejected" }), () => release.promise);
    const pending = h.transport.request("/x");

    await tick();
    w.event(A2); // the token was refreshed while the request was in flight
    release.resolve(json(401, {}));

    await assert.rejects(pending);
    assert.equal(w.lab.signOutCalls, 0);
    assert.equal(w.lab.current, A2);
  });

  it("a 401 that arrives after the user switched is dropped before any sign-out logic", async () => {
    const release = deferred<Response>();
    const { w, h } = setup(async () => ({ status: "rejected" }), () => release.promise);
    const pending = h.transport.request("/x");

    await tick();
    w.event(B1);
    release.resolve(json(401, {}));

    await assert.rejects(pending, (error: unknown) => error instanceof ApiError && error.kind === "cancelled");
    assert.equal(w.lab.refreshCalls, 0);
    assert.equal(w.lab.current, B1);
  });

  it("keeps the session on a 401 while the auth server is unreachable", async () => {
    const { w, h } = setup(async () => ({ status: "unavailable" }), async () => json(401, {}));

    await assert.rejects(h.transport.request("/x"));
    assert.equal(w.lab.signOutCalls, 0);
  });

  it("does not replay a request after a successful token refresh, mutation or not", async () => {
    const { h } = setup(async () => ({ status: "refreshed", session: A2 }), async () => json(401, {}));

    await assert.rejects(h.transport.request("/x"));
    await assert.rejects(h.transport.request("/y", { method: "POST", body: "{}" }));
    assert.equal(h.calls.length, 2, "one network attempt per call, no replay");
  });

  it("a failing session check never masks the 401", async () => {
    const h = makeHarness({
      respond: async () => json(401, { detail: "no" }),
      onUnauthorized: async () => {
        throw new Error("auth check exploded");
      },
    });

    await assert.rejects(h.transport.request("/x"), (error: unknown) =>
      error instanceof ApiError && error.kind === "unauthorized");
  });

  it("a hung session check cannot hold the request past its deadline", async () => {
    const h = makeHarness({
      respond: async () => json(401, {}),
      onUnauthorized: () => never(),
      policy: { timeoutMs: 40 },
    });

    await assert.rejects(h.transport.request("/x"), (error: unknown) =>
      error instanceof ApiError && error.kind === "timeout");
  });
});
