// MF2-SR02 / SR06: session ownership across asynchronous session lookups and
// authentication events. All timing is controlled with deferred promises.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { createAuthCoordinator } from "../features/auth/auth-coordinator.ts";
import { ApiError } from "./api-error.ts";
import { createApiTransport } from "./api-transport.ts";
import { hangUntilAborted, json } from "./api-test-support.ts";
import { SessionBoundary } from "./session-boundary.ts";
import { createAuthLab } from "./auth-test-support.ts";
import type { RefreshResult, SessionIdentity } from "./session-lifecycle.ts";

const A1: SessionIdentity = { userId: "user-a", accessToken: "a-token-1" };
const A2: SessionIdentity = { userId: "user-a", accessToken: "a-token-2" };
const B1: SessionIdentity = { userId: "user-b", accessToken: "b-token-1" };

function deferred<T>() {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((done) => { resolve = done; });

  return { promise, resolve };
}

const tick = (ms = 5) => new Promise((resolve) => setTimeout(resolve, ms));
const outcome = (promise: Promise<unknown>) =>
  promise.then(
    () => "resolved",
    (error: unknown) => (error instanceof ApiError ? error.kind : "other"),
  );

// A scripted authentication world. Each getSession() call waits on its own
// deferred, so a test decides exactly when (and with what) a lookup resolves.
function world() {
  const resets: number[] = [];
  const boundary = new SessionBoundary(() => resets.push(Date.now()));
  const lookups: ReturnType<typeof deferred<SessionIdentity | null>>[] = [];
  const http: { token: string | null; signal: AbortSignal }[] = [];
  const unauthorized: SessionIdentity[] = [];
  const respond: { next: (token: string | null, init: RequestInit) => Promise<Response> } = {
    next: async () => json(200, { ok: true }),
  };
  const transport = createApiTransport({
    baseUrl: "https://api.test",
    boundary,
    sleep: async () => undefined,
    getSession: () => {
      const lookup = deferred<SessionIdentity | null>();

      lookups.push(lookup);

      return lookup.promise;
    },
    fetch: (_url, init) => {
      const token = new Headers(init.headers).get("Authorization");

      http.push({ token, signal: init.signal as AbortSignal });

      return respond.next(token, init);
    },
    onUnauthorized: async (used) => {
      unauthorized.push(used);
    },
  });

  return { boundary, resets, lookups, http, unauthorized, respond, transport };
}

describe("SR02-T01: delayed getSession() after A -> B", () => {
  it("refuses A's stale lookup before HTTP, leaves B running and the boundary untouched", async () => {
    const w = world();

    w.boundary.applyAuthEvent("user-a", "token-user-a");

    const requestA = outcome(w.transport.request("/a"));

    await tick(); // A is waiting inside getSession()
    assert.equal(w.lookups.length, 1);

    w.boundary.applyAuthEvent("user-b", "token-user-b"); // authoritative switch A -> B
    w.respond.next = (_token, init) => hangUntilAborted(init); // B's request stays in flight

    const requestB = outcome(w.transport.request("/b"));

    await tick();
    w.lookups[1].resolve(B1); // B's own lookup
    await tick();
    assert.equal(w.http.length, 1, "B has been dispatched");

    const resetsBefore = w.resets.length;
    const snapshotBefore = w.boundary.snapshot();

    w.lookups[0].resolve(A1); // A's obsolete lookup resolves late
    assert.equal(await requestA, "cancelled");
    await tick();

    assert.equal(w.http.length, 1, "A never issued an HTTP request");
    assert.deepEqual(w.http.map((call) => call.token), ["Bearer b-token-1"]);
    assert.equal(w.http[0].signal.aborted, false, "B was not cancelled");
    assert.equal(w.resets.length, resetsBefore, "A could not reset the boundary");
    assert.equal(w.boundary.snapshot().epoch, snapshotBefore.epoch);
    assert.equal(w.boundary.snapshot().userId, "user-b", "A cannot modify session ownership");

    w.respond.next = async () => json(200, {});
    // B's request is still pending and alive:
    assert.equal(w.http[0].signal.aborted, false);
    w.boundary.applyAuthEvent(null, null);
    assert.equal(await requestB, "cancelled", "only a real auth event ends B");
  });

  it("the same race as reproduced on ef9b63b: B completes, A is refused (one reset only)", async () => {
    const w = world();

    w.boundary.applyAuthEvent("user-a", "token-user-a");

    const requestA = outcome(w.transport.request("/a"));

    await tick();
    w.boundary.applyAuthEvent("user-b", "token-user-b");

    const requestB = outcome(w.transport.request("/b"));

    await tick();
    w.lookups[1].resolve(B1);
    await tick();
    w.lookups[0].resolve(A1);

    assert.deepEqual([await requestA, await requestB], ["cancelled", "resolved"]);
    assert.deepEqual(w.http.map((call) => call.token), ["Bearer b-token-1"]);
    assert.equal(w.resets.length, 1, "exactly the A -> B reset, none caused by the stale lookup");
  });
});

describe("SR02-T02: A -> sign-out", () => {
  it("a delayed lookup cannot restore A after sign-out", async () => {
    const w = world();

    w.boundary.applyAuthEvent("user-a", "token-user-a");

    const requestA = outcome(w.transport.request("/a", { method: "POST", body: "{}" }));

    await tick();
    w.boundary.applyAuthEvent(null, null);
    w.lookups[0].resolve(A1);

    assert.equal(await requestA, "cancelled");
    assert.equal(w.http.length, 0);
    assert.equal(w.boundary.snapshot().userId, null);
  });

  it("a request that started after sign-out and resolves null is simply unauthenticated", async () => {
    const w = world();

    w.boundary.applyAuthEvent("user-a", "token-user-a");
    w.boundary.applyAuthEvent(null, null);

    const request = outcome(w.transport.request("/x"));

    await tick();
    w.lookups[0].resolve(null);
    assert.equal(await request, "unauthenticated");
  });
});

describe("SR02-T03: A -> B -> A", () => {
  it("an obsolete request of the first A generation is not valid for the second A", async () => {
    const w = world();

    w.boundary.applyAuthEvent("user-a", "token-user-a");

    const firstA = outcome(w.transport.request("/first", { method: "POST", body: "{}" }));

    await tick();
    w.boundary.applyAuthEvent("user-b", "token-user-b");
    w.boundary.applyAuthEvent("user-a", "token-user-a"); // the user id matches again; the generation does not

    w.lookups[0].resolve(A1);
    assert.equal(await firstA, "cancelled");
    assert.equal(w.http.length, 0, "the stale first-generation mutation was never sent");

    const secondA = outcome(w.transport.request("/second"));

    await tick();
    w.lookups[1].resolve(A2);
    assert.equal(await secondA, "resolved");
    assert.deepEqual(w.http.map((call) => call.token), ["Bearer a-token-2"]);
  });

  it("ownsSession compares generations, not just user ids", () => {
    const boundary = new SessionBoundary(() => undefined);

    boundary.applyAuthEvent("user-a", "token-user-a");

    const firstGeneration = boundary.snapshot();

    assert.equal(boundary.ownsSession(firstGeneration, "user-a"), true);
    assert.equal(boundary.ownsSession(firstGeneration, "user-b"), false, "another user's claim");

    boundary.applyAuthEvent("user-b", "token-user-b");
    boundary.applyAuthEvent("user-a", "token-user-a"); // same user id again, new generation

    assert.equal(boundary.isCurrent(firstGeneration), false);
    assert.equal(boundary.ownsSession(firstGeneration, "user-a"), false);
    assert.equal(boundary.ownsSession(boundary.snapshot(), "user-a"), true);
  });

  it("the epoch advances on every identity change, including the same user's return", () => {
    const boundary = new SessionBoundary(() => undefined);
    const epochs = [boundary.snapshot().epoch];

    for (const user of ["user-a", "user-b", "user-a", null, "user-a"]) {
      boundary.applyAuthEvent(user, user === null ? null : `token-${user}`);
      epochs.push(boundary.snapshot().epoch);
    }

    assert.deepEqual(epochs, [0, 1, 2, 3, 4, 5]);
  });
});

describe("SR02-T04: same-user token refresh", () => {
  it("does not reset, abort or invalidate the active session", async () => {
    const w = world();

    w.boundary.applyAuthEvent("user-a", "token-user-a");
    w.respond.next = (_token, init) => hangUntilAborted(init);

    const request = outcome(w.transport.request("/a"));

    await tick();
    w.lookups[0].resolve(A1);
    await tick();

    const epoch = w.boundary.snapshot().epoch;

    assert.equal(w.boundary.applyAuthEvent("user-a", "token-user-a"), false); // TOKEN_REFRESHED, same user
    assert.equal(w.boundary.snapshot().epoch, epoch);
    assert.equal(w.resets.length, 0);
    assert.equal(w.http[0].signal.aborted, false);

    w.respond.next = async () => json(200, {});
    const next = outcome(w.transport.request("/b"));

    await tick();
    w.lookups[1].resolve(A2); // the refreshed token
    assert.equal(await next, "resolved");
    assert.deepEqual(w.http.map((call) => call.token), ["Bearer a-token-1", "Bearer a-token-2"]);

    w.boundary.applyAuthEvent(null, null);
    await request;
  });
});

describe("SR02-T06: concurrent 401", () => {
  it("an old 401 of A cannot sign out B (through the transport)", async () => {
    const response = deferred<Response>();
    const lab = createAuthLab({ initial: A1, refresh: async () => ({ status: "rejected" }) });
    const transport = createApiTransport({
      baseUrl: "https://api.test",
      boundary: lab.boundary,
      sleep: async () => undefined,
      getSession: async () => A1,
      fetch: () => response.promise,
      onUnauthorized: (used, proof) => lab.lifecycle.handleUnauthorized(used, proof),
    });
    const requestA = outcome(transport.request("/a"));

    await tick();
    lab.event(B1);
    response.resolve(json(401, { detail: "expired" }));

    assert.equal(await requestA, "cancelled");
    assert.equal(lab.lab.refreshCalls, 0, "the stale 401 was dropped before any session logic");
    assert.equal(lab.lab.signOutCalls, 0);
    assert.equal(lab.lab.current, B1);
  });

  it("an old 401 of A cannot sign out an independently refreshed session of A", async () => {
    const lab = createAuthLab({ initial: A1, refresh: async () => ({ status: "rejected" }) });
    const oldProof = lab.proofFor(A1);

    lab.event(A2);
    assert.equal(await lab.lifecycle.handleUnauthorized(A1, oldProof), "stale");
    assert.equal(lab.lab.signOutCalls, 0);
    assert.equal(lab.lab.current, A2);
  });

  it("a rejected refresh that completes after the user switched ends nothing of B", async () => {
    const refresh = deferred<RefreshResult>();
    const lab = createAuthLab({ initial: A1, refresh: () => refresh.promise });
    const pending = lab.lifecycle.handleUnauthorized(A1, lab.proofFor(A1));

    await tick();
    lab.event(B1);
    refresh.resolve({ status: "rejected" });

    assert.equal(await pending, "stale");
    assert.equal(lab.lab.signOutCalls, 0);
    assert.equal(lab.lab.current, B1);
  });
});

describe("SR02: an unadopted session is refused", () => {
  it("a lookup result for a user the boundary has not adopted dispatches nothing", async () => {
    const w = world();

    w.boundary.applyAuthEvent("user-a", "token-user-a");

    const request = outcome(w.transport.request("/x"));

    await tick();
    w.lookups[0].resolve(B1); // getSession() claims B, no auth event said so
    assert.equal(await request, "cancelled");
    assert.equal(w.http.length, 0);
    assert.equal(w.boundary.snapshot().userId, "user-a", "a request cannot change ownership");
  });

  it("never replays a financial mutation: a refused POST is not sent later either", async () => {
    const w = world();

    w.boundary.applyAuthEvent("user-a", "token-user-a");

    const post = outcome(w.transport.request("/api/v1/account-transfers", { method: "POST", body: "{}" }));

    await tick();
    w.boundary.applyAuthEvent("user-b", "token-user-b");
    w.lookups[0].resolve(A1);
    await post;
    w.boundary.applyAuthEvent("user-a", "token-user-a");
    await tick(30);

    assert.equal(w.http.length, 0);
  });
});

describe("SR06: initial session restoration and auth-event ordering", () => {
  type FakeSession = { user: { id: string }; access_token: string };
  const sessionOf = (id: string): FakeSession => ({ user: { id }, access_token: `token-${id}` });

  function coordinatorWorld() {
    const adopted: (string | null)[] = [];
    const published: { session: FakeSession | null; isLoading: boolean }[] = [];
    const authority = {
      applyAuthEvent: (userId: string | null) => {
        adopted.push(userId);

        return true;
      },
      isActive: () => true,
      release: () => undefined,
    };
    const coordinator = createAuthCoordinator<FakeSession>({
      authority,
      publish: (state) => published.push(state),
    });
    const last = () => published[published.length - 1];

    return { coordinator, adopted, published, last };
  }

  it("a stale initial lookup (A) does not overwrite the session an auth event established (B)", () => {
    const w = coordinatorWorld();
    const settle = w.coordinator.beginInitialRestore(); // initial lookup begins

    w.coordinator.handleAuthEvent(sessionOf("user-b")); // auth event: B
    settle(sessionOf("user-a")); // initial lookup resolves with A

    assert.equal(w.last().session?.user.id, "user-b");
    assert.deepEqual(w.adopted, ["user-b"], "the boundary never saw A");
    assert.equal(w.last().isLoading, false);
  });

  it("sign-out during initial restoration wins over the restored session", () => {
    const w = coordinatorWorld();
    const settle = w.coordinator.beginInitialRestore();

    w.coordinator.handleAuthEvent(null);
    settle(sessionOf("user-a"));

    assert.equal(w.last().session, null);
    assert.deepEqual(w.adopted, [null]);
  });

  it("with no event meanwhile, the restored session is adopted and loading ends", () => {
    const w = coordinatorWorld();
    const settle = w.coordinator.beginInitialRestore();

    assert.equal(w.published.length, 0);
    settle(sessionOf("user-a"));

    assert.equal(w.last().session?.user.id, "user-a");
    assert.equal(w.last().isLoading, false);
    assert.deepEqual(w.adopted, ["user-a"]);
  });

  it("the boundary adopts a user before the UI is told about it", () => {
    const order: string[] = [];
    const coordinator = createAuthCoordinator<FakeSession>({
      authority: {
        applyAuthEvent: () => { order.push("boundary"); return true; },
        isActive: () => true,
        release: () => undefined,
      },
      publish: () => { order.push("publish"); },
    });

    coordinator.handleAuthEvent(sessionOf("user-a"));
    assert.deepEqual(order, ["boundary", "publish"]);
  });

  it("events are applied in arrival order, and a restore started later is judged against them", () => {
    const w = coordinatorWorld();

    w.coordinator.handleAuthEvent(sessionOf("user-a"));
    w.coordinator.handleAuthEvent(sessionOf("user-b"));

    const settle = w.coordinator.beginInitialRestore();

    settle(sessionOf("user-c"));
    assert.deepEqual(w.adopted, ["user-a", "user-b", "user-c"]);
  });

  it("a failed initial restore (null) cannot sign out a user an event already signed in", () => {
    const w = coordinatorWorld();
    const settle = w.coordinator.beginInitialRestore();

    w.coordinator.handleAuthEvent(sessionOf("user-b"));
    settle(null);

    assert.equal(w.last().session?.user.id, "user-b");
  });
});
