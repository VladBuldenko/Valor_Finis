// VF-020F5: requesting an example. Exact request shape, one POST, no retry,
// no write anywhere but the preview cache, stale/other-session answers dropped.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { QueryClient } from "@tanstack/react-query";

import { buildPreviewRequest, previewRuleRequest } from "./financial-rule-requests.ts";
import { previewKeyFor } from "./preview-authorization.ts";
import { requestRulePreview, validateSampleAmount, type PreviewFlowDeps } from "./rule-preview-flow.ts";
import type { RulePreview, RulePreviewRequest } from "./financial-rule.types.ts";
import { USER_A, apiError, floorRule, allocationRule, preview } from "./preview-fixtures.test-support.ts";

function setup(over: Partial<PreviewFlowDeps> = {}, answer: () => Promise<RulePreview> = async () => preview()) {
  const queryClient = new QueryClient();
  const sent: { ruleId: string; request: RulePreviewRequest }[] = [];
  const deps: PreviewFlowDeps = {
    queryClient,
    userId: USER_A,
    rule: allocationRule(),
    inputs: { amount: "3000.00", source: "salary" },
    send: (ruleId, request) => { sent.push({ ruleId, request }); return answer(); },
    isCurrent: () => true,
    ...over,
  };

  return { queryClient, sent, deps };
}

describe("request shape", () => {
  it("sends exactly the typed decimal string and the chosen source", async () => {
    const { sent, deps } = setup({ inputs: { amount: " 1234567890.10 ", source: "freelance" } });

    await requestRulePreview(deps);
    assert.deepEqual(sent[0].request, { sample_income: { amount: "1234567890.10", source: "freelance" } });
    assert.equal(sent[0].ruleId, "rule-1");
  });

  it("omits the source when none was chosen, and never adds currency, user or dates", async () => {
    const { sent, deps } = setup({ inputs: { amount: "3000.00", source: null } });

    await requestRulePreview(deps);
    assert.deepEqual(sent[0].request, { sample_income: { amount: "3000.00" } });
    assert.deepEqual(Object.keys(sent[0].request.sample_income), ["amount"]);
  });

  it("builds a POST to .../preview with the exact JSON body", () => {
    const id = "44444444-4444-4444-8444-444444444444";
    const spec = previewRuleRequest(id, buildPreviewRequest("0.05", "gift"));

    assert.equal(spec.method, "POST");
    assert.equal(spec.path, `/api/v1/financial-rules/${id}/preview`);
    assert.equal(spec.body, JSON.stringify({ sample_income: { amount: "0.05", source: "gift" } }));
  });

  it("rejects bad amounts before any request", async () => {
    for (const bad of ["", "0", "0.00", "-5", "1.234", "abc", "1e3", "3,000.00", "1000000000000.00"]) {
      const { sent, deps } = setup({ inputs: { amount: bad, source: null } });
      const result = await requestRulePreview(deps);

      assert.equal(result.kind, "invalid_input", bad);
      assert.equal(sent.length, 0, bad);
      assert.notEqual(validateSampleAmount(bad), null, bad);
    }

    assert.equal(validateSampleAmount("3000.00"), null);
    assert.equal(validateSampleAmount(" 12 "), null);
  });
});

describe("results", () => {
  it("stores the answer under the user + rule + version + sample key and returns it untouched", async () => {
    const answer = preview();
    const { queryClient, deps } = setup({}, async () => answer);
    const result = await requestRulePreview(deps);

    assert.equal(result.kind, "ok");
    assert.equal(
      queryClient.getQueryData(previewKeyFor({ userId: USER_A, ruleId: "rule-1", ruleVersion: 3, inputs: { amount: "3000.00", source: "salary" } })),
      answer,
    );
  });

  it("only INCOME_ALLOCATION rules are previewable; nothing is sent for others", async () => {
    const { sent, deps } = setup({ rule: floorRule() });

    assert.equal((await requestRulePreview(deps)).kind, "not_previewable");
    assert.equal(sent.length, 0);
  });

  it("an answer for another rule version is neither cached nor shown", async () => {
    const { queryClient, deps } = setup({}, async () => preview({ rule_version: 4 }));
    const result = await requestRulePreview(deps);

    assert.equal(result.kind, "rule_changed");
    assert.equal(queryClient.getQueryCache().getAll().length, 0);
  });

  it("an answer that is not a hypothetical preview of this rule is a failure and is not cached", async () => {
    for (const bad of [{ hypothetical: false as unknown as true }, { rule_id: "other" }]) {
      const { queryClient, deps } = setup({}, async () => preview(bad));

      assert.equal((await requestRulePreview(deps)).kind, "failed");
      assert.equal(queryClient.getQueryCache().getAll().length, 0);
    }
  });
});

describe("failures, retries and sessions", () => {
  it("each failure maps to a controlled message, caches nothing and is sent exactly once", async () => {
    const cases: [ReturnType<typeof apiError>, RegExp][] = [
      [apiError("http", 401), /./],
      [apiError("http", 404, "financial_rule_not_found"), /no longer exists/],
      [apiError("http", 409, "financial_rule_preview_not_available"), /only available for rules/],
      [apiError("http", 422, "validation_error"), /Check the values/],
      [apiError("timeout"), /./],
      [apiError("network"), /./],
      [apiError("malformed_response", 200), /./],
    ];

    for (const [error, expected] of cases) {
      const { queryClient, sent, deps } = setup({}, async () => { throw error; });
      const result = await requestRulePreview(deps);

      assert.equal(result.kind, "failed");
      assert.match(result.kind === "failed" ? result.info.message : "", expected);
      assert.equal(sent.length, 1, "no automatic retry");
      assert.equal(queryClient.getQueryCache().getAll().length, 0);
    }
  });

  it("an answer arriving after the session changed is dropped: nothing cached, nothing shown", async () => {
    let current = true;
    const { queryClient, deps } = setup({ isCurrent: () => current }, async () => { current = false; return preview(); });
    const result = await requestRulePreview(deps);

    assert.equal(result.kind, "stale_session");
    assert.equal(queryClient.getQueryCache().getAll().length, 0);
  });

  it("an error arriving after the session changed is also dropped", async () => {
    let current = true;
    const { deps } = setup({ isCurrent: () => current }, async () => { current = false; throw apiError("timeout"); });

    assert.equal((await requestRulePreview(deps)).kind, "stale_session");
  });

  it("a preview never touches anything but the preview cache (no real mutation path is called)", async () => {
    const { queryClient, deps } = setup();

    await requestRulePreview(deps);
    assert.deepEqual(queryClient.getQueryCache().getAll().map((q) => q.queryKey[0]), ["rule-previews"]);
    assert.equal(queryClient.getMutationCache().getAll().length, 0);
  });
});
