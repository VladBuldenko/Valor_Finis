// Income / Expense create idempotency, client side (VF-MVP-CORE-002): the REAL
// transport and the REAL attempt helpers against a fake server that follows the
// documented contract (201 new, 200 replay of the same key, one record per key).
// What is proved here is the client's behavior: one key per logical operation,
// the same key on an outcome-unknown retry, a fresh key for a new operation, and
// a POST that is never sent twice by the transport itself.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { json, makeHarness, type Call } from "../api/api-test-support.ts";
import { describeCreateFailure } from "../api/create-failure.ts";
import { createSubmitGuard, resolveCreateAttempt, type CreateAttempt } from "../lib/create-attempts.ts";
import { incomePayloadKey, toIncomeCreateInput, type IncomeCreatePayload } from "./income/income-create-attempt.ts";

const form: IncomeCreatePayload = { amount: "100.00", currency: "EUR", received_at: "2026-11-05", source: "gift" };

// A server with one record per client_request_id; the response of chosen calls is lost.
function fakeServer(lostResponses: ReadonlySet<number>) {
  const records = new Map<string, unknown>();
  const respond = async (call: Call, attempt: number): Promise<Response> => {
    const body = JSON.parse(String(call.init.body)) as { client_request_id: string };
    const replay = records.has(body.client_request_id);

    if (!replay) {
      records.set(body.client_request_id, { ...body, id: `income-${records.size + 1}` });
    }

    if (lostResponses.has(attempt)) {
      throw new TypeError("Network request failed");
    }

    return json(replay ? 200 : 201, records.get(body.client_request_id));
  };

  return { records, respond };
}

async function submit(
  transport: ReturnType<typeof makeHarness>["transport"],
  attempts: CreateAttempt<IncomeCreatePayload>[],
  payload: IncomeCreatePayload,
  generate: () => string,
) {
  const resolved = resolveCreateAttempt(attempts, "user-1", incomePayloadKey(payload), payload, generate);

  try {
    const record = await transport.request("/api/v1/income", {
      method: "POST",
      body: JSON.stringify(toIncomeCreateInput(resolved.attempt)),
    });

    return { attempts: resolved.attempts, record, error: null };
  } catch (error) {
    return { attempts: resolved.attempts, record: null, error };
  }
}

describe("income create over the real transport", () => {
  it("a lost response followed by a user retry sends the SAME key and leaves exactly one record", async () => {
    const server = fakeServer(new Set([1]));
    const { transport, calls } = makeHarness({ respond: server.respond });
    let counter = 0;
    const generate = () => `key-${(counter += 1)}`;

    const first = await submit(transport, [], form, generate);

    assert.ok(first.error, "the first response was lost");
    assert.equal(describeCreateFailure(first.error, "income", "x").outcomeUnknown, true);
    // The transport never re-sent the POST by itself: one call per user submission.
    assert.equal(calls.length, 1);

    const retry = await submit(transport, first.attempts, form, generate);

    assert.equal(retry.error, null);
    assert.equal(calls.length, 2);
    assert.equal(JSON.parse(String(calls[0].init.body)).client_request_id, JSON.parse(String(calls[1].init.body)).client_request_id);
    assert.equal(server.records.size, 1);
  });

  it("after a success the next identical-looking entry is a NEW operation with a new key", async () => {
    const server = fakeServer(new Set());
    const { transport } = makeHarness({ respond: server.respond });
    let counter = 0;
    const generate = () => `key-${(counter += 1)}`;

    const first = await submit(transport, [], form, generate);
    assert.equal(first.error, null);

    // onSuccess clears the attempts; the user enters the same figures again on purpose.
    const second = await submit(transport, [], form, generate);

    assert.equal(second.error, null);
    assert.equal(server.records.size, 2);
  });

  it("a changed form after an outcome-unknown failure is a new operation; editing it back replays the first", async () => {
    const server = fakeServer(new Set([1]));
    const { transport } = makeHarness({ respond: server.respond });
    let counter = 0;
    const generate = () => `key-${(counter += 1)}`;

    const lost = await submit(transport, [], form, generate);
    const changed = await submit(transport, lost.attempts, { ...form, amount: "200.00" }, generate);
    const editedBack = await submit(transport, changed.attempts, form, generate);

    assert.equal(changed.error, null);
    assert.equal(editedBack.error, null);
    // The first request (saved, response lost) was replayed, not duplicated.
    assert.equal(server.records.size, 2);
  });

  it("the transport never retries a POST on a network failure, even though GET would be retried", async () => {
    const { transport, calls } = makeHarness({
      respond: async () => {
        throw new TypeError("Network request failed");
      },
    });

    await assert.rejects(() => transport.request("/api/v1/income", { method: "POST", body: "{}" }));
    assert.equal(calls.length, 1);
  });

  it("the double-tap guard lets only the first of two synchronous taps start a request", async () => {
    const server = fakeServer(new Set());
    const { transport, calls } = makeHarness({ respond: server.respond });
    const guard = createSubmitGuard();
    let counter = 0;
    const generate = () => `key-${(counter += 1)}`;
    const pending: Promise<unknown>[] = [];

    for (let tap = 0; tap < 2; tap += 1) {
      if (guard.tryEnter()) {
        pending.push(submit(transport, [], form, generate));
      }
    }

    await Promise.all(pending);

    assert.equal(calls.length, 1);
    assert.equal(server.records.size, 1);
  });
});
