// VF-020F5: the AUTO enable gate's state. A proof exists only for a viewed,
// successful preview of THIS user, rule, version and sample, and dies with any
// edit, input change, Goal/Account change or session change.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { QueryClient } from "@tanstack/react-query";

import { SessionQueryClient } from "../../lib/session-query-client.ts";
import { applyRuleChangeInvalidation } from "./financial-rule-actions.ts";
import { applyRuleInvalidation } from "./financial-rule-invalidation.ts";
import { accountKeys, goalKeys } from "./financial-rule-query-keys.ts";
import { previewAuthorizations, previewKeyFor, type PreviewInputs, type PreviewProof } from "./preview-authorization.ts";
import { USER_A, USER_B, allocationRule, preview } from "./preview-fixtures.test-support.ts";

const INPUTS: PreviewInputs = { amount: "3000.00", source: "salary" };
const subject = (over: Partial<{ userId: string; ruleVersion: number; inputs: PreviewInputs }> = {}) => ({
  userId: USER_A, ruleId: "rule-1", ruleVersion: 3, inputs: INPUTS, ...over,
});

function viewed(client: QueryClient = new QueryClient()) {
  client.setQueryData(goalKeys.family(USER_A), []);
  client.setQueryData(accountKeys.family(USER_A), []);
  client.setQueryData(previewKeyFor(subject()), preview());
  const store = previewAuthorizations(client);

  assert.equal(store.markViewed(subject()), true);

  return { client, store };
}

describe("a proof needs a viewed, successful preview of the current inputs", () => {
  it("no preview, no proof", () => {
    const store = previewAuthorizations(new QueryClient());

    assert.equal(store.markViewed(subject()), false);
    assert.equal(store.proofFor(subject()), null);
  });

  it("a cached preview that was never viewed does not authorize", () => {
    const client = new QueryClient();

    client.setQueryData(previewKeyFor(subject()), preview());
    assert.equal(previewAuthorizations(client).proofFor(subject()), null);
  });

  it("viewing it yields a proof that verifies for the same rule version", () => {
    const { store } = viewed();
    const proof = store.proofFor(subject());

    assert.ok(proof);
    assert.equal(store.verify(proof, { id: "rule-1", version: 3 }), true);
  });

  it("a preview of an old version cannot authorize a newer version", () => {
    const { store } = viewed();
    const proof = store.proofFor(subject()) as PreviewProof;

    assert.equal(store.proofFor(subject({ ruleVersion: 4 })), null);
    assert.equal(store.verify(proof, { id: "rule-1", version: 4 }), false);
    assert.equal(store.verify(proof, { id: "other-rule", version: 3 }), false);
  });

  it("a different sample amount or source cannot reuse the authorization", () => {
    const { store } = viewed();

    assert.equal(store.proofFor(subject({ inputs: { amount: "3000", source: "salary" } })), null);
    assert.equal(store.proofFor(subject({ inputs: { amount: "3000.00", source: "gift" } })), null);
    assert.equal(store.proofFor(subject({ inputs: { amount: "3000.00", source: null } })), null);
  });

  it("a second sample that was fetched but never viewed gets no proof, even with the same timestamp", () => {
    const client = new QueryClient();
    const other: PreviewInputs = { amount: "500.00", source: "salary" };

    client.setQueryData(previewKeyFor(subject()), preview(), { updatedAt: 1000 });
    client.setQueryData(previewKeyFor(subject({ inputs: other })), preview(), { updatedAt: 1000 });

    const store = previewAuthorizations(client);

    assert.equal(store.markViewed(subject()), true);
    assert.ok(store.proofFor(subject()));
    assert.equal(store.proofFor(subject({ inputs: other })), null);
    assert.equal(store.proofFor(subject({ inputs: { amount: "3000.00", source: null } })), null);
  });

  it("an invalidated preview cannot even be recorded as viewed", async () => {
    const client = new QueryClient();

    client.setQueryData(previewKeyFor(subject()), preview());
    await client.invalidateQueries({ queryKey: [...previewKeyFor(subject())] });
    assert.equal(previewAuthorizations(client).markViewed(subject()), false);
  });

  it("a non-hypothetical or other-rule or other-version payload is never recorded", () => {
    for (const bad of [
      { hypothetical: false as unknown as true },
      { rule_id: "someone-else" },
      { rule_version: 2 },
    ]) {
      const client = new QueryClient();

      client.setQueryData(previewKeyFor(subject()), preview(bad));
      assert.equal(previewAuthorizations(client).markViewed(subject()), false, JSON.stringify(bad));
    }
  });

  it("a hand-built proof is rejected even with the right fields", () => {
    const { store } = viewed();
    const forged = { kind: "preview-proof", userId: USER_A, ruleId: "rule-1", ruleVersion: 3, inputs: INPUTS } as PreviewProof;

    assert.equal(store.verify(forged, { id: "rule-1", version: 3 }), false);
    assert.equal(store.verify(undefined, { id: "rule-1", version: 3 }), false);
  });
});

describe("revocation", () => {
  const revokedBy: [string, (client: QueryClient) => unknown][] = [
    ["a material rule edit", (c) => applyRuleChangeInvalidation(c, USER_A, { kind: "edited", rule: allocationRule(), material: true })],
    ["deleting the rule", (c) => applyRuleChangeInvalidation(c, USER_A, { kind: "deleted", rule: allocationRule() })],
    ["a status change of the rule", (c) => applyRuleChangeInvalidation(c, USER_A, { kind: "status", rule: allocationRule(), action: "pause" })],
    ["a Goal/Account change event", (c) => applyRuleInvalidation(c, USER_A, { type: "goal_or_account_changed" })],
    ["income being recorded", (c) => applyRuleInvalidation(c, USER_A, { type: "income_recorded" })],
    ["the Goals cache being invalidated", (c) => c.invalidateQueries({ queryKey: [...goalKeys.family(USER_A)] })],
    ["the Accounts cache being invalidated", (c) => c.invalidateQueries({ queryKey: [...accountKeys.family(USER_A)] })],
    ["the Goals data being replaced (refetched)", async (c) => { await new Promise((r) => setTimeout(r, 5)); c.setQueryData(goalKeys.family(USER_A), [{ id: "g" }]); }],
    ["a new Account entry appearing", (c) => c.setQueryData([...accountKeys.family(USER_A), "detail", "x"], {})],
    ["the preview entry itself being replaced", async (c) => { await new Promise((r) => setTimeout(r, 5)); c.setQueryData(previewKeyFor(subject()), preview()); }],
  ];

  for (const [name, act] of revokedBy) {
    it(`${name} revokes the proof and refuses an issued one`, async () => {
      const { client, store } = viewed();
      const proof = store.proofFor(subject()) as PreviewProof;

      await act(client);
      assert.equal(store.proofFor(subject()), null, "no new proof");
      assert.equal(store.verify(proof, { id: "rule-1", version: 3 }), false, "issued proof refused");
    });
  }

  it("a name-only edit (not material) keeps the authorization", async () => {
    const { client, store } = viewed();

    await applyRuleChangeInvalidation(client, USER_A, { kind: "edited", rule: allocationRule(), material: false });
    assert.ok(store.proofFor(subject()));
  });

  it("revokeRule and clear drop records and notify subscribers", () => {
    const { store } = viewed();
    let notified = 0;
    const stop = store.subscribe(() => { notified += 1; });
    const before = store.getVersion();

    store.revokeRule("rule-1");
    assert.equal(store.proofFor(subject()), null);
    assert.equal(notified, 1);
    assert.equal(store.getVersion(), before + 1);
    store.markViewed(subject());
    assert.ok(store.proofFor(subject()));
    store.clear();
    assert.equal(store.proofFor(subject()), null);
    stop();
  });
});

describe("session ownership", () => {
  it("a rotated QueryClient starts with no authorization, and the old proof is worthless there", () => {
    const holder = new SessionQueryClient();
    const old = holder.get();

    old.setQueryData(previewKeyFor(subject()), preview());

    const oldStore = previewAuthorizations(old);

    oldStore.markViewed(subject());

    const proof = oldStore.proofFor(subject()) as PreviewProof;

    holder.rotate();

    const next = holder.get();
    const nextStore = previewAuthorizations(next);

    assert.notEqual(nextStore, oldStore);
    assert.equal(nextStore.proofFor(subject()), null);
    assert.equal(nextStore.verify(proof, { id: "rule-1", version: 3 }), false);
  });

  it("another user's proof is not valid for a subject of a different user", () => {
    const { client, store } = viewed();
    const proof = store.proofFor(subject()) as PreviewProof;

    assert.equal(store.proofFor(subject({ userId: USER_B })), null);
    // Same fields but the other user's cache holds nothing.
    client.setQueryData(previewKeyFor(subject({ userId: USER_B })), preview());
    assert.equal(store.proofFor(subject({ userId: USER_B })), null, "never viewed by B");
    assert.equal(store.verify(proof, { id: "rule-1", version: 3 }), true, "A's own proof is unaffected");
  });
});
