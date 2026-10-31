import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { createFinancialRulesApi, type RequestFn } from "./financial-rule.api.ts";
import {
  buildPreviewRequest,
  listAlertsRequest,
  listExecutionsRequest,
  listProposalsRequest,
  previewRuleRequest,
} from "./financial-rule-requests.ts";

const RULE = "11111111-1111-4111-8111-111111111111";
const PROPOSAL = "22222222-2222-4222-8222-222222222222";
const ALERT = "33333333-3333-4333-8333-333333333333";

type Recorded = { path: string; method: string | undefined; body: unknown; signal: unknown };

function recorder() {
  const calls: Recorded[] = [];
  const request: RequestFn = async <T,>(path: string, options?: { method?: string; body?: unknown; signal?: unknown }) => {
    calls.push({ path, method: options?.method, body: options?.body, signal: options?.signal });

    return undefined as T;
  };

  return { calls, api: createFinancialRulesApi(request) };
}

describe("endpoint coverage: exactly the 14 backend endpoints, real methods", () => {
  it("sends the right method and path for each", async () => {
    const { calls, api } = recorder();
    const base = "/api/v1";

    await api.listRules();
    await api.createRule({ rule_type: "BUDGET_ALERT", name: "n", budget_id: RULE });
    await api.evaluateRules();
    await api.getRule(RULE);
    await api.updateRule(RULE, { name: "x" });
    await api.deleteRule(RULE);
    await api.enableRule(RULE);
    await api.pauseRule(RULE);
    await api.disableRule(RULE);
    await api.previewRule(RULE, buildPreviewRequest("100.00"));
    await api.listProposals();
    await api.getProposal(PROPOSAL);
    await api.confirmProposal(PROPOSAL);
    await api.rejectProposal(PROPOSAL);
    await api.listAlerts();
    await api.acknowledgeAlert(ALERT);
    await api.listExecutions();

    assert.deepEqual(
      calls.map((call) => `${call.method} ${call.path}`),
      [
        `GET ${base}/financial-rules`,
        `POST ${base}/financial-rules`,
        `POST ${base}/financial-rules/evaluate`,
        `GET ${base}/financial-rules/${RULE}`,
        `PATCH ${base}/financial-rules/${RULE}`,
        `DELETE ${base}/financial-rules/${RULE}`,
        `POST ${base}/financial-rules/${RULE}/enable`,
        `POST ${base}/financial-rules/${RULE}/pause`,
        `POST ${base}/financial-rules/${RULE}/disable`,
        `POST ${base}/financial-rules/${RULE}/preview`,
        `GET ${base}/rule-proposals`,
        `GET ${base}/rule-proposals/${PROPOSAL}`,
        `POST ${base}/rule-proposals/${PROPOSAL}/confirm`,
        `POST ${base}/rule-proposals/${PROPOSAL}/reject`,
        `GET ${base}/rule-alerts`,
        `POST ${base}/rule-alerts/${ALERT}/acknowledge`,
        `GET ${base}/rule-executions`,
      ],
    );
  });

  it("body-less actions send no body; writes send exactly the typed JSON", async () => {
    const { calls, api } = recorder();

    await api.enableRule(RULE);
    await api.confirmProposal(PROPOSAL);
    await api.evaluateRules();
    await api.updateRule(RULE, { floor_amount: "250.00" });

    assert.equal(calls[0].body, undefined);
    assert.equal(calls[1].body, undefined);
    assert.equal(calls[2].body, undefined);
    assert.equal(calls[3].body, JSON.stringify({ floor_amount: "250.00" }));
  });

  it("passes the abort signal through for reads, evaluate and preview", async () => {
    const { calls, api } = recorder();
    const controller = new AbortController();

    await api.listRules(controller.signal);
    await api.evaluateRules(controller.signal);
    await api.previewRule(RULE, buildPreviewRequest("5"), controller.signal);

    assert.ok(calls.every((call) => call.signal === controller.signal));
  });

  it("the money fields stay decimal strings on the wire (no float)", async () => {
    const { calls, api } = recorder();

    await api.createRule({
      rule_type: "INCOME_ALLOCATION",
      name: "Save",
      source_account_id: RULE,
      execution_mode: "CONFIRM",
      policy: "PERCENT_OF_INCOME_WATERFALL",
      percent: "12.50",
      targets: [{ goal_id: PROPOSAL, amount_or_cap: "300.10" }],
    });

    const sent = JSON.parse(String(calls[0].body)) as {
      percent: unknown;
      targets: { amount_or_cap: unknown }[];
    };

    assert.equal(sent.percent, "12.50");
    assert.equal(sent.targets[0].amount_or_cap, "300.10");
  });
});

describe("pagination and filter construction", () => {
  it("builds no query string without filters", () => {
    assert.equal(listProposalsRequest().path, "/api/v1/rule-proposals");
    assert.equal(listAlertsRequest({}).path, "/api/v1/rule-alerts");
    assert.equal(listExecutionsRequest({}).path, "/api/v1/rule-executions");
  });

  it("uses the backend parameter names, including status and acknowledged", () => {
    assert.equal(
      listProposalsRequest({ limit: 20, offset: 40, status: "awaiting_confirmation" }).path,
      "/api/v1/rule-proposals?limit=20&offset=40&status=awaiting_confirmation",
    );
    assert.equal(
      listAlertsRequest({ limit: 100, offset: 0, acknowledged: false }).path,
      "/api/v1/rule-alerts?limit=100&offset=0&acknowledged=false",
    );
    assert.equal(
      listAlertsRequest({ acknowledged: true }).path,
      "/api/v1/rule-alerts?acknowledged=true",
    );
    assert.equal(
      listExecutionsRequest({ rule_id: RULE, status: "blocked", limit: 5 }).path,
      `/api/v1/rule-executions?limit=5&rule_id=${RULE}&status=blocked`,
    );
  });

  it("rejects out-of-range or non-integer pagination instead of sending it", () => {
    for (const bad of [0, 101, -1, 1.5, Number.NaN]) {
      assert.throws(() => listProposalsRequest({ limit: bad }), RangeError, `limit ${bad}`);
    }

    for (const bad of [-1, 2.5, Number.NaN]) {
      assert.throws(() => listAlertsRequest({ offset: bad }), RangeError, `offset ${bad}`);
    }
  });
});

describe("ids are validated before they reach a path", () => {
  it("rejects anything that is not a UUID", () => {
    const { api } = recorder();

    for (const bad of ["", "abc", "../financial-rules", `${RULE}/enable`, `${RULE}?x=1`]) {
      assert.throws(() => api.getRule(bad), RangeError, bad);
      assert.throws(() => api.confirmProposal(bad), RangeError, bad);
      assert.throws(() => api.acknowledgeAlert(bad), RangeError, bad);
    }

    assert.throws(() => listExecutionsRequest({ rule_id: "not-a-uuid" }), RangeError);
  });
});

describe("preview request typing and validation", () => {
  it("builds a decimal-string sample, with the source only when given", () => {
    assert.deepEqual(buildPreviewRequest("3000.00"), { sample_income: { amount: "3000.00" } });
    assert.deepEqual(buildPreviewRequest("3000", "salary"), {
      sample_income: { amount: "3000", source: "salary" },
    });
  });

  it("rejects zero, negative, 3-decimal, exponent, comma and non-numeric samples", () => {
    for (const bad of ["0", "0.00", "-5", "1.234", "1e3", "1,5", "", "abc", " 5", "12345678901"]) {
      assert.throws(() => buildPreviewRequest(bad), RangeError, JSON.stringify(bad));
    }
  });

  it("re-validates a hand-built request", () => {
    assert.throws(
      () => previewRuleRequest(RULE, { sample_income: { amount: "-1" } }),
      RangeError,
    );
  });
});

// Compile-time proof (checked by tsc): a number cannot be passed as money.
// @ts-expect-error amount must be a decimal string
buildPreviewRequest(100);
