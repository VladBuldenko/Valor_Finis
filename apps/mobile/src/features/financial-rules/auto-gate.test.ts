// VF-020F5: the runner enforces the AUTO preview gate by itself, and the
// activation flow around it never resends an ambiguous enable.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { QueryClient } from "@tanstack/react-query";

import {
  ActionBlockedError,
  ActionPreflightError,
  ActionStaleError,
  AUTO_ENABLE_BLOCKED_MESSAGE,
  createRuleActionRunner,
  createSubmitGuard,
  getRuleActionAvailability,
  type RuleChange,
} from "./financial-rule-actions.ts";
import { activateAutoRule, AUTO_ACTIVATION_DIALOG, type ActivationDeps } from "./auto-activation.ts";
import { accountKeys, goalKeys } from "./financial-rule-query-keys.ts";
import { previewAuthorizations, previewKeyFor, type PreviewProof } from "./preview-authorization.ts";
import type { FinancialRule } from "./financial-rule.types.ts";
import { USER_A, allocationRule, apiError, preview } from "./preview-fixtures.test-support.ts";

const INPUTS = { amount: "3000.00", source: "salary" as const };

function world(initial: FinancialRule = allocationRule()) {
  const client = new QueryClient();
  const calls: string[] = [];
  const state = { latest: initial as FinancialRule, enableResult: null as FinancialRule | null, enableError: null as unknown, getError: null as unknown };
  const gate = previewAuthorizations(client);
  const api = {
    getRule: async (id: string) => { calls.push(`get ${id}`); if (state.getError) throw state.getError; return state.latest; },
    enableRule: async (id: string) => {
      calls.push(`enable ${id}`);
      if (state.enableError) throw state.enableError;

      return state.enableResult ?? allocationRule({ status: "enabled" });
    },
    pauseRule: async (id: string) => { calls.push(`pause ${id}`); return allocationRule({ status: "paused" }); },
    disableRule: async (id: string) => { calls.push(`disable ${id}`); return allocationRule({ status: "disabled" }); },
    deleteRule: async (id: string) => { calls.push(`delete ${id}`); },
  };

  function view(rule: FinancialRule = initial): PreviewProof | undefined {
    client.setQueryData(goalKeys.family(USER_A), []);
    client.setQueryData(accountKeys.family(USER_A), []);
    client.setQueryData(previewKeyFor({ userId: USER_A, ruleId: rule.id, ruleVersion: rule.version, inputs: INPUTS }), preview({ rule_version: rule.version }));
    gate.markViewed({ userId: USER_A, ruleId: rule.id, ruleVersion: rule.version, inputs: INPUTS });

    return gate.proofFor({ userId: USER_A, ruleId: rule.id, ruleVersion: rule.version, inputs: INPUTS }) ?? undefined;
  }

  return { client, calls, state, gate, api, runner: createRuleActionRunner(api, gate), view };
}

describe("runner-level gate (independent of any screen)", () => {
  it("AUTO cannot be enabled without a viewed preview: nothing is sent, not even a read", async () => {
    const w = world();

    await assert.rejects(() => w.runner.run(allocationRule(), "enable"), ActionBlockedError);
    await assert.rejects(() => w.runner.run(allocationRule(), "enable", {}), (e: Error) => e.message === AUTO_ENABLE_BLOCKED_MESSAGE);
    assert.deepEqual(w.calls, []);
  });

  it("a preview that was fetched but never viewed gives no proof, so the runner still refuses", async () => {
    const w = world();

    w.client.setQueryData(previewKeyFor({ userId: USER_A, ruleId: "rule-1", ruleVersion: 3, inputs: INPUTS }), preview());
    assert.equal(w.gate.proofFor({ userId: USER_A, ruleId: "rule-1", ruleVersion: 3, inputs: INPUTS }), null);
    await assert.rejects(() => w.runner.run(allocationRule(), "enable"), ActionBlockedError);
    assert.deepEqual(w.calls, []);
  });

  it("a hand-built proof is refused", async () => {
    const w = world();
    const forged = { kind: "preview-proof", userId: USER_A, ruleId: "rule-1", ruleVersion: 3, inputs: INPUTS } as PreviewProof;

    await assert.rejects(() => w.runner.run(allocationRule(), "enable", { proof: forged }), ActionBlockedError);
    assert.deepEqual(w.calls, []);
  });

  it("a runner built without a gate fails closed for AUTO", async () => {
    const w = world();
    const bare = createRuleActionRunner(w.api);

    await assert.rejects(() => bare.run(allocationRule(), "enable", { proof: w.view() }), ActionBlockedError);
    assert.deepEqual(w.calls, []);
  });

  it("with a valid proof the rule is re-read once and enabled once", async () => {
    const w = world();
    const result = await w.runner.run(allocationRule(), "enable", { proof: w.view(), isCurrent: () => true });

    assert.equal(result.status, "enabled");
    assert.deepEqual(w.calls, ["get rule-1", "enable rule-1"]);
  });

  it("a proof for an old version cannot enable a newer version", async () => {
    const w = world();
    const proof = w.view(allocationRule({ version: 3 }));

    await assert.rejects(() => w.runner.run(allocationRule({ version: 4 }), "enable", { proof }), ActionBlockedError);
    assert.deepEqual(w.calls, []);
  });

  it("the latest rule differing in version, mode or status is refused before any POST, and the authorization is revoked", async () => {
    for (const latest of [
      allocationRule({ version: 4 }),
      allocationRule({ execution_mode: "CONFIRM" }),
      allocationRule({ status: "disabled" }),
    ]) {
      const w = world();
      const proof = w.view();

      w.state.latest = latest;
      await assert.rejects(() => w.runner.run(allocationRule(), "enable", { proof }), ActionStaleError);
      assert.deepEqual(w.calls, ["get rule-1"]);
      assert.equal(w.gate.proofFor({ userId: USER_A, ruleId: "rule-1", ruleVersion: 3, inputs: INPUTS }), null);
    }
  });

  it("the session ending during the re-read stops the enable", async () => {
    const w = world();
    let current = true;
    const original = w.api.getRule;

    w.api.getRule = async (id: string) => { const rule = await original(id); current = false; return rule; };
    await assert.rejects(() => createRuleActionRunner(w.api, w.gate).run(allocationRule(), "enable", { proof: w.view(), isCurrent: () => current }), ActionBlockedError);
    assert.ok(!w.calls.some((call) => call.startsWith("enable")));
  });

  it("a failed re-read is a preflight failure and nothing is enabled", async () => {
    const w = world();

    w.state.getError = apiError("timeout");
    await assert.rejects(() => w.runner.run(allocationRule(), "enable", { proof: w.view() }), ActionPreflightError);
    assert.deepEqual(w.calls, ["get rule-1"]);
  });

  it("CONFIRM stays available without any preview and is not re-read", async () => {
    const w = world();
    const confirm = allocationRule({ execution_mode: "CONFIRM" });

    assert.equal(getRuleActionAvailability(confirm).enable.available, true);
    await w.runner.run(confirm, "enable");
    assert.deepEqual(w.calls, ["enable rule-1"]);
  });

  it("pause, disable and the availability of AUTO without a proof are unchanged", () => {
    assert.equal(getRuleActionAvailability(allocationRule()).enable.available, false);
    assert.equal(getRuleActionAvailability(allocationRule(), { autoAuthorized: true }).enable.available, true);
    assert.equal(getRuleActionAvailability(allocationRule({ status: "enabled" }), { autoAuthorized: true }).enable.available, false);
  });
});

describe("activation outcomes", () => {
  function deps(w: ReturnType<typeof world>, over: Partial<ActivationDeps> = {}) {
    const changes: RuleChange[] = [];
    const read: string[] = [];
    const base: ActivationDeps = {
      rule: allocationRule(),
      proof: w.view(),
      run: (rule, proof) => w.runner.run(rule, "enable", { proof, isCurrent: () => true }),
      readBack: async (id) => { read.push(id); return w.api.getRule(id); },
      isCurrent: () => true,
      invalidate: async (change) => { changes.push(change); },
      ...over,
    };

    return { base, changes, read };
  }

  it("success reports the authoritative status and invalidates the rule caches", async () => {
    const w = world();
    const { base, changes } = deps(w);
    const result = await activateAutoRule(base);

    assert.equal(result.kind, "activated");
    assert.deepEqual(changes.map((c) => c.kind), ["status"]);
    assert.equal(w.calls.filter((c) => c.startsWith("enable")).length, 1);
  });

  it("a server answer that is not 'enabled' is reported as such", async () => {
    const w = world();

    w.state.enableResult = allocationRule({ status: "paused" });
    assert.equal((await activateAutoRule(deps(w).base)).kind, "unexpected_status");
  });

  it("a definite server failure is shown, not retried and not read back", async () => {
    const w = world();

    w.state.enableError = apiError("http", 409, "financial_rule_invalid_transition");

    const { base, read } = deps(w);
    const result = await activateAutoRule(base);

    assert.equal(result.kind, "failed");
    assert.equal(w.calls.filter((c) => c.startsWith("enable")).length, 1);
    assert.deepEqual(read, []);
  });

  it("an ambiguous answer is never resent: one read-back decides", async () => {
    for (const error of [apiError("timeout"), apiError("network"), apiError("malformed_response", 200), apiError("http", 503)]) {
      const w = world();

      w.state.enableError = error;
      w.state.latest = allocationRule();

      const { base, read } = deps(w);
      const result = await activateAutoRule(base);

      assert.equal(result.kind, "unknown_pending", error.kind);
      assert.equal(w.calls.filter((c) => c.startsWith("enable")).length, 1, "enable sent once");
      assert.equal(read.length, 1, "one read-back");
    }
  });

  it("an ambiguous answer is resolved when the read-back shows the rule is on", async () => {
    const w = world();

    w.state.enableError = apiError("timeout");

    const { base } = deps(w, { readBack: async () => allocationRule({ status: "enabled" }) });

    assert.equal((await activateAutoRule(base)).kind, "unknown_resolved");
  });

  it("a failing read-back leaves the outcome unknown and claims nothing", async () => {
    const w = world();

    w.state.enableError = apiError("network");

    const { base } = deps(w, { readBack: async () => { throw apiError("network"); } });
    const result = await activateAutoRule(base);

    assert.equal(result.kind, "unknown_pending");
    assert.match(result.kind === "unknown_pending" ? result.message : "", /could not confirm/i);
  });

  it("a changed rule asks for a new example and sends nothing", async () => {
    const w = world();
    const { base } = deps(w);

    w.state.latest = allocationRule({ version: 9 });

    const result = await activateAutoRule(base);

    assert.equal(result.kind, "needs_new_preview");
    assert.ok(!w.calls.some((c) => c.startsWith("enable")));
  });

  it("no proof asks for an example and sends nothing", async () => {
    const w = world();
    const result = await activateAutoRule(deps(w, { proof: undefined }).base);

    assert.equal(result.kind, "needs_new_preview");
    assert.deepEqual(w.calls, []);
  });

  it("a failed pre-enable read is 'not checked' and sends nothing", async () => {
    const w = world();

    w.state.getError = apiError("timeout");

    const result = await activateAutoRule(deps(w).base);

    assert.equal(result.kind, "not_checked");
    assert.ok(!w.calls.some((c) => c.startsWith("enable")));
  });

  it("a session that ended before or during the call neither starts nor invalidates", async () => {
    const w = world();
    const before = deps(w, { isCurrent: () => false });

    assert.equal((await activateAutoRule(before.base)).kind, "session_changed");
    assert.deepEqual(w.calls, []);

    const w2 = world();
    let current = true;
    const during = deps(w2, {
      isCurrent: () => current,
      run: async (rule, proof) => { const rule2 = await w2.runner.run(rule, "enable", { proof }); current = false; return rule2; },
    });

    await activateAutoRule(during.base);
    assert.deepEqual(during.changes, [], "nothing invalidated for a dead session");
  });
});

describe("duplicate taps and the confirmation text", () => {
  it("the submit guard admits one activation at a time", () => {
    const guard = createSubmitGuard();

    assert.equal(guard.tryEnter(), true);
    assert.equal(guard.tryEnter(), false);
    guard.leave();
    assert.equal(guard.tryEnter(), true);
  });

  it("the dialog states every required point and avoids forbidden promises", () => {
    const text = AUTO_ACTIVATION_DIALOG.lines.join(" ");

    assert.match(text, /without asking you to confirm each eligible income/);
    assert.match(text, /No bank transfer takes place\./);
    assert.match(text, /open or refresh the app and after you record income/);
    assert.match(text, /example was hypothetical/);
    assert.doesNotMatch(text, /while the app is closed|in the background|24\/7|guarantee/i);
  });
});
