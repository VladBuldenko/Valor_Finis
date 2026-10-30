// MF2-SR05: what a retired QueryClient does and what it keeps alive.
import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";
import v8 from "node:v8";
import vm from "node:vm";

import { MutationObserver } from "@tanstack/react-query";

import { ApiError } from "../api/api-error.ts";
import { SessionBoundary } from "../api/session-boundary.ts";
import { SessionQueryClient } from "./session-query-client.ts";

// A test-only way to reach V8's collector without a command-line flag.
v8.setFlagsFromString("--expose-gc");
const collect = vm.runInNewContext("gc") as () => void;

const tick = (ms = 5) => new Promise((resolve) => setTimeout(resolve, ms));

function deferred() {
  let resolve: () => void = () => undefined;
  const promise = new Promise<void>((done) => { resolve = done; });

  return { promise, resolve };
}

function setup() {
  const holder = new SessionQueryClient();
  const boundary = new SessionBoundary(() => holder.rotate());

  boundary.applyAuthEvent("user-a");

  return { holder, boundary };
}

const unhandled: unknown[] = [];
const onUnhandled = (reason: unknown) => unhandled.push(reason);

before(() => {
  process.on("unhandledRejection", onUnhandled);
});
after(() => {
  process.off("unhandledRejection", onUnhandled);
});

describe("a retired client is inert", () => {
  it("never starts a new mutation: mutationFn is not called and no callback runs", async () => {
    const { holder, boundary } = setup();
    const retired = holder.get();
    let sent = 0;
    const events: string[] = [];

    boundary.applyAuthEvent("user-b");

    const observer = new MutationObserver(retired, {
      mutationFn: async () => {
        sent += 1;

        return "x";
      },
      onSuccess: () => { events.push("success"); },
      onError: () => { events.push("error"); },
      onSettled: () => { events.push("settled"); },
    });

    void observer.mutate();
    await tick(30);

    assert.equal(sent, 0, "a stale callback cannot send a request under the next user's session");
    assert.deepEqual(events, []);
  });

  it("makes no request for a query: queryFn is replaced and the query fails as cancelled", async () => {
    const { holder, boundary } = setup();
    const retired = holder.get();
    let fetched = 0;

    boundary.applyAuthEvent("user-b");

    await assert.rejects(
      retired.fetchQuery({
        queryKey: ["items"],
        queryFn: async () => {
          fetched += 1;

          return "x";
        },
      }),
      (error: unknown) => error instanceof ApiError && error.kind === "cancelled",
    );
    assert.equal(fetched, 0);
    assert.equal(retired.getQueryData(["items"]), undefined);
  });

  it("the live client is unaffected by the retired one's guards", async () => {
    const { holder, boundary } = setup();

    boundary.applyAuthEvent("user-b");

    const live = holder.get();
    const events: string[] = [];
    const observer = new MutationObserver(live, {
      mutationFn: async () => "ok",
      onSuccess: () => { events.push("success"); },
      onSettled: () => { events.push("settled"); },
    });

    await observer.mutate();
    assert.deepEqual(events, ["success", "settled"]);
    assert.equal(await live.fetchQuery({ queryKey: ["q"], queryFn: async () => 7 }), 7);
  });
});

describe("pending mutations across account changes", () => {
  it("a mutation pending when A signs out never runs a callback; B's mutation settles normally", async () => {
    const { holder, boundary } = setup();
    const gate = deferred();
    const aEvents: string[] = [];
    const bEvents: string[] = [];

    void new MutationObserver(holder.get(), {
      mutationFn: async () => {
        await gate.promise;

        return "a";
      },
      onSuccess: () => { aEvents.push("success"); },
      onError: () => { aEvents.push("error"); },
      onSettled: () => { aEvents.push("settled"); },
    }).mutate();
    await tick();

    boundary.applyAuthEvent(null);
    boundary.applyAuthEvent("user-b");

    await new MutationObserver(holder.get(), {
      mutationFn: async () => "b",
      onSuccess: () => { bEvents.push("success"); },
      onSettled: () => { bEvents.push("settled"); },
    }).mutate();

    gate.resolve(); // A's operation finishes after B already worked
    await tick(30);

    assert.deepEqual(bEvents, ["success", "settled"]);
    assert.deepEqual(aEvents, [], "no reactivation of old callbacks");
  });

  it("a failing pending mutation of a retired client does not call onError either", async () => {
    const { holder, boundary } = setup();
    const gate = deferred();
    const events: string[] = [];

    void new MutationObserver(holder.get(), {
      mutationFn: async () => {
        await gate.promise;
        throw new Error("late failure");
      },
      onError: () => { events.push("error"); },
      onSettled: () => { events.push("settled"); },
    }).mutate();
    await tick();
    boundary.applyAuthEvent("user-b");
    gate.resolve();
    await tick(30);

    assert.deepEqual(events, []);
  });

  it("repeated A -> B -> A changes: nothing is reactivated and nothing is unhandled", async () => {
    const { holder, boundary } = setup();
    const gate = deferred();
    const ran: string[] = [];
    const clients = new Set<unknown>([holder.get()]);

    for (let cycle = 0; cycle < 30; cycle += 1) {
      void new MutationObserver(holder.get(), {
        mutationFn: async () => {
          await gate.promise;

          return cycle;
        },
        onSuccess: () => { ran.push(`success-${cycle}`); },
        onError: () => { ran.push(`error-${cycle}`); },
        onSettled: () => { ran.push(`settled-${cycle}`); },
      }).mutate();
      await tick(1);

      boundary.applyAuthEvent(cycle % 2 === 0 ? "user-b" : "user-a");
      clients.add(holder.get());
    }

    gate.resolve();
    await tick(40);

    // Only the last cycle's mutation belongs to the live client... which was
    // also rotated away from by its own switch, so nothing may have run at all.
    assert.deepEqual(ran, []);
    assert.equal(clients.size, 31, "every session got its own client");
    assert.deepEqual(unhandled, []);
  });
});

describe("resource retention (measured)", () => {
  it("retired clients, their pending mutations and the closures they hold are garbage-collected", async () => {
    const { holder, boundary } = setup();
    const gate = deferred();
    const clientRefs: WeakRef<object>[] = [];
    const payloadRefs: WeakRef<object>[] = [];

    collect();
    const heapBefore = process.memoryUsage().heapUsed;

    // The cycles run in their own function so none of their locals (the last
    // client / payload) stays in this test's frame and masks a real leak.
    async function runCycles(): Promise<void> {
      for (let cycle = 0; cycle < 25; cycle += 1) {
        const payload = { bytes: new Uint8Array(1 << 20), cycle }; // 1 MiB held only by the callback closure
        const client = holder.get();

        clientRefs.push(new WeakRef(client));
        payloadRefs.push(new WeakRef(payload));

        void new MutationObserver(client, {
          mutationFn: async () => {
            await gate.promise;

            return payload.cycle;
          },
          onSuccess: () => payload.bytes.length,
        }).mutate();
        await tick(1);

        boundary.applyAuthEvent(cycle % 2 === 0 ? "user-b" : "user-a"); // retires `client`
      }
    }

    await runCycles();
    gate.resolve(); // every pending mutation now reaches its halted hook
    await tick(40);

    const liveClient = holder.get();

    for (let attempt = 0; attempt < 30; attempt += 1) {
      collect();
      await new Promise((resolve) => setImmediate(resolve));

      if (clientRefs.every((ref) => ref.deref() === undefined)) {
        break;
      }
    }

    const retainedClients = clientRefs.filter((ref) => ref.deref() !== undefined).length;
    const retainedPayloads = payloadRefs.filter((ref) => ref.deref() !== undefined).length;
    const heapAfter = process.memoryUsage().heapUsed;

    assert.ok(liveClient);
    assert.equal(retainedClients, 0, "no retired client is kept alive");
    assert.equal(retainedPayloads, 0, "no retired mutation keeps its callback closure alive");
    assert.ok(
      heapAfter - heapBefore < 8 * 1024 * 1024,
      `heap grew by ${Math.round((heapAfter - heapBefore) / 1024 / 1024)} MiB for 25 MiB of retired payloads`,
    );
  });
});
