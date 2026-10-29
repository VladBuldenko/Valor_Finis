import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { ApiError } from "./api-error.ts";
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

// A scripted auth world: the "current" session can change between awaits.
function world(initial: SessionIdentity | null, refresh: () => Promise<RefreshResult>) {
  const state = { current: initial, refreshCalls: 0, endCalls: 0 };
  const lifecycle = createSessionLifecycle({
    getCurrentSession: async () => state.current,
    refreshSession: async () => {
      state.refreshCalls += 1;

      return refresh();
    },
    endSession: async () => {
      state.endCalls += 1;
      state.current = null;
    },
  });

  return { state, lifecycle };
}

const tick = () => new Promise((resolve) => setTimeout(resolve, 5));

describe("handleUnauthorized", () => {
  it("ends the session only when the auth server rejects the refresh", async () => {
    const w = world(A1, async () => ({ status: "rejected" }));

    assert.equal(await w.lifecycle.handleUnauthorized(A1), "signed-out");
    assert.equal(w.state.endCalls, 1);
  });

  it("keeps the session when the refresh gives a new token", async () => {
    const w = world(A1, async () => ({ status: "refreshed", session: A2 }));

    assert.equal(await w.lifecycle.handleUnauthorized(A1), "refreshed");
    assert.equal(w.state.endCalls, 0);
  });

  it("keeps the session when the auth server cannot be reached", async () => {
    const w = world(A1, async () => ({ status: "unavailable" }));

    assert.equal(await w.lifecycle.handleUnauthorized(A1), "unconfirmed");
    assert.equal(w.state.endCalls, 0);
  });

  it("does not trust a refresh that returns the very same token", async () => {
    const w = world(A1, async () => ({ status: "refreshed", session: A1 }));

    assert.equal(await w.lifecycle.handleUnauthorized(A1), "unconfirmed");
    assert.equal(w.state.endCalls, 0);
  });

  it("ignores an old token's 401 after the session was refreshed (token race)", async () => {
    const w = world(A2, async () => ({ status: "rejected" }));

    assert.equal(await w.lifecycle.handleUnauthorized(A1), "stale");
    assert.equal(w.state.refreshCalls, 0);
    assert.equal(w.state.endCalls, 0);
  });

  it("ignores a 401 from a previous user's session after an account switch", async () => {
    const w = world(B1, async () => ({ status: "rejected" }));

    assert.equal(await w.lifecycle.handleUnauthorized(A1), "stale");
    assert.equal(w.state.endCalls, 0);
    assert.equal(w.state.current, B1);
  });

  it("ignores a 401 when nobody is signed in any more", async () => {
    const w = world(null, async () => ({ status: "rejected" }));

    assert.equal(await w.lifecycle.handleUnauthorized(A1), "stale");
    assert.equal(w.state.refreshCalls, 0);
  });

  it("does not end a newer session that appeared while the refresh was running", async () => {
    let release: (value: RefreshResult) => void = () => undefined;
    const w = world(A1, () => new Promise<RefreshResult>((resolve) => { release = resolve; }));
    const pending = w.lifecycle.handleUnauthorized(A1);

    await tick();
    w.state.current = B1; // the user switched accounts during the refresh
    release({ status: "rejected" });

    assert.equal(await pending, "stale");
    assert.equal(w.state.endCalls, 0);
    assert.equal(w.state.current, B1);
  });

  it("shares one check between simultaneous 401s of the same token", async () => {
    const releases: ((value: RefreshResult) => void)[] = [];
    const w = world(A1, () => new Promise<RefreshResult>((resolve) => { releases.push(resolve); }));
    const results = [1, 2, 3, 4, 5].map(() => w.lifecycle.handleUnauthorized(A1));

    await tick();
    releases.forEach((release) => release({ status: "rejected" }));

    assert.deepEqual(await Promise.all(results), Array(5).fill("signed-out"));
    assert.equal(w.state.refreshCalls, 1);
    assert.equal(w.state.endCalls, 1);
  });

  it("runs a fresh check for a later 401 once the first has finished", async () => {
    const w = world(A1, async () => ({ status: "unavailable" }));

    await w.lifecycle.handleUnauthorized(A1);
    await w.lifecycle.handleUnauthorized(A1);
    assert.equal(w.state.refreshCalls, 2);
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
    initial: SessionIdentity | null = A1,
  ) {
    const w = world(initial, refresh);
    const h = makeHarness({
      respond,
      session: async () => w.state.current,
      onUnauthorized: (used) => w.lifecycle.handleUnauthorized(used),
    });

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
    assert.equal(w.state.endCalls, 1);
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
    assert.equal(w.state.refreshCalls, 1);
    assert.equal(w.state.endCalls, 1);
  });

  it("a late 401 for an old token does not sign out the refreshed session", async () => {
    let release: () => void = () => undefined;
    const { w, h } = setup(
      async () => ({ status: "rejected" }),
      () => new Promise<Response>((resolve) => { release = () => resolve(json(401, {})); }),
    );
    const pending = h.transport.request("/x");

    await tick();
    w.state.current = A2; // the token was refreshed while the request was in flight
    release();

    await assert.rejects(pending);
    assert.equal(w.state.endCalls, 0);
    assert.equal(w.state.current, A2);
  });

  it("a 401 that arrives after the user switched is dropped before any sign-out logic", async () => {
    let release: () => void = () => undefined;
    const { w, h } = setup(
      async () => ({ status: "rejected" }),
      () => new Promise<Response>((resolve) => { release = () => resolve(json(401, {})); }),
    );
    const pending = h.transport.request("/x");

    await tick();
    w.state.current = B1;
    h.boundary.observe(B1.userId);
    release();

    await assert.rejects(pending, (error: unknown) => error instanceof ApiError && error.kind === "cancelled");
    assert.equal(w.state.refreshCalls, 0);
    assert.equal(w.state.current, B1);
  });

  it("keeps the session on a 401 while the auth server is unreachable", async () => {
    const { w, h } = setup(
      async () => ({ status: "unavailable" }),
      async () => json(401, {}),
    );

    await assert.rejects(h.transport.request("/x"));
    assert.equal(w.state.endCalls, 0);
  });

  it("does not replay a request after a successful token refresh, mutation or not", async () => {
    const { h } = setup(
      async () => ({ status: "refreshed", session: A2 }),
      async () => json(401, {}),
    );

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
