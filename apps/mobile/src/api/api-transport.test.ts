import assert from "node:assert/strict";
import { getEventListeners } from "node:events";
import { describe, it } from "node:test";

import { ApiError, type ApiErrorKind } from "./api-error.ts";
import { DEFAULT_TRANSPORT_POLICY } from "./api-transport.ts";
import { hangUntilAborted, json, makeHarness, never } from "./api-test-support.ts";

async function rejection(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    assert.ok(error instanceof ApiError, `expected ApiError, got ${String(error)}`);

    return error;
  }

  throw new Error("expected the request to fail");
}

function timeoutCount(): number {
  return process.getActiveResourcesInfo().filter((name) => name === "Timeout").length;
}

describe("default policy", () => {
  it("uses 30 s for standard and 60 s for multipart requests", () => {
    assert.equal(DEFAULT_TRANSPORT_POLICY.timeoutMs, 30_000);
    assert.equal(DEFAULT_TRANSPORT_POLICY.multipartTimeoutMs, 60_000);
  });
});

describe("success paths", () => {
  it("returns parsed JSON and sends bearer token and JSON content type", async () => {
    const h = makeHarness({ respond: async () => json(200, { id: "a" }) });

    assert.deepEqual(await h.transport.request("/api/v1/things"), { id: "a" });
    assert.equal(h.calls[0].url, "https://api.test/api/v1/things");
    assert.equal(h.calls[0].headers.get("Authorization"), "Bearer token-1");
    assert.equal(h.calls[0].headers.get("Content-Type"), "application/json");
  });

  it("resolves a 204 with undefined", async () => {
    const h = makeHarness({ respond: async () => new Response(null, { status: 204 }) });

    assert.equal(await h.transport.request("/x", { method: "DELETE" }), undefined);
  });

  it("keeps a caller-supplied Content-Type for non-multipart bodies", async () => {
    const h = makeHarness({ respond: async () => json(200, {}) });

    await h.transport.request("/x", {
      method: "POST",
      headers: { "content-type": "application/vnd.test+json" },
      body: "{}",
    });

    assert.equal(h.calls[0].headers.get("Content-Type"), "application/vnd.test+json");
  });
});

describe("authorization header", () => {
  const evil = "Bearer attacker";
  const variants: [string, HeadersInit][] = [
    ["plain object, exact case", { Authorization: evil }],
    ["plain object, lower case", { authorization: evil }],
    ["Headers instance", new Headers({ Authorization: evil })],
    ["tuple array", [["AUTHORIZATION", evil]]],
  ];

  for (const [name, headers] of variants) {
    it(`cannot be overridden by the caller (${name})`, async () => {
      const h = makeHarness({ respond: async () => json(200, {}) });

      await h.transport.request("/x", { headers });

      assert.equal(h.calls[0].headers.get("Authorization"), "Bearer token-1");
    });
  }

  it("sends no request without a session", async () => {
    const h = makeHarness({ respond: async () => json(200, {}), session: async () => null });
    const error = await rejection(h.transport.request("/x"));

    assert.equal(error.kind, "unauthenticated");
    assert.equal(error.message, "User is not authenticated.");
    assert.equal(h.calls.length, 0);
  });
});

describe("HTTP error parsing", () => {
  it("keeps the historical message and exposes status, detail and code", async () => {
    const body = { detail: "Archived account cannot receive new transactions.", code: "account_archived" };
    const h = makeHarness({ respond: async () => json(409, body) });
    const error = await rejection(h.transport.request("/x", { method: "POST" }));

    assert.equal(error.kind, "http");
    assert.equal(error.status, 409);
    assert.equal(error.detail, "Archived account cannot receive new transactions.");
    assert.equal(error.code, "account_archived");
    assert.equal(error.message, `API request failed: 409 ${JSON.stringify(body)}`);
    assert.equal(error.body, JSON.stringify(body));
  });

  it("has a null detail for a 422 validation list and keeps the body", async () => {
    const body = { detail: [{ msg: "Field required", loc: ["body", "title"] }] };
    const h = makeHarness({ respond: async () => json(422, body) });
    const error = await rejection(h.transport.request("/x", { method: "POST" }));

    assert.equal(error.status, 422);
    assert.equal(error.detail, null);
    assert.equal(error.body, JSON.stringify(body));
  });

  it("ignores a code that is not a stable snake_case identifier", async () => {
    const h = makeHarness({ respond: async () => json(400, { detail: "x", code: "Bad Code!" }) });

    assert.equal((await rejection(h.transport.request("/x", { method: "POST" }))).code, null);
  });

  it("tolerates a non-JSON error body", async () => {
    const h = makeHarness({ respond: async () => new Response("<html>oops</html>", { status: 500 }) });
    const error = await rejection(h.transport.request("/x", { method: "POST" }));

    assert.equal(error.kind, "http");
    assert.equal(error.detail, null);
    assert.equal(error.message, "API request failed: 500 <html>oops</html>");
  });

  it("reports a 2xx body that is not JSON as malformed_response", async () => {
    const h = makeHarness({ respond: async () => new Response("not json", { status: 200 }) });
    const error = await rejection(h.transport.request("/x", { method: "POST" }));

    assert.equal(error.kind, "malformed_response");
    assert.equal(error.status, 200);
  });

  it("reports a failing fetch as a network error (message of the cause kept)", async () => {
    const h = makeHarness({
      respond: async () => {
        throw new TypeError("Network request failed");
      },
    });
    const error = await rejection(h.transport.request("/x", { method: "POST" }));

    assert.equal(error.kind, "network");
    assert.equal(error.status, null);
    assert.equal(error.message, "Network request failed");
  });
});

describe("timeout and cancellation", () => {
  it("times out a request whose fetch honours the signal", async () => {
    const h = makeHarness({
      respond: async (call) => hangUntilAborted(call.init),
      policy: { timeoutMs: 30 },
    });
    const error = await rejection(h.transport.request("/x"));

    assert.equal(error.kind, "timeout");
    assert.equal(h.calls.length, 1);
  });

  it("times out even when fetch ignores the signal (hard bound)", async () => {
    const h = makeHarness({ respond: () => never<Response>(), policy: { timeoutMs: 30 } });

    assert.equal((await rejection(h.transport.request("/x"))).kind, "timeout");
  });

  it("covers reading the response body in the deadline", async () => {
    const stalledBody = {
      ok: true,
      status: 200,
      json: () => never<unknown>(),
      text: () => never<string>(),
      body: null,
    } as unknown as Response;
    const h = makeHarness({ respond: async () => stalledBody, policy: { timeoutMs: 30 } });

    assert.equal((await rejection(h.transport.request("/x"))).kind, "timeout");
  });

  it("covers reading an error body in the deadline", async () => {
    const stalledBody = {
      ok: false,
      status: 500,
      json: () => never<unknown>(),
      text: () => never<string>(),
      body: null,
    } as unknown as Response;
    const h = makeHarness({ respond: async () => stalledBody, policy: { timeoutMs: 30 } });

    assert.equal((await rejection(h.transport.request("/x", { method: "POST" }))).kind, "timeout");
  });

  it("covers a stalled session lookup in the deadline", async () => {
    const h = makeHarness({
      respond: async () => json(200, {}),
      session: () => never(),
      policy: { timeoutMs: 30 },
    });

    assert.equal((await rejection(h.transport.request("/x"))).kind, "timeout");
    assert.equal(h.calls.length, 0);
  });

  it("applies one overall deadline across retries (it is not reset per attempt)", async () => {
    const h = makeHarness({
      respond: async () => json(503, { detail: "down" }),
      policy: { timeoutMs: 120, maxRetries: 50, retryDelaysMs: [40] },
      sleep: (ms, signal) =>
        new Promise((resolve, reject) => {
          const timer = setTimeout(resolve, ms);

          signal.addEventListener("abort", () => {
            clearTimeout(timer);
            reject(new Error("aborted"));
          });
        }),
    });
    const startedAt = Date.now();
    const error = await rejection(h.transport.request("/x"));

    assert.ok(Date.now() - startedAt < 400, "ended near the deadline, not after 50 retries");
    assert.ok(h.calls.length >= 2 && h.calls.length <= 4, `attempts: ${h.calls.length}`);
    assert.ok(error.kind === "http" || error.kind === "timeout");
  });

  it("honours a per-call timeout override", async () => {
    const h = makeHarness({ respond: () => never<Response>(), policy: { timeoutMs: 5_000 } });
    const startedAt = Date.now();
    const error = await rejection(h.transport.request("/x", { timeoutMs: 30 }));

    assert.equal(error.kind, "timeout");
    assert.ok(Date.now() - startedAt < 1_000);
  });

  it("cancels on the caller's signal and aborts the fetch signal", async () => {
    const h = makeHarness({ respond: async (call) => hangUntilAborted(call.init) });
    const controller = new AbortController();
    const pending = h.transport.request("/x", { signal: controller.signal });

    await new Promise((resolve) => setTimeout(resolve, 10));
    controller.abort();

    assert.equal((await rejection(pending)).kind, "cancelled");
    assert.equal(h.calls[0].init.signal?.aborted, true);
  });

  it("does not touch the network when the caller's signal is already aborted", async () => {
    const h = makeHarness({ respond: async () => json(200, {}) });
    const error = await rejection(h.transport.request("/x", { signal: AbortSignal.abort() }));

    assert.equal(error.kind, "cancelled");
    assert.equal(h.calls.length, 0);
  });

  it("does not retry a timeout or a cancellation", async () => {
    const timeout = makeHarness({ respond: () => never<Response>(), policy: { timeoutMs: 20 } });

    await rejection(timeout.transport.request("/x"));
    assert.equal(timeout.calls.length, 1);

    const cancel = makeHarness({ respond: async (call) => hangUntilAborted(call.init) });
    const controller = new AbortController();
    const pending = cancel.transport.request("/x", { signal: controller.signal });

    setTimeout(() => controller.abort(), 10);
    await rejection(pending);
    assert.equal(cancel.calls.length, 1);
  });

  it("removes every listener and timer afterwards", async () => {
    const baseline = timeoutCount();
    const caller = new AbortController();
    const h = makeHarness({ respond: async () => json(200, {}) });

    await h.transport.request("/ok", { signal: caller.signal });
    assert.equal(getEventListeners(caller.signal, "abort").length, 0);
    assert.equal(getEventListeners(h.boundary.snapshot().signal, "abort").length, 0);

    const failing = makeHarness({ respond: async () => json(500, {}) });

    await rejection(failing.transport.request("/err", { method: "POST", signal: caller.signal }));
    assert.equal(getEventListeners(caller.signal, "abort").length, 0);
    assert.equal(getEventListeners(failing.boundary.snapshot().signal, "abort").length, 0);

    const timing = makeHarness({ respond: () => never<Response>(), policy: { timeoutMs: 20 } });

    await rejection(timing.transport.request("/slow", { signal: caller.signal }));
    assert.equal(getEventListeners(caller.signal, "abort").length, 0);
    assert.equal(getEventListeners(timing.boundary.snapshot().signal, "abort").length, 0);

    assert.equal(timeoutCount(), baseline, "no deadline timer left running");
  });
});

describe("late results", () => {
  it("refuses a result that was already read when the user changed (microtask window)", async () => {
    let boundaryOf: (userId: string) => void = () => undefined;
    const readyResponse = () => {
      let settle: (value: unknown) => void = () => undefined;
      const parsed = new Promise<unknown>((resolve) => { settle = resolve; });

      // Attached before the transport's own reaction, so it runs first and
      // queues the user change between "value received" and "value used".
      void parsed.then(() => queueMicrotask(() => boundaryOf("user-2")));
      setTimeout(() => settle({ owner: "user-1" }), 5);

      return { ok: true, status: 200, json: () => parsed, text: async () => "", body: null } as unknown as Response;
    };
    const h = makeHarness({ respond: async () => readyResponse() });

    boundaryOf = (userId) => {
      h.boundary.observe(userId);
    };

    const error = await rejection(h.transport.request("/x"));

    assert.equal(error.kind, "cancelled");
  });
});

describe("GET retry policy", () => {
  it("retries a transient 503 and then succeeds, with bounded delays", async () => {
    const h = makeHarness({
      respond: async (_call, attempt) => (attempt < 3 ? json(503, {}) : json(200, { ok: true })),
    });

    assert.deepEqual(await h.transport.request("/x"), { ok: true });
    assert.equal(h.calls.length, 3);
    assert.deepEqual(h.sleeps, [300, 900]);
  });

  for (const status of [502, 503, 504]) {
    it(`stops after 1 + maxRetries attempts on persistent ${status}`, async () => {
      const h = makeHarness({ respond: async () => json(status, { detail: "bad gateway" }) });
      const error = await rejection(h.transport.request("/x"));

      assert.equal(h.calls.length, 3);
      assert.equal(error.status, status);
    });
  }

  it("retries a network failure, then succeeds", async () => {
    const h = makeHarness({
      respond: async (_call, attempt) => {
        if (attempt === 1) {
          throw new TypeError("Network request failed");
        }

        return json(200, { ok: 1 });
      },
    });

    assert.deepEqual(await h.transport.request("/x"), { ok: 1 });
    assert.equal(h.calls.length, 2);
  });

  it("gives up on a persistent network failure after 3 attempts", async () => {
    const h = makeHarness({
      respond: async () => {
        throw new TypeError("Network request failed");
      },
    });
    const error = await rejection(h.transport.request("/x"));

    assert.equal(error.kind, "network");
    assert.equal(h.calls.length, 3);
  });

  it("respects a custom maxRetries of 0", async () => {
    const h = makeHarness({ respond: async () => json(503, {}), policy: { maxRetries: 0 } });

    await rejection(h.transport.request("/x"));
    assert.equal(h.calls.length, 1);
  });

  const neverRetried: [number, ApiErrorKind][] = [
    [400, "http"],
    [401, "unauthorized"],
    [403, "http"],
    [404, "http"],
    [409, "http"],
    [422, "http"],
    [500, "http"],
    [501, "http"],
  ];

  for (const [status, kind] of neverRetried) {
    it(`never retries HTTP ${status} (exactly one network attempt)`, async () => {
      const h = makeHarness({ respond: async () => json(status, { detail: "no" }) });
      const error = await rejection(h.transport.request("/x"));

      assert.equal(error.kind, kind);
      assert.equal(h.calls.length, 1);
    });
  }

  it("does not retry when the wait would not fit in the deadline", async () => {
    const h = makeHarness({
      respond: async () => json(503, {}),
      policy: { timeoutMs: 100, retryDelaysMs: [500] },
    });
    const error = await rejection(h.transport.request("/x"));

    assert.equal(h.calls.length, 1);
    assert.equal(error.status, 503);
  });
});

describe("financial mutations are never repeated by the transport", () => {
  const methods = ["POST", "PATCH", "PUT", "DELETE"];

  for (const method of methods) {
    for (const failure of ["503", "502", "504", "network"]) {
      it(`${method} gets one attempt after ${failure}`, async () => {
        const h = makeHarness({
          respond: async () => {
            if (failure === "network") {
              throw new TypeError("Network request failed");
            }

            return json(Number(failure), { detail: "transient" });
          },
        });
        const error = await rejection(
          h.transport.request("/api/v1/account-transfers", { method, body: "{}" }),
        );

        assert.equal(h.calls.length, 1);
        assert.deepEqual(h.sleeps, []);
        assert.equal(error.kind, failure === "network" ? "network" : "http");
      });
    }
  }

  it("treats the method case-insensitively", async () => {
    const h = makeHarness({ respond: async () => json(503, {}) });

    await rejection(h.transport.request("/x", { method: "post", body: "{}" }));
    assert.equal(h.calls.length, 1);
  });

  it("does not replay a mutation after a timeout either", async () => {
    const h = makeHarness({ respond: () => never<Response>(), policy: { timeoutMs: 20 } });

    await rejection(h.transport.request("/x", { method: "POST", body: "{}" }));
    assert.equal(h.calls.length, 1);
  });
});

describe("multipart", () => {
  function upload(): FormData {
    const form = new FormData();

    form.append("file", new Blob(["receipt"], { type: "image/jpeg" }), "receipt.jpg");

    return form;
  }

  it("passes the FormData through untouched and lets the runtime set the boundary", async () => {
    const h = makeHarness({ respond: async () => json(201, { id: "r1" }) });
    const form = upload();

    await h.transport.request("/api/v1/receipts", {
      method: "POST",
      body: form,
      headers: { "Content-Type": "application/json" },
    });

    assert.equal(h.calls[0].init.body, form);
    assert.equal(h.calls[0].headers.has("Content-Type"), false);
    assert.equal(h.calls[0].headers.get("Authorization"), "Bearer token-1");
  });

  it("uses the longer multipart deadline", async () => {
    const slow = async () => {
      await new Promise((resolve) => setTimeout(resolve, 80));

      return json(201, { id: "r1" });
    };
    const policy = { timeoutMs: 30, multipartTimeoutMs: 400 };
    const jsonCall = makeHarness({ respond: slow, policy });
    const uploadCall = makeHarness({ respond: slow, policy });

    assert.equal((await rejection(jsonCall.transport.request("/x", { method: "POST", body: "{}" }))).kind, "timeout");
    assert.deepEqual(await uploadCall.transport.request("/x", { method: "POST", body: upload() }), { id: "r1" });
  });

  it("never retries an upload", async () => {
    const h = makeHarness({ respond: async () => json(503, {}) });

    await rejection(h.transport.request("/api/v1/receipts", { method: "POST", body: upload() }));
    assert.equal(h.calls.length, 1);
  });

  it("times out a stalled upload at the multipart deadline", async () => {
    const h = makeHarness({
      respond: () => never<Response>(),
      policy: { timeoutMs: 5_000, multipartTimeoutMs: 40 },
    });

    assert.equal(
      (await rejection(h.transport.request("/x", { method: "POST", body: upload() }))).kind,
      "timeout",
    );
  });
});
