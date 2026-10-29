import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { createApiTransport } from "../api/api-transport.ts";
import { hangUntilAborted, json, never } from "../api/api-test-support.ts";
import { ApiError } from "../api/api-error.ts";
import { SessionBoundary } from "../api/session-boundary.ts";
import type { SessionIdentity } from "../api/session-lifecycle.ts";
import { createAppQueryClient } from "./query-client.ts";
import { SessionQueryClient } from "./session-query-client.ts";

const USER_A: SessionIdentity = { userId: "user-a", accessToken: "a-token" };
const USER_B: SessionIdentity = { userId: "user-b", accessToken: "b-token" };

function app(respond: (url: string, init: RequestInit, user: SessionIdentity) => Promise<Response>) {
  const holder = new SessionQueryClient();
  const boundary = new SessionBoundary(() => holder.rotate());
  const state: { session: SessionIdentity | null } = { session: USER_A };
  const urls: string[] = [];
  const transport = createApiTransport({
    baseUrl: "https://api.test",
    fetch: (url, init) => {
      urls.push(url);

      return respond(url, init, state.session ?? USER_A);
    },
    getSession: async () => state.session,
    boundary,
    onUnauthorized: async () => undefined,
    sleep: async () => undefined,
  });

  // The app's real shape: queries share ONE key space across users.
  const load = (key: string, path = `/api/v1/${key}`) =>
    holder.get().fetchQuery({ queryKey: [key], queryFn: () => transport.request<{ owner: string }>(path) });

  return {
    get client() {
      return holder.get();
    },
    holder,
    boundary,
    state,
    transport,
    load,
    urls,
  };
}

const tick = (ms = 5) => new Promise((resolve) => setTimeout(resolve, ms));

describe("query client defaults", () => {
  it("disables TanStack retries so only the transport retries", () => {
    const defaults = createAppQueryClient().getDefaultOptions();

    assert.equal(defaults.queries?.retry, false);
    assert.equal(defaults.mutations?.retry, false);
  });

  it("does not amplify a failing GET: 3 network attempts in total, not 3 x 4", async () => {
    const a = app(async () => json(503, { detail: "down" }));

    await assert.rejects(a.load("accounts"));
    assert.equal(a.urls.length, 3);
  });

  it("does not retry a failing mutation through the query client", async () => {
    const a = app(async () => json(503, { detail: "down" }));
    let sent = 0;

    await assert.rejects(
      a.client
        .getMutationCache()
        .build(a.client, {
          mutationFn: () => {
            sent += 1;

            return a.transport.request("/api/v1/account-transfers", { method: "POST", body: "{}" });
          },
        })
        .execute(undefined),
    );
    assert.equal(sent, 1);
    assert.equal(a.urls.length, 1);
  });
});

describe("cross-user cache isolation", () => {
  it("clears all cached data when the user changes", async () => {
    const a = app(async (_url, _init, user) => json(200, { owner: user.userId }));

    await a.load("accounts");
    await a.load("goals");
    assert.equal(a.client.getQueryCache().getAll().length, 2);

    a.boundary.observe(USER_A.userId);
    assert.equal(a.client.getQueryCache().getAll().length, 2, "same user: nothing is cleared");

    const previous = a.client;

    a.boundary.observe(USER_B.userId);
    assert.equal(a.client.getQueryCache().getAll().length, 0);
    assert.equal(a.client.getQueryData(["accounts"]), undefined);
    assert.notEqual(a.client, previous, "the next user gets a fresh client");
    assert.equal(previous.getQueryCache().getAll().length, 0, "the old client holds nothing either");
  });

  it("clears the cache on sign-out", async () => {
    const a = app(async () => json(200, { owner: "a" }));

    await a.load("accounts");
    a.boundary.observe(null);
    assert.equal(a.client.getQueryCache().getAll().length, 0);
  });

  it("a token refresh of the same user keeps cache and in-flight requests", async () => {
    let release: () => void = () => undefined;
    const a = app(() => new Promise<Response>((resolve) => { release = () => resolve(json(200, { owner: "a" })); }));
    const pending = a.load("accounts");

    await tick();
    a.boundary.observe(USER_A.userId); // refreshed token, same user
    release();

    assert.deepEqual(await pending, { owner: "a" });
    assert.deepEqual(a.client.getQueryData(["accounts"]), { owner: "a" });
  });

  it("aborts user A's in-flight request when the account switches (transport level)", async () => {
    const a = app((_url, init) => hangUntilAborted(init));
    const pending = a.transport.request("/api/v1/accounts");

    await tick();
    a.boundary.observe(USER_B.userId);

    await assert.rejects(pending, (error: unknown) => error instanceof ApiError && error.kind === "cancelled");
  });

  it("drops a late response after the switch even if fetch ignores abort (transport level)", async () => {
    let deliver: () => void = () => undefined;
    const a = app(() => new Promise<Response>((resolve) => { deliver = () => resolve(json(200, { owner: "user-a" })); }));
    const pending = a.transport.request("/api/v1/accounts");

    await tick();
    a.state.session = USER_B;
    a.boundary.observe(USER_B.userId);
    deliver(); // user A's data arrives after user B took over

    await assert.rejects(pending, (error: unknown) => error instanceof ApiError && error.kind === "cancelled");
  });

  it("never caches user A's in-flight query result after the switch (query level)", async () => {
    let deliver: () => void = () => undefined;
    const a = app(() => new Promise<Response>((resolve) => { deliver = () => resolve(json(200, { owner: "user-a" })); }));
    const pendingA = a.load("accounts");

    await tick();
    a.state.session = USER_B;
    a.boundary.observe(USER_B.userId);
    deliver();

    await assert.rejects(pendingA); // cancelled by the reset or refused by the transport
    await tick();
    assert.equal(a.client.getQueryData(["accounts"]), undefined, "user B's cache holds nothing of user A");
    assert.equal(a.client.getQueryCache().getAll().length, 0);
  });

  it("detects a switch the auth listener has not reported yet (self-correcting)", async () => {
    const a = app(async (_url, _init, user) => json(200, { owner: user.userId }));

    await a.load("accounts");
    a.state.session = USER_B; // no boundary.observe() from the auth listener

    await a.transport.request("/api/v1/goals"); // the next request notices the new user

    assert.equal(a.client.getQueryData(["accounts"]), undefined);
  });

  it("user B can load fresh data after the switch, scoped to B", async () => {
    const a = app(async (_url, _init, user) => json(200, { owner: user.userId }));

    await a.load("accounts");
    a.state.session = USER_B;
    a.boundary.observe(USER_B.userId);

    assert.deepEqual(await a.load("accounts"), { owner: "user-b" });
    assert.deepEqual(a.client.getQueryData(["accounts"]), { owner: "user-b" });
  });

  it("a request started after the switch is unaffected by the earlier abort", async () => {
    const a = app((_url, init, user) => (user === USER_A ? hangUntilAborted(init) : Promise.resolve(json(200, { owner: user.userId }))));
    const pendingA = a.load("accounts");

    await tick();
    a.state.session = USER_B;
    a.boundary.observe(USER_B.userId); // what the auth listener does

    const resultB = await a.load("goals");

    assert.deepEqual(resultB, { owner: "user-b" });
    await assert.rejects(pendingA);
  });

  it("rapid A -> B -> A switching never lets the first A request deliver into the last A session", async () => {
    let deliver: () => void = () => undefined;
    const a = app(() => new Promise<Response>((resolve) => { deliver = () => resolve(json(200, { owner: "first-a" })); }));
    const first = a.load("accounts");

    await tick();
    a.boundary.observe(USER_B.userId);
    a.boundary.observe(USER_A.userId);
    deliver();

    await assert.rejects(first);
    await tick();
    assert.equal(a.client.getQueryData(["accounts"]), undefined);
  });

  it("an abandoned request that never answers does not block the reset", async () => {
    const a = app(() => never<Response>());
    const pending = a.load("accounts");

    await tick();
    a.boundary.observe(null);

    await assert.rejects(pending);
    assert.equal(a.client.getQueryCache().getAll().length, 0);
  });
});
