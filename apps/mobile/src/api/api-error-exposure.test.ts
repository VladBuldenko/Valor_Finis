// What a user can read when a screen shows `error.message` directly.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { ApiError } from "./api-error.ts";
import { hangUntilAborted, json, makeHarness, never } from "./api-test-support.ts";

async function failure(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    assert.ok(error instanceof ApiError);

    return error;
  }

  throw new Error("expected a failure");
}

describe("non-HTTP failures show only fixed, non-technical text", () => {
  const SECRET_TOKEN = "token-1";

  it("timeout, cancellation, malformed response and missing session", async () => {
    const timeout = makeHarness({ respond: () => never<Response>(), policy: { timeoutMs: 20 } });
    const cancelled = makeHarness({ respond: async (call) => hangUntilAborted(call.init) });
    const controller = new AbortController();
    const cancelledFailure = failure(cancelled.transport.request("/x", { signal: controller.signal }));

    setTimeout(() => controller.abort(), 10);

    const malformed = makeHarness({ respond: async () => new Response("<html>stack trace</html>", { status: 200 }) });
    const anonymous = makeHarness({ respond: async () => json(200, {}), session: async () => null });
    const messages = [
      (await failure(timeout.transport.request("/x"))).message,
      (await cancelledFailure).message,
      (await failure(malformed.transport.request("/x"))).message,
      (await failure(anonymous.transport.request("/x"))).message,
    ];

    assert.deepEqual(messages, [
      "Request timed out.",
      "Request was cancelled.",
      "The server returned an unreadable response.",
      "User is not authenticated.",
    ]);
  });

  it("never puts the token, the URL or the request path into any message", async () => {
    const network = makeHarness({
      respond: async () => {
        throw new TypeError("Network request failed");
      },
    });
    const error = await failure(network.transport.request("/api/v1/secret-path?x=1", { method: "POST" }));
    const text = `${error.message} ${error.name} ${JSON.stringify(error)}`;

    assert.ok(!text.includes(SECRET_TOKEN));
    assert.ok(!text.includes("api.test"));
    assert.ok(!text.includes("secret-path"));
  });
});

describe("HTTP failures keep the historical message (documented exposure)", () => {
  it("includes the server's body, exactly as before ApiError existed", async () => {
    const body = '{"detail":"Archived account cannot receive new transactions."}';
    const h = makeHarness({ respond: async () => new Response(body, { status: 409 }) });
    const error = await failure(h.transport.request("/x", { method: "POST" }));

    assert.equal(error.message, `API request failed: 409 ${body}`);
  });

  it("a 5xx page body also reaches error.message, which is why screens must map errors", async () => {
    const h = makeHarness({ respond: async () => new Response("<html>Internal details</html>", { status: 500 }) });
    const error = await failure(h.transport.request("/x", { method: "POST" }));

    assert.match(error.message, /^API request failed: 500 /);
    assert.equal(error.detail, null);
    assert.equal(error.code, null);
  });

  it("the structured fields never include the request, headers or token", async () => {
    const h = makeHarness({ respond: async () => new Response('{"detail":"no"}', { status: 403 }) });
    const error = await failure(h.transport.request("/api/v1/x", { method: "POST", body: '{"amount":"10.00"}' }));
    const dump = JSON.stringify({ ...error, message: error.message });

    assert.ok(!dump.includes("token-1"));
    assert.ok(!dump.includes("10.00"));
    assert.ok(!dump.includes("Bearer"));
  });
});
