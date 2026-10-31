// The Smart Rules services go through the REAL transport with a fake fetch to
// prove the wire behaviour: a POST is sent exactly once, whatever fails.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { ApiError } from "../../api/api-error.ts";
import { json, makeHarness } from "../../api/api-test-support.ts";
import { createFinancialRulesApi } from "./financial-rule.api.ts";
import { describeRuleError } from "./financial-rule-errors.ts";

const RULE = "11111111-1111-4111-8111-111111111111";
const PROPOSAL = "22222222-2222-4222-8222-222222222222";

function apiOver(respond: Parameters<typeof makeHarness>[0]["respond"]) {
  const harness = makeHarness({ respond });

  return { harness, api: createFinancialRulesApi((path, options) => harness.transport.request(path, options)) };
}

describe("a POST is never repeated by the client", () => {
  it("evaluate after a network error is sent once", async () => {
    const { harness, api } = apiOver(async () => {
      throw new TypeError("Network request failed");
    });

    await assert.rejects(api.evaluateRules(), (error: unknown) => error instanceof ApiError && error.kind === "network");
    assert.equal(harness.calls.length, 1);
  });

  it("evaluate after HTTP 503 is sent once", async () => {
    const { harness, api } = apiOver(async () => json(503, { detail: "x", code: "service_unavailable" }));

    await assert.rejects(api.evaluateRules());
    assert.equal(harness.calls.length, 1);
  });

  it("confirm, reject, enable, create and preview are each sent once on a network error", async () => {
    const { harness, api } = apiOver(async () => {
      throw new TypeError("Network request failed");
    });

    await assert.rejects(api.confirmProposal(PROPOSAL));
    await assert.rejects(api.rejectProposal(PROPOSAL));
    await assert.rejects(api.enableRule(RULE));
    await assert.rejects(api.createRule({ rule_type: "BUDGET_ALERT", name: "n", budget_id: RULE }));
    await assert.rejects(api.previewRule(RULE, { sample_income: { amount: "10.00" } }));
    assert.equal(harness.calls.length, 5);
  });

  it("a failed confirm is reported as 'outcome unknown', not as a plain failure", async () => {
    const { api } = apiOver(async () => {
      throw new TypeError("Network request failed");
    });

    const error = await api.confirmProposal(PROPOSAL).catch((caught: unknown) => caught);
    const info = describeRuleError(error, "fallback", { mutation: true });

    assert.equal(info.category, "outcome_unknown");
    assert.equal(info.retryable, false);
  });

  it("a GET list may use the transport's own bounded retry (503 then 200)", async () => {
    const { harness, api } = apiOver(async (_call, attempt) =>
      attempt === 1 ? json(503, { detail: "x" }) : json(200, []),
    );

    assert.deepEqual(await api.listRules(), []);
    assert.equal(harness.calls.length, 2);
  });
});
