import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { QueryClient } from "@tanstack/react-query";

import { financialRuleKeys } from "./financial-rule-query-keys.ts";

const A = "user-a";
const B = "user-b";
const RULE = "rule-1";

describe("every private key carries the user id", () => {
  it("builds each key with the family first and the user second", () => {
    const keys = [
      financialRuleKeys.ruleList(A),
      financialRuleKeys.ruleDetail(A, RULE),
      financialRuleKeys.proposalList(A),
      financialRuleKeys.proposalDetail(A, "p1"),
      financialRuleKeys.alertList(A),
      financialRuleKeys.executionList(A),
      financialRuleKeys.preview(A, { ruleId: RULE, ruleVersion: 1, sampleAmount: "10.00", sampleSource: null }),
    ];

    for (const key of keys) {
      assert.equal(key[1], A);
    }
  });

  it("refuses to build a key without a user", () => {
    for (const user of ["", undefined as unknown as string, null as unknown as string]) {
      assert.throws(() => financialRuleKeys.ruleList(user), RangeError);
      assert.throws(() => financialRuleKeys.proposalList(user), RangeError);
    }
  });

  it("two users never share a key", () => {
    assert.notDeepEqual(financialRuleKeys.ruleList(A), financialRuleKeys.ruleList(B));
    assert.notDeepEqual(financialRuleKeys.alertList(A), financialRuleKeys.alertList(B));
  });

  it("a family invalidation for one user does not touch another user's cache", async () => {
    const client = new QueryClient();

    client.setQueryData(financialRuleKeys.ruleList(A), ["a"]);
    client.setQueryData(financialRuleKeys.ruleList(B), ["b"]);
    await client.invalidateQueries({ queryKey: [...financialRuleKeys.rulesFamily(A)] });

    assert.equal(client.getQueryState(financialRuleKeys.ruleList(A))?.isInvalidated, true);
    assert.equal(client.getQueryState(financialRuleKeys.ruleList(B))?.isInvalidated, false);
  });
});

describe("filters, pagination and rule version are part of the key", () => {
  it("different pages and filters are different entries; equal requests share one", () => {
    assert.notDeepEqual(
      financialRuleKeys.proposalList(A, { limit: 20, offset: 0 }),
      financialRuleKeys.proposalList(A, { limit: 20, offset: 20 }),
    );
    assert.notDeepEqual(
      financialRuleKeys.proposalList(A, { status: "executed" }),
      financialRuleKeys.proposalList(A, { status: "rejected" }),
    );
    assert.notDeepEqual(
      financialRuleKeys.alertList(A, { acknowledged: true }),
      financialRuleKeys.alertList(A, { acknowledged: false }),
    );
    assert.notDeepEqual(
      financialRuleKeys.alertList(A, { acknowledged: false }),
      financialRuleKeys.alertList(A),
    );
    assert.notDeepEqual(
      financialRuleKeys.executionList(A, { rule_id: "r1" }),
      financialRuleKeys.executionList(A, { rule_id: "r2" }),
    );
    assert.deepEqual(
      financialRuleKeys.executionList(A, { status: "blocked", limit: 5 }),
      financialRuleKeys.executionList(A, { limit: 5, status: "blocked" }),
    );
  });

  it("a preview of rule version 2 is a different entry from version 1", () => {
    const base = { ruleId: RULE, sampleAmount: "10.00", sampleSource: null } as const;

    assert.notDeepEqual(
      financialRuleKeys.preview(A, { ...base, ruleVersion: 1 }),
      financialRuleKeys.preview(A, { ...base, ruleVersion: 2 }),
    );
    assert.notDeepEqual(
      financialRuleKeys.preview(A, { ...base, ruleVersion: 1 }),
      financialRuleKeys.preview(A, { ...base, ruleVersion: 1, sampleAmount: "11.00" }),
    );
    assert.notDeepEqual(
      financialRuleKeys.preview(A, { ...base, ruleVersion: 1 }),
      financialRuleKeys.preview(A, { ...base, ruleVersion: 1, sampleSource: "salary" }),
    );
  });
});
