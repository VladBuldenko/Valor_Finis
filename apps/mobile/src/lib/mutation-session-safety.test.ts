// MF2-SR01: mutation callbacks (useMutation onSuccess/onError/onSettled) keep
// running after an account switch. These tests drive TanStack's own
// MutationObserver, which is what useMutation uses, with callbacks shaped like
// the receipt-upload and goal-priorities screens (setQueryData, navigation,
// invalidate/refetch).
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { MutationObserver, type QueryClient } from "@tanstack/react-query";

import { createApiTransport } from "../api/api-transport.ts";
import { hangUntilAborted, json } from "../api/api-test-support.ts";
import { SessionBoundary } from "../api/session-boundary.ts";
import type { SessionIdentity } from "../api/session-lifecycle.ts";
import { SessionQueryClient } from "./session-query-client.ts";

const USER_A: SessionIdentity = { userId: "user-a", accessToken: "a-token" };
const USER_B: SessionIdentity = { userId: "user-b", accessToken: "b-token" };

type Receipt = { id: string; owner: string };

function world(respond: (init: RequestInit, user: SessionIdentity, method: string) => Promise<Response>) {
  const holder = new SessionQueryClient();
  const boundary = new SessionBoundary(() => holder.rotate());
  const state: { session: SessionIdentity } = { session: USER_A };

  boundary.observe(USER_A.userId); // what AuthProvider does when the session loads
  const requests: { method: string; user: string }[] = [];
  const transport = createApiTransport({
    baseUrl: "https://api.test",
    fetch: (_url, init) => {
      requests.push({ method: init.method ?? "GET", user: state.session.userId });

      return respond(init, state.session, init.method ?? "GET");
    },
    getSession: async () => state.session,
    boundary,
    onUnauthorized: async () => undefined,
    sleep: async () => undefined,
  });
  const calls = { success: 0, error: 0, settled: 0, navigated: [] as string[] };

  // A screen's mutation: `client` is what useQueryClient() returned while the
  // screen rendered, captured by the callbacks' closures.
  function screenMutation(
    client: QueryClient,
    options: {
      mutationFn?: () => Promise<Receipt>;
      afterSuccessGap?: () => Promise<void>;
      guardNavigation?: boolean;
    } = {},
  ) {
    const observer = new MutationObserver<Receipt, Error, void>(client, {
      mutationFn:
        options.mutationFn ?? (() => transport.request<Receipt>("/api/v1/receipts/1/process", { method: "POST" })),
      onSuccess: async (receipt) => {
        calls.success += 1;
        await options.afterSuccessGap?.();

        // The receipt-upload shape: seed the cache, navigate, invalidate.
        client.setQueryData(["receipts", "detail", receipt.id], receipt);

        if (!options.guardNavigation || holder.isCurrent(client)) {
          calls.navigated.push(`/receipts/${receipt.id}`);
        }

        void client.invalidateQueries({ queryKey: ["receipts"] });
      },
      onError: () => {
        calls.error += 1;
      },
      onSettled: () => {
        calls.settled += 1;
      },
    });
    const outcome = observer.mutate().then(
      () => "settled" as const,
      () => "settled" as const,
    );

    return { outcome };
  }

  return { holder, boundary, state, transport, requests, calls, screenMutation };
}

const tick = (ms = 10) => new Promise((resolve) => setTimeout(resolve, ms));
const stillPending = (outcome: Promise<string>) =>
  Promise.race([outcome, tick(40).then(() => "pending")]);

function gate() {
  let open: () => void = () => undefined;
  const opened = new Promise<void>((resolve) => { open = resolve; });

  return { opened, open };
}

function switchToB(w: ReturnType<typeof world>) {
  w.state.session = USER_B;
  w.boundary.observe(USER_B.userId);
}

describe("normal operation is unchanged", () => {
  it("runs success and settled callbacks and writes the cache when nothing changed", async () => {
    const w = world(async () => json(200, { id: "r1", owner: "user-a" }));
    const client = w.holder.get();
    const { outcome } = w.screenMutation(client, { guardNavigation: true });

    assert.equal(await outcome, "settled");
    assert.deepEqual([w.calls.success, w.calls.error, w.calls.settled], [1, 0, 1]);
    assert.deepEqual(w.calls.navigated, ["/receipts/r1"]);
    assert.deepEqual(client.getQueryData(["receipts", "detail", "r1"]), { id: "r1", owner: "user-a" });
  });

  it("a token refresh of the same user keeps the client and lets the mutation finish", async () => {
    const release = gate();
    const w = world(async () => {
      await release.opened;

      return json(200, { id: "r1", owner: "user-a" });
    });
    const client = w.holder.get();
    const { outcome } = w.screenMutation(client, { guardNavigation: true });

    await tick();
    w.boundary.observe(USER_A.userId);
    release.open();
    await outcome;

    assert.equal(w.holder.get(), client);
    assert.equal(w.calls.success, 1);
  });
});

describe("a pending request that completes after the account switch", () => {
  for (const [name, ignoresAbort] of [["fetch honours abort", false], ["fetch ignores abort", true]] as const) {
    it(`runs none of A's callbacks and writes nothing for B (${name})`, async () => {
      const release = gate();
      const w = world((init) =>
        ignoresAbort
          ? release.opened.then(() => json(200, { id: "r1", owner: "user-a" }))
          : hangUntilAborted(init),
      );
      const clientA = w.holder.get();
      const { outcome } = w.screenMutation(clientA, { guardNavigation: true });

      await tick();
      switchToB(w);
      release.open();
      await tick();

      assert.equal(await stillPending(outcome), "pending", "the retired mutation never settles");
      assert.deepEqual([w.calls.success, w.calls.error, w.calls.settled], [0, 0, 0]);
      assert.deepEqual(w.calls.navigated, []);
      assert.equal(w.holder.get().getQueryData(["receipts", "detail", "r1"]), undefined);
      assert.equal(w.holder.get().getQueryCache().getAll().length, 0);
      assert.equal(clientA.getQueryCache().getAll().length, 0, "A's own cache was cleared too");
      assert.equal(w.requests.length, 1, "the mutation was never replayed");
    });
  }

  it("does not replay the mutation for B, and B's own mutation is unaffected", async () => {
    const w = world(async (_init, user) => json(200, { id: `r-${user.userId}`, owner: user.userId }));
    const gateA = gate();
    const slowA = () => gateA.opened.then(() => ({ id: "r-a", owner: "user-a" }));
    const a = w.screenMutation(w.holder.get(), { mutationFn: slowA });

    await tick();
    switchToB(w);

    const b = w.screenMutation(w.holder.get(), { guardNavigation: true });

    assert.equal(await b.outcome, "settled");
    gateA.open();
    await tick();

    assert.equal(await stillPending(a.outcome), "pending");
    assert.equal(w.requests.filter((r) => r.method === "POST").length, 1, "only B's own POST was sent");
    assert.equal(w.calls.success, 1);
    assert.deepEqual(w.calls.navigated, ["/receipts/r-user-b"]);
    assert.equal(w.holder.get().getQueryData(["receipts", "detail", "r-a"]), undefined);
  });

  it("stays halted when the first user signs back in (A -> B -> A)", async () => {
    const release = gate();
    const w = world(() => release.opened.then(() => json(200, { id: "r1", owner: "first-a" })));
    const { outcome } = w.screenMutation(w.holder.get(), { guardNavigation: true });

    await tick();
    w.boundary.observe(USER_B.userId);
    w.boundary.observe(USER_A.userId);
    release.open();
    await tick();

    assert.equal(await stillPending(outcome), "pending");
    assert.equal(w.calls.success + w.calls.error + w.calls.settled, 0);
    assert.equal(w.holder.get().getQueryCache().getAll().length, 0);
  });
});

describe("a request that completed before the switch but whose processing is delayed", () => {
  it("stops before the callbacks when the delay is between the HTTP answer and the callbacks", async () => {
    const gap = gate();
    const w = world(async () => json(200, { id: "r1", owner: "user-a" }));
    const { outcome } = w.screenMutation(w.holder.get(), {
      guardNavigation: true,
      mutationFn: async () => {
        const receipt = await w.transport.request<Receipt>("/api/v1/receipts/1/process", { method: "POST" });

        await gap.opened; // post-processing paused after the HTTP request finished

        return receipt;
      },
    });

    await tick();
    switchToB(w);
    gap.open();
    await tick();

    assert.equal(await stillPending(outcome), "pending");
    assert.deepEqual([w.calls.success, w.calls.error, w.calls.settled], [0, 0, 0]);
    assert.deepEqual(w.calls.navigated, []);
    assert.equal(w.holder.get().getQueryCache().getAll().length, 0);
    assert.equal(w.requests.length, 1);
  });

  it("a callback body already paused cannot write into B's cache (it holds A's retired client)", async () => {
    const gap = gate();
    const w = world(async () => json(200, { id: "r1", owner: "user-a" }));
    const clientA = w.holder.get();
    const { outcome } = w.screenMutation(clientA, {
      guardNavigation: true,
      afterSuccessGap: () => gap.opened, // onSuccess started; paused before its cache writes
    });

    await tick();
    assert.equal(w.calls.success, 1, "the callback had started before the switch");
    switchToB(w);
    gap.open();
    await tick(); // the body finishes; the mutation then halts at onSettled

    assert.equal(await stillPending(outcome), "pending");
    assert.equal(w.holder.get().getQueryData(["receipts", "detail", "r1"]), undefined, "B's cache has nothing of A");
    assert.equal(w.holder.get().getQueryCache().getAll().length, 0);
    assert.equal(w.requests.length, 1, "no refetch or replay under B's session");
    assert.equal(w.holder.get().isFetching(), 0);
  });

  it("the paused callback's navigation is suppressed only if it checks the client is current", async () => {
    for (const guardNavigation of [true, false]) {
      const gap = gate();
      const w = world(async () => json(200, { id: "r1", owner: "user-a" }));
      w.screenMutation(w.holder.get(), {
        guardNavigation,
        afterSuccessGap: () => gap.opened,
      });

      await tick();
      switchToB(w);
      gap.open();
      await tick();

      assert.deepEqual(w.calls.navigated, guardNavigation ? [] : ["/receipts/r1"]);
    }
  });

  it("isCurrent is false for a retired client and true for its successor", () => {
    const holder = new SessionQueryClient();
    const first = holder.get();

    assert.equal(holder.isCurrent(first), true);
    holder.rotate();
    assert.equal(holder.isCurrent(first), false);
    assert.equal(holder.isCurrent(holder.get()), true);
  });

  it("notifies subscribers when the client rotates (the provider re-renders)", () => {
    const holder = new SessionQueryClient();
    let notified = 0;
    const unsubscribe = holder.subscribe(() => { notified += 1; });

    holder.rotate();
    unsubscribe();
    holder.rotate();
    assert.equal(notified, 1);
  });
});
