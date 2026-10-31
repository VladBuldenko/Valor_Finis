import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import { QueryClient } from "@tanstack/react-query";

import { ApiError } from "../../api/api-error.ts";
import {
  AUTO_ENABLE_BLOCKED_MESSAGE,
  ActionBlockedError,
  applyRuleChangeInvalidation,
  createRuleActionRunner,
  createSubmitGuard,
  getRuleActionAvailability,
  isAutoEnableBlocked,
  planRuleChangeInvalidation,
} from "./financial-rule-actions.ts";
import { describeRuleError } from "./financial-rule-errors.ts";
import { financialRuleKeys } from "./financial-rule-query-keys.ts";
import { RULE_STATUSES, type FinancialRule, type RuleAction, type RuleStatus } from "./financial-rule.types.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const ACCOUNT = "11111111-1111-4111-8111-111111111111";
const stamp = { user_id: "u", version: 1, active_since: null, created_at: "t", updated_at: "t", description: null };

const allocation = (status: RuleStatus, mode: "AUTO" | "CONFIRM"): FinancialRule => ({
  ...stamp, id: "r1", name: "Save", status, rule_type: "INCOME_ALLOCATION", source_account_id: ACCOUNT,
  execution_mode: mode, execution_order: 1, effective_from: null, policy: "FIXED_PER_GOAL", percent: null,
  cap_at_target: true, allow_partial: false, income_sources: ["salary"], targets: [],
});
const floor = (status: RuleStatus): FinancialRule => ({
  ...stamp, id: "r2", name: "Floor", status, rule_type: "MINIMUM_UNALLOCATED_FLOOR", source_account_id: ACCOUNT, floor_amount: "10.00",
});
const budgetAlert = (status: RuleStatus): FinancialRule => ({
  ...stamp, id: "r3", name: "B", status, rule_type: "BUDGET_ALERT", budget_id: ACCOUNT,
});

function fakeApi() {
  const calls: string[] = [];
  const api = {
    enableRule: async (id: string) => { calls.push(`enable ${id}`); return allocation("enabled", "CONFIRM"); },
    pauseRule: async (id: string) => { calls.push(`pause ${id}`); return allocation("paused", "CONFIRM"); },
    disableRule: async (id: string) => { calls.push(`disable ${id}`); return allocation("disabled", "CONFIRM"); },
    deleteRule: async (id: string) => { calls.push(`delete ${id}`); },
  };

  return { calls, runner: createRuleActionRunner(api) };
}

describe("lifecycle availability follows the backend status machine", () => {
  const expected: Record<RuleStatus, RuleAction[]> = {
    draft: ["enable"], enabled: ["pause", "disable"], paused: ["enable", "disable"], disabled: ["enable"],
  };

  it("offers exactly the allowed actions for a CONFIRM rule", () => {
    for (const status of RULE_STATUSES) {
      const a = getRuleActionAvailability(allocation(status, "CONFIRM"));
      const offered = (["enable", "pause", "disable"] as const).filter((action) => a[action].available);

      assert.deepEqual([...offered].sort(), [...expected[status]].sort(), status);
    }
  });

  it("delete only for draft and off; edit always", () => {
    for (const status of RULE_STATUSES) {
      const a = getRuleActionAvailability(allocation(status, "CONFIRM"));

      assert.equal(a.delete.available, status === "draft" || status === "disabled", status);
      assert.equal(a.edit.available, true);
    }
  });
});

describe("AUTO gating before Preview exists (F5)", () => {
  it("an AUTO allocation rule can never be turned on, with an explanation", () => {
    for (const status of ["draft", "paused", "disabled"] as const) {
      const rule = allocation(status, "AUTO");
      const enable = getRuleActionAvailability(rule).enable;

      assert.equal(isAutoEnableBlocked(rule), true);
      assert.equal(enable.available, false, status);
      assert.equal(enable.reason, AUTO_ENABLE_BLOCKED_MESSAGE);
    }

    assert.match(AUTO_ENABLE_BLOCKED_MESSAGE, /needs an example first/);
    assert.match(AUTO_ENABLE_BLOCKED_MESSAGE, /Ask me first/);
  });

  it("the runner refuses to call the API even if a screen tries", async () => {
    const { calls, runner } = fakeApi();

    for (const status of ["draft", "paused", "disabled"] as const) {
      await assert.rejects(runner.run(allocation(status, "AUTO"), "enable"), ActionBlockedError);
    }

    assert.deepEqual(calls, []);
  });

  it("CONFIRM rules and alert rules are not gated", async () => {
    const { calls, runner } = fakeApi();

    await runner.run(allocation("draft", "CONFIRM"), "enable");
    await runner.run(floor("draft"), "enable");
    await runner.run(budgetAlert("draft"), "enable");
    assert.equal(calls.length, 3);
    assert.equal(isAutoEnableBlocked(floor("draft")), false);
  });

  it("pausing or turning off an AUTO rule is always allowed", async () => {
    const { calls, runner } = fakeApi();

    await runner.run(allocation("enabled", "AUTO"), "pause");
    await runner.run(allocation("enabled", "AUTO"), "disable");
    assert.deepEqual(calls, ["pause r1", "disable r1"]);
  });
});

describe("runner: transitions and delete", () => {
  it("blocks transitions the status machine does not offer, before any request", async () => {
    const { calls, runner } = fakeApi();

    await assert.rejects(runner.run(allocation("enabled", "CONFIRM"), "enable"), ActionBlockedError);
    await assert.rejects(runner.run(allocation("draft", "CONFIRM"), "pause"), ActionBlockedError);
    await assert.rejects(runner.run(allocation("disabled", "CONFIRM"), "disable"), ActionBlockedError);
    await assert.rejects(runner.remove(allocation("enabled", "CONFIRM")), ActionBlockedError);
    assert.deepEqual(calls, []);
  });

  it("deletes a draft or off rule", async () => {
    const { calls, runner } = fakeApi();

    await runner.remove(allocation("draft", "CONFIRM"));
    await runner.remove(allocation("disabled", "AUTO"));
    assert.deepEqual(calls, ["delete r1", "delete r1"]);
  });

  it("backend conflicts surface through the stable-code mapper, unknown codes safely", async () => {
    const conflict = new ApiError({ kind: "http", status: 409, code: "financial_rule_invalid_transition", message: "x" });
    const body = JSON.stringify({ detail: "Traceback (most recent call last) at app.py:12", code: "brand_new_code" });
    const unknown = new ApiError({ kind: "http", status: 409, code: "brand_new_code", detail: "Traceback (most recent call last) at app.py:12", body, message: `API request failed: 409 ${body}` });

    assert.equal(describeRuleError(conflict, "fallback", { mutation: true }).category, "invalid_transition");
    assert.equal(describeRuleError(unknown, "fallback", { mutation: true }).message, "fallback");
    assert.equal(describeRuleError(new ApiError({ kind: "http", status: 409, code: "financial_rule_deletion_not_allowed", message: "x" }), "f").category, "deletion_blocked");
    assert.match(describeRuleError(new ApiError({ kind: "http", status: 409, code: "financial_rule_activation_not_available", message: "x" }), "f").message, /Alerts are not available yet/);
  });
});

describe("duplicate submission prevention", () => {
  it("lets only one submit in until it leaves", () => {
    const guard = createSubmitGuard();

    assert.equal(guard.tryEnter(), true);
    assert.equal(guard.tryEnter(), false);
    assert.equal(guard.isBusy(), true);
    guard.leave();
    assert.equal(guard.tryEnter(), true);
  });
});

describe("mutation invalidations", () => {
  const U = "user-a";
  const flat = (keys: readonly (readonly unknown[])[]) => keys.map((key) => key.join("/"));

  it("create touches only the rules; edit and status follow the F1 sets", () => {
    assert.deepEqual(flat(planRuleChangeInvalidation(U, { kind: "created", rule: allocation("draft", "CONFIRM") })), ["financial-rules/user-a"]);
    assert.deepEqual(flat(planRuleChangeInvalidation(U, { kind: "edited", rule: allocation("enabled", "CONFIRM"), material: true })),
      ["financial-rules/user-a", "rule-previews/user-a/r1", "rule-proposals/user-a", "rule-executions/user-a", "accounts/user-a"]);
    assert.deepEqual(flat(planRuleChangeInvalidation(U, { kind: "edited", rule: allocation("draft", "CONFIRM"), material: false })), ["financial-rules/user-a"]);
    assert.deepEqual(flat(planRuleChangeInvalidation(U, { kind: "status", rule: allocation("enabled", "CONFIRM"), action: "enable" })),
      ["financial-rules/user-a", "rule-previews/user-a/r1"]);
  });

  it("a floor rule change also refreshes Accounts (floor and rule capacity), once", () => {
    for (const kind of ["edited", "deleted", "status"] as const) {
      const change = kind === "edited" ? { kind, rule: floor("enabled"), material: true } as const
        : kind === "deleted" ? { kind, rule: floor("disabled") } as const
        : { kind, rule: floor("enabled"), action: "enable" } as const;
      const keys = flat(planRuleChangeInvalidation(U, change));

      assert.equal(keys.filter((key) => key === "accounts/user-a").length, 1, kind);
    }

    assert.ok(!flat(planRuleChangeInvalidation(U, { kind: "created", rule: floor("draft") })).includes("accounts/user-a"));
    assert.ok(!flat(planRuleChangeInvalidation(U, { kind: "status", rule: budgetAlert("draft"), action: "enable" })).includes("accounts/user-a"));
  });

  it("applies only to the signed-in user's cache and leaves unrelated families fresh", async () => {
    const client = new QueryClient();
    const seed = (user: string) => {
      client.setQueryData(financialRuleKeys.ruleList(user), []);
      client.setQueryData(["accounts", user], []);
      client.setQueryData(["expenses", user], []);
      client.setQueryData(["income", user], []);
    };

    seed("user-a");
    seed("user-b");
    await applyRuleChangeInvalidation(client, "user-a", { kind: "edited", rule: floor("enabled"), material: true });

    const stale = (key: readonly unknown[]) => client.getQueryState(key)?.isInvalidated === true;

    assert.ok(stale(financialRuleKeys.ruleList("user-a")));
    assert.ok(stale(["accounts", "user-a"]));
    assert.ok(!stale(["expenses", "user-a"]));
    assert.ok(!stale(["income", "user-a"]));
    assert.ok(!stale(financialRuleKeys.ruleList("user-b")));
    assert.ok(!stale(["accounts", "user-b"]));
  });

  it("a signed-out caller cannot build a key or a plan", () => {
    assert.throws(() => planRuleChangeInvalidation("", { kind: "created", rule: floor("draft") }), RangeError);
    assert.throws(() => financialRuleKeys.ruleDetail("", "r1"), RangeError);
  });
});

describe("screens: accessibility, navigation and copy (source checks)", () => {
  const files = readdirSync(HERE).filter((name) => /^(rules-screen|rule-detail-screen|rule-editor-screen|rule-form-fields|option-picker)\.tsx$/.test(name));

  it("finds all five UI files", () => {
    assert.equal(files.length, 5);
  });

  it("every Pressable declares an accessibilityRole", () => {
    for (const name of files) {
      const source = readFileSync(join(HERE, name), "utf8");

      for (const match of source.matchAll(/<Pressable\b/g)) {
        const end = source.indexOf("</Pressable>", match.index);
        const block = source.slice(match.index, end === -1 ? undefined : end);
        const opening = block.slice(0, block.indexOf("\n>") === -1 ? 700 : block.indexOf("\n>"));

        assert.match(opening, /accessibilityRole=/, `${name} @${match.index}`);
      }
    }
  });

  it("every TextInput and Switch has an accessibility label", () => {
    const source = readFileSync(join(HERE, "rule-form-fields.tsx"), "utf8");

    assert.match(source, /<TextInput[\s\S]*?accessibilityLabel=\{label\}/);
    assert.match(source, /<Switch[\s\S]*?accessibilityLabel=\{label\}/);
  });

  it("routes exist, are thin, and are registered in the stack", () => {
    const app = join(HERE, "../../../app/(app)");
    const routes: [string, RegExp][] = [
      ["rules/index.tsx", /RulesScreen/],
      ["rules/new.tsx", /RuleCreateScreen/],
      ["rules/[id]/index.tsx", /RuleDetailScreen/],
      ["rules/[id]/edit.tsx", /RuleEditScreen/],
    ];

    for (const [file, pattern] of routes) {
      assert.match(readFileSync(join(app, file), "utf8"), pattern, file);
    }

    const layout = readFileSync(join(app, "_layout.tsx"), "utf8");

    for (const name of ["rules", "rules/new", "rules/[id]/index", "rules/[id]/edit"]) {
      assert.ok(layout.includes(`name="${name}"`), name);
    }
  });

  it("the Dashboard link is plain: no count and no unread wording", () => {
    const dashboard = readFileSync(join(HERE, "../dashboard/dashboard-screen.tsx"), "utf8");
    const block = dashboard.slice(dashboard.indexOf('<Link href="/rules"'), dashboard.indexOf('<Link href="/receipts/upload"'));

    assert.match(block, />Rules</);
    assert.doesNotMatch(block, /unread|\{[^}]*(count|length)[^}]*\}/i);
  });

  it("does not mount the evaluation trigger or call evaluate (F4 owns it)", () => {
    for (const name of files) {
      const source = readFileSync(join(HERE, name), "utf8");

      assert.doesNotMatch(source, /evaluateRules|watchForeground|createRulesEvaluationTrigger|AppState/, name);
    }
  });

  it("uses only the typed service for requests (no apiRequest or fetch in screens)", () => {
    for (const name of files) {
      assert.doesNotMatch(readFileSync(join(HERE, name), "utf8"), /apiRequest|\bfetch\(/, name);
    }
  });

  it("no screen offers an enable call that bypasses the guarded runner", () => {
    const detail = readFileSync(join(HERE, "rule-detail-screen.tsx"), "utf8");

    assert.doesNotMatch(detail, /financialRulesService\.enableRule/);
    assert.match(detail, /runner\.run\(/);
  });
});
