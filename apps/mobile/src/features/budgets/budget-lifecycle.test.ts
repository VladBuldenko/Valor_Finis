// Budget requests over the REAL transport (VF-MVP-CORE-004), against a fake server that follows the
// documented contract. Budget create has no idempotency key: the unique (name, period, start date)
// rule is what stops a duplicate, and a lost response is only ever resolved by the user, never by an
// automatic resend. What is proved is the client side: no automatic retry of a write, and the
// message the user reads for each documented refusal.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { json, makeHarness } from "../../api/api-test-support.ts";
import { readApiFailure } from "../../api/api-error-message.ts";
import { getUserFacingErrorMessage } from "../../api/user-facing-error.ts";

const lostResponse = async () => {
  throw new TypeError("Network request failed");
};

describe("budget writes are never resent by the transport", () => {
  for (const [method, path, body] of [
    ["POST", "/api/v1/budgets", { name: "Food", limit_amount: "400.00", start_date: "2026-11-01" }],
    ["PATCH", "/api/v1/budgets/b-1", { limit_amount: "500.00" }],
    ["DELETE", "/api/v1/budgets/b-1", undefined],
  ] as const) {
    it(`${method} is sent exactly once when the response is lost`, async () => {
      const { transport, calls } = makeHarness({ respond: lostResponse });

      await assert.rejects(() =>
        transport.request(path, { method, body: body ? JSON.stringify(body) : undefined }),
      );
      assert.equal(calls.length, 1);
    });
  }

  it("a user-driven retry of a create after a lost response meets the duplicate rule and creates nothing new", async () => {
    const stored = new Set<string>();
    const { transport, calls } = makeHarness({
      respond: async (call, attempt) => {
        const body = JSON.parse(String(call.init.body)) as { name: string };
        const known = stored.has(body.name);

        stored.add(body.name);

        if (attempt === 1) {
          throw new TypeError("Network request failed"); // committed, answer lost
        }

        return known
          ? json(409, { detail: "Budget with this name, period, and start date already exists for this user.", code: "budget_already_exists" })
          : json(201, { id: "b-1", ...body });
      },
    });
    const send = () =>
      transport.request("/api/v1/budgets", { method: "POST", body: JSON.stringify({ name: "Food" }) });

    await assert.rejects(send);
    await assert.rejects(send, (error: unknown) => {
      assert.equal(readApiFailure(error).status, 409);
      return true;
    });
    assert.equal(calls.length, 2);
    assert.equal(stored.size, 1, "one budget, however many taps");
  });
});

describe("the message a user reads for each Budget refusal", () => {
  const cases: [number, string, string][] = [
    [409, "budget_already_exists", "Budget with this name, period, and start date already exists for this user."],
    [409, "budget_immutable_field", "Budget currency cannot be changed. Period and start date cannot be changed after the first period completes."],
    [409, "budget_retroactive_deactivation", "Budget end date cannot be set to a date before today."],
    [409, "budget_referenced_by_rule", "Budget is referenced by a financial rule and cannot be deleted."],
    [422, "budget_date_range_invalid", "Budget end date must be on or after its start date."],
    [404, "budget_not_found", "Budget not found."],
    [409, "category_in_use_by_budget", "Category is referenced by a budget and cannot be deleted. Hide it instead."],
  ];

  for (const [status, code, detail] of cases) {
    it(`${status} ${code} reads as its own sentence, not a raw envelope`, async () => {
      const { transport } = makeHarness({ respond: async () => json(status, { detail, code }) });
      let caught: unknown;

      try {
        await transport.request("/api/v1/budgets/b-1", { method: "PATCH", body: "{}" });
      } catch (error) {
        caught = error;
      }

      assert.equal(readApiFailure(caught).status, status);
      assert.equal(getUserFacingErrorMessage(caught, "Unable to update budget."), detail);
    });
  }

  it("a server failure never shows its body", async () => {
    const { transport } = makeHarness({
      respond: async () => json(500, { detail: "Internal server error.", code: "internal_server_error" }),
    });
    let caught: unknown;

    try {
      await transport.request("/api/v1/budgets", { method: "POST", body: "{}" });
    } catch (error) {
      caught = error;
    }

    const message = getUserFacingErrorMessage(caught, "Unable to create budget.");

    assert.ok(!message.includes("Internal server error"));
    assert.ok(!message.includes("budgets"));
  });
});
