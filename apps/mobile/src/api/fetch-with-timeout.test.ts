// MF2-SR10: the request deadline covers dispatch, headers AND the body, and is
// enforced even when the underlying fetch ignores AbortSignal.
import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";

import { createFetchWithTimeout } from "./fetch-with-timeout.ts";

const DEADLINE = 25;
const unhandled: unknown[] = [];
const onUnhandled = (reason: unknown) => unhandled.push(reason);

before(() => {
  process.on("unhandledRejection", onUnhandled);
});
after(() => {
  process.off("unhandledRejection", onUnhandled);
});

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function neverEndingBody(signal?: AbortSignal | null, onCancel?: () => void): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      signal?.addEventListener("abort", () => controller.error(new Error("aborted")), { once: true });
    },
    cancel: onCancel,
  });

  return new Response(stream, { status: 200 });
}

// The per-test timeout makes a regression (a promise that never settles) fail instead of hang.
describe("createFetchWithTimeout (SR10)", { timeout: 3000 }, () => {
  it("settles by the deadline when fetch never resolves and ignores abort", async () => {
    const wrapped = createFetchWithTimeout((() => new Promise<Response>(() => undefined)) as typeof fetch, DEADLINE);
    const startedAt = Date.now();
    const result = wrapped("https://x.test").then(() => "ok", (error: Error) => error.name);

    assert.equal(await result, "TimeoutError");
    assert.ok(Date.now() - startedAt < DEADLINE * 4);
  });

  it("settles by the deadline when headers arrive but the body never ends (stream ignores abort)", async () => {
    const wrapped = createFetchWithTimeout((async () => neverEndingBody()) as typeof fetch, DEADLINE);
    const response = wrapped("https://x.test").then((r) => r.json(), (error: Error) => error.name);

    assert.equal(await response, "TimeoutError");
  });

  it("aborts the underlying request on timeout (abort-aware fetch)", async () => {
    let aborted = false;
    const base = ((_input: unknown, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          aborted = true;
          reject(new DOMException("aborted", "AbortError"));
        });
      })) as typeof fetch;

    assert.equal(await createFetchWithTimeout(base, DEADLINE)("https://x.test").then(() => "ok", (e: Error) => e.name), "TimeoutError");
    await sleep(5);
    assert.equal(aborted, true);
  });

  it("returns a successful JSON response intact (status, headers, body) and clears its timer", async () => {
    const base = (async () =>
      new Response(JSON.stringify({ a: 1 }), { status: 201, statusText: "Created", headers: { "X-Test": "yes", "Content-Type": "application/json" } })) as typeof fetch;
    const response = await createFetchWithTimeout(base, DEADLINE)("https://x.test");

    assert.equal(response.status, 201);
    assert.equal(response.statusText, "Created");
    assert.equal(response.headers.get("X-Test"), "yes");
    assert.deepEqual(await response.json(), { a: 1 });
    await sleep(DEADLINE * 2); // a leaked timer would abort the controller / fail loudly
    assert.deepEqual(unhandled, []);
  });

  it("keeps 204 (no body) and error statuses with their bodies", async () => {
    const wrapped = createFetchWithTimeout(
      (async (input: unknown) =>
        String(input).endsWith("204") ? new Response(null, { status: 204 }) : new Response('{"code":"x"}', { status: 400 })) as typeof fetch,
      DEADLINE,
    );
    const empty = await wrapped("https://x.test/204");
    const bad = await wrapped("https://x.test/400");

    assert.equal(empty.status, 204);
    assert.equal(await empty.text(), "");
    assert.equal(bad.status, 400);
    assert.deepEqual(await bad.json(), { code: "x" });
  });

  it("passes a genuine network error through unchanged", async () => {
    const boom = new TypeError("Network request failed");
    const wrapped = createFetchWithTimeout((async () => { throw boom; }) as typeof fetch, DEADLINE);

    await assert.rejects(wrapped("https://x.test"), (error) => error === boom);
  });

  it("caller abort settles at once even if fetch ignores the signal, and a pre-aborted signal never dispatches", async () => {
    let dispatched = 0;
    const base = (() => { dispatched += 1; return new Promise<Response>(() => undefined); }) as typeof fetch;
    const wrapped = createFetchWithTimeout(base, 10_000);
    const caller = new AbortController();
    const pending = wrapped("https://x.test", { signal: caller.signal }).then(() => "ok", (e: Error) => e.name);

    caller.abort();
    assert.equal(await pending, "AbortError");

    const pre = new AbortController();

    pre.abort();
    assert.equal(await wrapped("https://x.test", { signal: pre.signal }).then(() => "ok", (e: Error) => e.name), "AbortError");
    assert.equal(dispatched, 1);
  });

  it("removes its listener from the caller signal and leaves no timer behind", async () => {
    const caller = new AbortController();
    let removed = 0;
    const original = caller.signal.removeEventListener.bind(caller.signal);

    caller.signal.removeEventListener = ((...args: Parameters<typeof original>) => { removed += 1; return original(...args); }) as typeof original;
    await createFetchWithTimeout((async () => new Response("{}")) as typeof fetch, 10_000)("https://x.test", { signal: caller.signal });
    assert.equal(removed, 1);
    // The 10 s timer was cleared: the process can exit (node:test would hang otherwise).
  });

  it("late fetch rejection and late body completion after the timeout are swallowed", async () => {
    let rejectFetch: (reason: Error) => void = () => undefined;
    const lateFetch = createFetchWithTimeout(
      (() => new Promise<Response>((_resolve, reject) => { rejectFetch = reject; })) as typeof fetch,
      DEADLINE,
    );

    assert.equal(await lateFetch("https://x.test").then(() => "ok", (e: Error) => e.name), "TimeoutError");
    rejectFetch(new Error("late network failure"));

    let finishBody: () => void = () => undefined;
    let resolved = 0;
    const lateBody = createFetchWithTimeout(
      (async () => {
        const body = new ReadableStream<Uint8Array>({ start(controller) { finishBody = () => { controller.enqueue(new TextEncoder().encode("{}")); controller.close(); }; } });

        return new Response(body);
      }) as typeof fetch,
      DEADLINE,
    );

    assert.equal(await lateBody("https://x.test").then(() => { resolved += 1; return "ok"; }, (e: Error) => e.name), "TimeoutError");
    finishBody();
    await sleep(DEADLINE);
    assert.equal(resolved, 0);
    assert.deepEqual(unhandled, []);
  });

  it("late successful fetch resolution after the timeout does not resurrect the request", async () => {
    let resolveFetch: (response: Response) => void = () => undefined;
    const wrapped = createFetchWithTimeout((() => new Promise<Response>((resolve) => { resolveFetch = resolve; })) as typeof fetch, DEADLINE);
    let fulfilled = 0;

    assert.equal(await wrapped("https://x.test").then(() => { fulfilled += 1; return "ok"; }, (e: Error) => e.name), "TimeoutError");
    resolveFetch(new Response("{}"));
    await sleep(DEADLINE);
    assert.equal(fulfilled, 0);
    assert.deepEqual(unhandled, []);
  });
});
