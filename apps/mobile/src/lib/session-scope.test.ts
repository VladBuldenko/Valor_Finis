// MF2-SR03: mounted React tests with the real TanStack hooks. They prove the
// observer lifecycle of SessionScope; they do not cover AuthProvider, Supabase
// or Expo Router (see docs/modules/mobile-api-client.md).
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  act,
  createMountedWorld,
  deferred,
  USER_A,
  USER_A_SECOND,
  USER_B,
} from "./mounted-test-support.ts";

async function unmount(renderer: { unmount: () => void }): Promise<void> {
  await act(async () => {
    renderer.unmount();
  });
}

describe("SR03-T01: direct A -> B", () => {
  it("retires A's subtree, gives B live observers, and keeps A's late work out of B", async () => {
    const w = createMountedWorld();
    const gateA = deferred<void>();

    w.gates.set("user-a", gateA);

    const renderer = await w.mount();
    const first = w.current();

    assert.equal(first.id, 1);
    assert.equal(first.client, w.holder.get());
    assert.equal(first.query?.data?.owner, "user-a");

    await w.startMutation(); // A's mutation is in flight (its POST waits on the gate)
    assert.equal(w.http.filter((call) => call.method === "POST").length, 1);

    await w.authEvent(USER_B);

    assert.equal(first.mounted, false, "A's subtree was retired");
    assert.equal(w.instances.length, 2);

    const second = w.current();

    assert.equal(second.id, 2);
    assert.notEqual(second.client, first.client, "B has a different QueryClient");
    assert.equal(second.client, w.holder.get(), "B's hooks are bound to the live client");
    assert.equal(second.query?.data?.owner, "user-b", "B's query settled");

    await w.startMutation();
    assert.equal(second.mutation?.status, "success", "B's mutation settled");
    assert.deepEqual(second.events, ["success:user-b", "settled"]);

    gateA.resolve(); // A's operation finishes now
    await w.settle(40);

    assert.deepEqual(first.events, [], "none of A's callbacks ran");
    assert.deepEqual(w.navigations, [{ instance: 2, path: "/receipts/r-user-b" }], "only B navigated, to B's own receipt");
    assert.equal(w.holder.get().getQueryData(["receipts", "detail", "r-user-a"]), undefined);
    assert.equal(w.http.filter((call) => call.method === "POST").length, 2, "one POST per user, nothing replayed");

    await unmount(renderer);
  });

  it("prior failure: an UNKEYED provider keeps A's observers and B's mutation never settles", async () => {
    const w = createMountedWorld();
    const renderer = await w.mount(w.unkeyedScope);
    const first = w.current();

    await w.authEvent(USER_B);

    assert.equal(w.instances.length, 1, "no remount: the same component instance survives the switch");
    assert.equal(first.mounted, true);

    await w.startMutation();
    assert.notEqual(first.mutation?.status, "success", "B's mutation is stuck on the retired client");
    assert.deepEqual(first.events, [], "and no callback of B's flow ever runs");

    await unmount(renderer);
  });
});

describe("SR03-T02: A -> null -> B", () => {
  it("rotates on sign-out, and B starts with fresh observers", async () => {
    const w = createMountedWorld();
    const gateA = deferred<void>();

    w.gates.set("user-a", gateA);

    const renderer = await w.mount();
    const first = w.current();

    await w.startMutation();
    await w.authEvent(null); // sign-out with A's mutation pending

    assert.equal(first.mounted, false);
    assert.equal(w.instances.length, 1, "no authenticated screen exists while signed out");
    assert.equal(w.holder.isCurrent(first.client), false);

    await w.authEvent(USER_B);

    const third = w.current();

    assert.equal(w.instances.length, 2, "B gets a brand-new screen instance");
    assert.notEqual(third.client, first.client);
    assert.equal(third.client, w.holder.get());
    assert.equal(third.query?.data?.owner, "user-b");

    await w.startMutation();
    assert.equal(third.mutation?.status, "success");

    gateA.resolve();
    await w.settle(40);

    assert.deepEqual(first.events, []);
    assert.deepEqual(w.navigations.map((entry) => entry.instance), [third.id]);
    assert.equal(w.holder.get().getQueryData(["receipts", "detail", "r-user-a"]), undefined);

    await unmount(renderer);
  });
});

describe("SR03-T03: A -> B -> A", () => {
  it("the second A is a new logical session and never reuses retired state", async () => {
    const w = createMountedWorld();
    const gateFirstA = deferred<void>();

    w.gates.set("user-a", gateFirstA);

    const renderer = await w.mount();
    const firstA = w.current();
    const firstClient = firstA.client;
    const firstData = firstA.query?.data;

    await w.startMutation();
    await w.authEvent(USER_B);

    const forB = w.current();

    await w.authEvent(USER_A_SECOND); // A returns

    const secondA = w.current();

    assert.equal(w.instances.length, 3);
    assert.notEqual(secondA.client, firstClient, "not the first A's client");
    assert.notEqual(secondA.client, forB.client);
    assert.equal(secondA.client, w.holder.get());
    assert.notEqual(secondA.query?.data, firstData, "A's data was fetched anew, not resurrected");
    assert.equal(secondA.query?.data?.owner, "user-a");

    gateFirstA.resolve(); // the FIRST A's request completes while A is signed in again
    await w.settle(40);

    assert.deepEqual(firstA.events, [], "the first A generation's callbacks stay dead");
    assert.deepEqual(secondA.events, []);
    assert.equal(w.navigations.length, 0);

    gateFirstA.resolve();
    w.gates.delete("user-a");
    await w.startMutation();
    assert.equal(secondA.mutation?.status, "success", "the second A can run its own mutation");

    await unmount(renderer);
  });
});

describe("SR03-T04: same-user token refresh", () => {
  it("does not remount, rotate or reset the UI", async () => {
    const w = createMountedWorld();
    const gate = deferred<void>();

    w.gates.set("user-a", gate);

    const renderer = await w.mount();
    const first = w.current();
    const client = first.client;

    await w.startMutation();
    await w.authEvent(USER_A_SECOND); // TOKEN_REFRESHED: same user, new access token

    assert.equal(w.instances.length, 1, "no new component instance");
    assert.equal(first.mounted, true);
    assert.equal(w.holder.get(), client, "same QueryClient");

    gate.resolve();
    await w.settle(40);

    assert.deepEqual(first.events, ["success:user-a", "settled"], "the in-flight mutation finishes normally");
    assert.deepEqual(w.navigations, [{ instance: 1, path: "/receipts/r-user-a" }]);
    assert.equal(w.http.filter((call) => call.method === "POST").length, 1);

    await unmount(renderer);
    assert.equal(USER_A.userId, USER_A_SECOND.userId);
  });
});
