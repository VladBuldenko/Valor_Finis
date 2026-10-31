import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { QueryClient } from "@tanstack/react-query";

import {
  applyRuleInvalidation,
  evaluationChangedState,
  planRuleInvalidation,
  type RuleInvalidationEvent,
} from "./financial-rule-invalidation.ts";
import { financialRuleKeys } from "./financial-rule-query-keys.ts";
import type { RuleEvaluationResult } from "./financial-rule.types.ts";

const U = "user-a";
const OTHER = "user-b";
const RULE = "rule-1";

const RULES = ["financial-rules", U];
const PROPOSALS = ["rule-proposals", U];
const ALERTS = ["rule-alerts", U];
const EXECUTIONS = ["rule-executions", U];
const PREVIEWS = ["rule-previews", U];
const RULE_PREVIEWS = ["rule-previews", U, RULE];
const GOALS = ["goals", U];
const PROGRESS = ["analytics", "goal-progress", U];
const ACCOUNTS = ["accounts", U];

const idle: RuleEvaluationResult = {
  processed: 0, deferred: 0, failed_retryable: 0, dead: 0, blocked: false, outcomes: {},
  alerts_available: true, alerts_created: 0, alerts_resolved: 0, alerts_failed: false,
};

function plan(event: RuleInvalidationEvent) {
  return planRuleInvalidation(U, event);
}

describe("exact invalidation sets", () => {
  it("rule create touches only the rule list family", () => {
    assert.deepEqual(plan({ type: "rule_created" }), [RULES]);
  });

  it("rule edit: a name-only edit refreshes only the rules", () => {
    assert.deepEqual(plan({ type: "rule_edited", ruleId: RULE, material: false }), [RULES]);
  });

  it("rule edit: a material edit also drops its previews and refreshes cancelled proposals and holds", () => {
    assert.deepEqual(plan({ type: "rule_edited", ruleId: RULE, material: true }), [
      RULES, RULE_PREVIEWS, PROPOSALS, EXECUTIONS, ACCOUNTS,
    ]);
  });

  it("rule delete: the rules and that rule's previews only", () => {
    assert.deepEqual(plan({ type: "rule_deleted", ruleId: RULE }), [RULES, RULE_PREVIEWS]);
  });

  it("enable: rules and that rule's previews; no money moved", () => {
    assert.deepEqual(plan({ type: "rule_status_changed", ruleId: RULE, action: "enable" }), [RULES, RULE_PREVIEWS]);
  });

  it("pause and disable also refresh the cancelled proposals and released holds", () => {
    for (const action of ["pause", "disable"] as const) {
      assert.deepEqual(plan({ type: "rule_status_changed", ruleId: RULE, action }), [
        RULES, RULE_PREVIEWS, PROPOSALS, EXECUTIONS, ACCOUNTS,
      ]);
    }
  });

  it("confirm/reject is decided by the RETURNED status", () => {
    for (const status of ["executed", "executed_partial"] as const) {
      assert.deepEqual(plan({ type: "proposal_decided", decision: "confirm", status }), [
        PROPOSALS, EXECUTIONS, GOALS, PROGRESS, ACCOUNTS,
      ]);
    }

    for (const status of ["rejected", "expired", "cancelled"] as const) {
      // Even when the user pressed confirm: an expired result moved no money.
      for (const decision of ["confirm", "reject"] as const) {
        assert.deepEqual(plan({ type: "proposal_decided", decision, status }), [PROPOSALS, EXECUTIONS, ACCOUNTS]);
      }
    }

    assert.deepEqual(plan({ type: "proposal_decided", decision: "confirm", status: "awaiting_confirmation" }), [PROPOSALS]);
  });

  it("acknowledge touches only alerts", () => {
    assert.deepEqual(plan({ type: "alert_acknowledged" }), [ALERTS]);
  });

  it("evaluate: nothing processed means nothing invalidated", () => {
    assert.deepEqual(plan({ type: "evaluated", result: idle }), []);
    assert.equal(evaluationChangedState(idle), false);
    // blocked/deferred alone do not change anything on screen.
    assert.deepEqual(plan({ type: "evaluated", result: { ...idle, deferred: 2, blocked: true } }), []);
  });

  it("evaluate: processed events refresh proposals and executions", () => {
    assert.deepEqual(plan({ type: "evaluated", result: { ...idle, processed: 1 } }), [PROPOSALS, EXECUTIONS]);
  });

  it("evaluate: a committed outcome also refreshes Goals, Goal Progress and Accounts", () => {
    assert.deepEqual(
      plan({ type: "evaluated", result: { ...idle, processed: 1, outcomes: { executed: 1 } } }),
      [PROPOSALS, EXECUTIONS, GOALS, PROGRESS, ACCOUNTS],
    );
  });

  it("evaluate: alerts are refreshed only when some were created or resolved", () => {
    assert.deepEqual(plan({ type: "evaluated", result: { ...idle, alerts_created: 1 } }), [PROPOSALS, EXECUTIONS, ALERTS]);
    assert.deepEqual(plan({ type: "evaluated", result: { ...idle, alerts_resolved: 1 } }), [PROPOSALS, EXECUTIONS, ALERTS]);
    assert.ok(!plan({ type: "evaluated", result: { ...idle, processed: 1 } }).some((key) => key[0] === "rule-alerts"));
  });

  it("failed or dead events still refresh the history so the failure is visible", () => {
    assert.deepEqual(plan({ type: "evaluated", result: { ...idle, dead: 1 } }), [PROPOSALS, EXECUTIONS]);
    assert.deepEqual(plan({ type: "evaluated", result: { ...idle, failed_retryable: 1 } }), [PROPOSALS, EXECUTIONS]);
  });

  it("a Goal or Account change drops previews and proposals; income drops only previews", () => {
    assert.deepEqual(plan({ type: "goal_or_account_changed" }), [PREVIEWS, PROPOSALS]);
    assert.deepEqual(plan({ type: "income_recorded" }), [PREVIEWS]);
  });

  it("no event ever invalidates unrelated families", () => {
    const events: RuleInvalidationEvent[] = [
      { type: "rule_created" },
      { type: "rule_edited", ruleId: RULE, material: true },
      { type: "rule_deleted", ruleId: RULE },
      { type: "rule_status_changed", ruleId: RULE, action: "disable" },
      { type: "proposal_decided", decision: "confirm", status: "executed" },
      { type: "alert_acknowledged" },
      { type: "evaluated", result: { ...idle, processed: 1, outcomes: { executed: 1 }, alerts_created: 1 } },
      { type: "goal_or_account_changed" },
      { type: "income_recorded" },
    ];
    const allowed = new Set(["financial-rules", "rule-proposals", "rule-alerts", "rule-executions", "rule-previews", "goals", "accounts", "analytics"]);

    for (const event of events) {
      for (const key of plan(event)) {
        assert.ok(allowed.has(String(key[0])), `${event.type} -> ${String(key[0])}`);
        assert.ok(key[0] !== "analytics" || key[1] === "goal-progress", `${event.type} touches analytics ${String(key[1])}`);
        assert.ok(key.includes(U), `${event.type} key lacks the user id`);
      }
    }
  });
});

describe("applying a set to a real QueryClient", () => {
  const seed = (client: QueryClient, user: string) => {
    const data: [readonly unknown[], unknown][] = [
      [financialRuleKeys.ruleList(user), []],
      [financialRuleKeys.proposalList(user), {}],
      [financialRuleKeys.alertList(user), {}],
      [financialRuleKeys.executionList(user), {}],
      [["goals", user], []],
      [["accounts", user], []],
      [["income", user], []],
      [["expenses", user], []],
      [["budgets", user], []],
      [["account-transfers", user], []],
      [["analytics", "financial-overview", user, 2026, 10], {}],
      [["analytics", "goal-progress", user], []],
    ];

    for (const [key, value] of data) {
      client.setQueryData(key, value);
    }
  };

  const invalidated = (client: QueryClient, key: readonly unknown[]) => client.getQueryState(key)?.isInvalidated === true;

  it("a confirm that executed refreshes exactly its set and leaves unrelated caches fresh", async () => {
    const client = new QueryClient();

    seed(client, U);
    seed(client, OTHER);
    await applyRuleInvalidation(client, U, { type: "proposal_decided", decision: "confirm", status: "executed" });

    for (const key of [
      financialRuleKeys.proposalList(U), financialRuleKeys.executionList(U),
      ["goals", U], ["accounts", U], ["analytics", "goal-progress", U],
    ]) {
      assert.ok(invalidated(client, key), JSON.stringify(key));
    }

    for (const key of [
      financialRuleKeys.ruleList(U), financialRuleKeys.alertList(U), ["income", U], ["expenses", U],
      ["budgets", U], ["account-transfers", U], ["analytics", "financial-overview", U, 2026, 10],
    ]) {
      assert.ok(!invalidated(client, key), `${JSON.stringify(key)} must stay fresh`);
    }

    // Another user's entries are never touched.
    assert.ok(!invalidated(client, financialRuleKeys.proposalList(OTHER)));
    assert.ok(!invalidated(client, ["goals", OTHER]));
  });

  it("never removes cached data (invalidate, not clear)", async () => {
    const client = new QueryClient();

    seed(client, U);
    await applyRuleInvalidation(client, U, { type: "rule_status_changed", ruleId: RULE, action: "disable" });
    assert.deepEqual(client.getQueryData(financialRuleKeys.ruleList(U)), []);
  });

  it("an empty plan invalidates nothing", async () => {
    const client = new QueryClient();

    seed(client, U);
    await applyRuleInvalidation(client, U, { type: "evaluated", result: idle });
    assert.ok(client.getQueryCache().getAll().every((query) => !query.state.isInvalidated));
  });
});
