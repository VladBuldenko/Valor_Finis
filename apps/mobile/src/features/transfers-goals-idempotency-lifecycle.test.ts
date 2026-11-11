// Transfer and Goal-transaction create idempotency, client side (VF-MVP-CORE-003): the REAL
// transport and the REAL attempt helpers against a fake server that follows the documented
// contract (201 new, 200 replay of the same key with the same payload, 409 for a changed payload,
// one record per key). What is proved is the client's behavior: the same key on an
// outcome-unknown retry, a new key for a new operation, a conflict that drops the stale key, and
// a POST that the transport never sends twice by itself.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { json, makeHarness, type Call } from "../api/api-test-support.ts";
import { readApiFailure } from "../api/api-error-message.ts";
import {
  GOAL_ARCHIVED_DETAIL,
  IDEMPOTENCY_CONFLICT_DETAIL,
  mapGoalTransactionFailure,
} from "./goals/goal-transaction-errors.ts";
import {
  discardGoalTransactionAttempt,
  resolveGoalTransactionAttempt,
  toGoalTransactionCreateInput,
  type GoalTransactionAttempt,
  type GoalTransactionPayload,
} from "./goals/goal-transaction-attempts.ts";
import {
  resolveTransferCreateAttempt,
  toAccountTransferCreateInput,
  type TransferCreateAttempt,
  type TransferCreatePayload,
} from "./transfers/transfer-create-attempts.ts";

type Body = Record<string, unknown> & { client_request_id: string };

// A server with one record per client_request_id; a changed payload under a used key is a 409.
// `lostResponses` are call numbers whose response is lost AFTER the server committed.
function fakeServer(options: { lostResponses?: ReadonlySet<number>; conflictDetail: string; prefix: string }) {
  const records = new Map<string, Body>();
  const respond = async (call: Call, attempt: number): Promise<Response> => {
    const body = JSON.parse(String(call.init.body)) as Body;
    const existing = records.get(body.client_request_id);

    if (existing && JSON.stringify(existing.input) !== JSON.stringify(body)) {
      return json(409, { detail: options.conflictDetail, code: "idempotency_conflict" });
    }

    if (!existing) {
      records.set(body.client_request_id, { ...body, input: body, id: `${options.prefix}-${records.size + 1}` });
    }

    if (options.lostResponses?.has(attempt)) {
      throw new TypeError("Network request failed");
    }

    return json(existing ? 200 : 201, { id: records.get(body.client_request_id)?.id, ...body });
  };

  return { records, respond };
}

const keyFactory = () => {
  let counter = 0;

  return () => `key-${(counter += 1)}`;
};

describe("account transfer create over the real transport", () => {
  const form: TransferCreatePayload = {
    source_account_id: "src",
    destination_account_id: "dst",
    amount: "300.00",
    transfer_date: "2026-11-11",
    description: null,
  };

  async function submit(
    transport: ReturnType<typeof makeHarness>["transport"],
    attempts: TransferCreateAttempt[],
    payload: TransferCreatePayload,
    generate: () => string,
  ) {
    const resolved = resolveTransferCreateAttempt(attempts, payload, generate);

    try {
      const record = await transport.request("/api/v1/account-transfers", {
        method: "POST",
        body: JSON.stringify(toAccountTransferCreateInput(resolved.attempt)),
      });

      return { attempts: resolved.attempts, record, error: null as unknown };
    } catch (error) {
      return { attempts: resolved.attempts, record: null, error };
    }
  }

  it("a lost response then a user retry sends the SAME key and leaves exactly one transfer", async () => {
    const server = fakeServer({ lostResponses: new Set([1]), conflictDetail: "x", prefix: "transfer" });
    const { transport, calls } = makeHarness({ respond: server.respond });
    const generate = keyFactory();

    const first = await submit(transport, [], form, generate);

    assert.ok(first.error, "the first response was lost");
    assert.equal(calls.length, 1, "the transport never re-sends a POST by itself");

    const retry = await submit(transport, first.attempts, form, generate);

    assert.equal(retry.error, null);
    assert.equal(calls.length, 2);
    assert.equal(
      JSON.parse(String(calls[0].init.body)).client_request_id,
      JSON.parse(String(calls[1].init.body)).client_request_id,
    );
    assert.equal(server.records.size, 1);
  });

  it("after a success the next identical-looking transfer is a NEW operation with a new key", async () => {
    const server = fakeServer({ conflictDetail: "x", prefix: "transfer" });
    const { transport } = makeHarness({ respond: server.respond });
    const generate = keyFactory();

    const first = await submit(transport, [], form, generate);
    assert.equal(first.error, null);

    // onSuccess clears the attempts; the user enters the same figures again on purpose.
    const second = await submit(transport, [], form, generate);

    assert.equal(second.error, null);
    assert.equal(server.records.size, 2);
  });

  it("a changed form after an unconfirmed attempt is a new operation; editing it back replays the first", async () => {
    const server = fakeServer({ lostResponses: new Set([1]), conflictDetail: "x", prefix: "transfer" });
    const { transport } = makeHarness({ respond: server.respond });
    const generate = keyFactory();

    const lost = await submit(transport, [], form, generate);
    const changed = await submit(transport, lost.attempts, { ...form, amount: "5.00" }, generate);
    const editedBack = await submit(transport, changed.attempts, form, generate);

    assert.equal(changed.error, null);
    assert.equal(editedBack.error, null);
    assert.equal(server.records.size, 2, "the first request was replayed, not duplicated");
  });

  it("manual posting is sent once per tap: the transport never retries it on a network failure", async () => {
    const { transport, calls } = makeHarness({
      respond: async () => {
        throw new TypeError("Network request failed");
      },
    });

    await assert.rejects(() =>
      transport.request("/api/v1/account-transfers/t-1/post", {
        method: "POST",
        body: JSON.stringify({ effective_date: "2026-11-11" }),
      }),
    );
    assert.equal(calls.length, 1);
  });

  it("deleting is sent once and a 404 is surfaced to the caller as an ApiError the service can recognize", async () => {
    const { transport, calls } = makeHarness({
      respond: async () => json(404, { detail: "Account transfer not found.", code: "account_transfer_not_found" }),
    });

    await assert.rejects(
      () => transport.request("/api/v1/account-transfers/t-1", { method: "DELETE" }),
      (error: unknown) => readApiFailure(error).status === 404,
    );
    assert.equal(calls.length, 1);
  });
});

describe("goal transaction create over the real transport", () => {
  const tracked: GoalTransactionPayload = {
    goalId: "goal-1",
    type: "contribution",
    amount: "100.00",
    description: null,
    accountId: null,
  };
  const linked: GoalTransactionPayload = { ...tracked, accountId: "acc-1" };

  async function submit(
    transport: ReturnType<typeof makeHarness>["transport"],
    attempts: GoalTransactionAttempt[],
    payload: GoalTransactionPayload,
    generate: () => string,
  ) {
    const resolved = resolveGoalTransactionAttempt(attempts, payload, generate);

    try {
      const record = await transport.request(`/api/v1/goals/${payload.goalId}/transactions`, {
        method: "POST",
        body: JSON.stringify(toGoalTransactionCreateInput(resolved.attempt)),
      });

      return { attempts: resolved.attempts, attempt: resolved.attempt, record, error: null as unknown };
    } catch (error) {
      return { attempts: resolved.attempts, attempt: resolved.attempt, record: null, error };
    }
  }

  for (const [label, payload] of [
    ["tracked", tracked],
    ["linked (reservation)", linked],
  ] as const) {
    it(`a lost ${label} response then a retry reuses the key: one transaction, and the account_id is preserved`, async () => {
      const server = fakeServer({ lostResponses: new Set([1]), conflictDetail: IDEMPOTENCY_CONFLICT_DETAIL, prefix: "gtx" });
      const { transport, calls } = makeHarness({ respond: server.respond });
      const generate = keyFactory();

      const first = await submit(transport, [], payload, generate);

      assert.ok(first.error);
      assert.equal(calls.length, 1);

      const retry = await submit(transport, first.attempts, payload, generate);

      assert.equal(retry.error, null);
      assert.equal(server.records.size, 1);

      const sent = JSON.parse(String(calls[1].init.body));

      assert.equal(sent.client_request_id, JSON.parse(String(calls[0].init.body)).client_request_id);
      assert.equal("account_id" in sent, payload.accountId !== null);
      // This client never sends an effective_date: the server date keeps a retry after midnight a replay.
      assert.equal("effective_date" in sent, false);
    });
  }

  it("a reservation and a tracked contribution of the same amount are different requests with different keys", () => {
    const generate = keyFactory();
    const first = resolveGoalTransactionAttempt([], tracked, generate);
    const second = resolveGoalTransactionAttempt(first.attempts, linked, generate);

    assert.notEqual(second.attempt.clientRequestId, first.attempt.clientRequestId);
  });

  it("a conflict maps to the documented copy and drops the stale key, so the next submit is a new request", async () => {
    const server = fakeServer({ conflictDetail: IDEMPOTENCY_CONFLICT_DETAIL, prefix: "gtx" });
    const { transport } = makeHarness({ respond: server.respond });
    const generate = keyFactory();

    // Seed the server with key-1 for a DIFFERENT amount, then reuse key-1 for this payload.
    const first = resolveGoalTransactionAttempt([], tracked, generate);
    await transport.request("/api/v1/goals/goal-1/transactions", {
      method: "POST",
      body: JSON.stringify({ ...toGoalTransactionCreateInput(first.attempt), amount: "1.00" }),
    });

    const clash = await submit(transport, first.attempts, tracked, generate);

    assert.ok(clash.error);

    const failure = readApiFailure(clash.error);

    assert.equal(failure.status, 409);

    const handling = mapGoalTransactionFailure(failure, { type: "contribution", isLinked: false }, "fallback");

    assert.equal(handling.discardAttempt, true);

    const kept = discardGoalTransactionAttempt(clash.attempts, clash.attempt.clientRequestId);
    const next = await submit(transport, kept, tracked, generate);

    assert.equal(next.error, null);
    assert.notEqual(next.attempt.clientRequestId, clash.attempt.clientRequestId);
  });

  it("an archived-goal refusal refreshes Goals; the transport sends the POST exactly once", async () => {
    const { transport, calls } = makeHarness({
      respond: async () => json(409, { detail: GOAL_ARCHIVED_DETAIL, code: "goal_archived" }),
    });
    const result = await submit(transport, [], tracked, keyFactory());
    const handling = mapGoalTransactionFailure(readApiFailure(result.error), { type: "contribution", isLinked: false }, "fallback");

    assert.equal(calls.length, 1);
    assert.equal(handling.refreshGoals, true);
    assert.equal(handling.discardAttempt, false);
  });

  it("the transport never retries a goal POST on a network failure, even though a GET would be retried", async () => {
    const { transport, calls } = makeHarness({
      respond: async () => {
        throw new TypeError("Network request failed");
      },
    });

    await assert.rejects(() => transport.request("/api/v1/goals/goal-1/transactions", { method: "POST", body: "{}" }));
    assert.equal(calls.length, 1);
  });
});
