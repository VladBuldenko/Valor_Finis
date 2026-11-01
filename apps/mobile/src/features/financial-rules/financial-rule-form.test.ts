import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AutoActivationBlockedError,
  ERROR_TEXT,
  MATERIAL_EDIT_NOTICE,
  MODE_LOCKED_MESSAGE,
  MODE_ORDER,
  allowedModes,
  buildCreateRequest,
  buildUpdatePlan,
  emptyFormState,
  formStateFromRule,
  isFormValid,
  isNonNegativeMoney,
  isPositiveMoney,
  isValidIsoDate,
  isValidPercent,
  needsMaterialEditNotice,
  normalizeDecimal,
  validateRuleForm,
  type AllocationFormState,
  type RuleFormState,
} from "./financial-rule-form.ts";
import {
  RULE_TYPES,
  type FinancialRule,
  type IncomeAllocationRule,
} from "./financial-rule.types.ts";

const ACCOUNT = "11111111-1111-4111-8111-111111111111";
const GOAL_A = "22222222-2222-4222-8222-222222222222";
const GOAL_B = "33333333-3333-4333-8333-333333333333";
const BUDGET = "44444444-4444-4444-8444-444444444444";

const stamp = { user_id: "u", version: 1, active_since: null, created_at: "t", updated_at: "t", description: null };

const allocationRule = (over: Partial<IncomeAllocationRule> = {}): IncomeAllocationRule => ({
  ...stamp, id: "r1", name: "Save", status: "draft", rule_type: "INCOME_ALLOCATION",
  source_account_id: ACCOUNT, execution_mode: "CONFIRM", execution_order: 1, effective_from: null,
  policy: "FIXED_PER_GOAL", percent: null, cap_at_target: true, allow_partial: false,
  income_sources: ["salary", "freelance", "gift", "other"],
  targets: [{ id: "t1", goal_id: GOAL_A, amount_or_cap: "300.00", position: 0 }], ...over,
});

const allocationForm = (over: Partial<AllocationFormState> = {}): AllocationFormState => ({
  ...(emptyFormState("INCOME_ALLOCATION") as AllocationFormState),
  name: "Save", sourceAccountId: ACCOUNT, targets: [{ goalId: GOAL_A, amount: "300.00" }], ...over,
});

describe("defaults: CONFIRM first", () => {
  it("lists CONFIRM before AUTO and preselects CONFIRM", () => {
    assert.deepEqual([...MODE_ORDER], ["CONFIRM", "AUTO"]);
    assert.equal((emptyFormState("INCOME_ALLOCATION") as AllocationFormState).executionMode, "CONFIRM");
    assert.deepEqual(allowedModes("draft"), ["CONFIRM", "AUTO"]);
    assert.deepEqual(allowedModes(null), ["CONFIRM", "AUTO"]);
  });

  it("uses the backend defaults for the other allocation fields", () => {
    const form = emptyFormState("INCOME_ALLOCATION") as AllocationFormState;

    assert.deepEqual(form.incomeSources, ["salary", "freelance", "gift", "other"]);
    assert.equal(form.capAtTarget, true);
    assert.equal(form.allowPartial, false);
    assert.equal(form.policy, "FIXED_PER_GOAL");
  });

  it("has an empty form for each of the four types, discriminated by ruleType", () => {
    assert.deepEqual(RULE_TYPES.map((type) => emptyFormState(type).ruleType), [...RULE_TYPES]);
  });
});

describe("shape validators", () => {
  it("money", () => {
    for (const ok of ["1", "0.01", "300.00", "9999999999.99"]) assert.ok(isPositiveMoney(ok), ok);
    for (const bad of ["", "0", "0.00", "-1", "1.234", "1e3", "1,5", "abc", "12345678901"]) assert.ok(!isPositiveMoney(bad), bad);
    assert.ok(isNonNegativeMoney("0.00"));
    assert.ok(!isNonNegativeMoney("-0.01"));
  });

  it("percent: above 0 and up to 100, two decimals", () => {
    for (const ok of ["0.01", "12.5", "99.99", "100", "100.00"]) assert.ok(isValidPercent(ok), ok);
    for (const bad of ["", "0", "0.00", "100.01", "101", "1.234", "-5", "abc"]) assert.ok(!isValidPercent(bad), bad);
  });

  it("calendar dates", () => {
    assert.ok(isValidIsoDate("2026-02-28"));
    for (const bad of ["2026-02-30", "2026-13-01", "26-01-01", "2026/01/01", ""]) assert.ok(!isValidIsoDate(bad), bad);
  });
});

describe("editor 1: income allocation", () => {
  it("accepts a valid fixed rule and builds the discriminated create request", () => {
    const request = buildCreateRequest(allocationForm({ description: "  monthly  " }));

    assert.deepEqual(request, {
      name: "Save", description: "monthly", rule_type: "INCOME_ALLOCATION",
      source_account_id: ACCOUNT, execution_mode: "CONFIRM", policy: "FIXED_PER_GOAL",
      cap_at_target: true, allow_partial: false,
      income_sources: ["salary", "freelance", "gift", "other"],
      targets: [{ goal_id: GOAL_A, amount_or_cap: "300.00", position: 0 }],
    });
    assert.equal("percent" in request, false);
    assert.equal("status" in request || "user_id" in request || "version" in request, false);
  });

  it("builds a percent rule with optional caps and an effective date", () => {
    const request = buildCreateRequest(allocationForm({
      policy: "PERCENT_OF_INCOME_WATERFALL", percent: "12.50", allowPartial: true, effectiveFrom: "2026-12-01",
      targets: [{ goalId: GOAL_A, amount: "" }, { goalId: GOAL_B, amount: "500" }],
    }));

    assert.equal(request.rule_type, "INCOME_ALLOCATION");
    if (request.rule_type === "INCOME_ALLOCATION") {
      assert.equal(request.percent, "12.50");
      assert.equal(request.effective_from, "2026-12-01");
      assert.deepEqual(request.targets, [
        { goal_id: GOAL_A, position: 0 },
        { goal_id: GOAL_B, amount_or_cap: "500", position: 1 },
      ]);
    }
  });

  it("can be saved as AUTO (a configuration) but sends no status", () => {
    const request = buildCreateRequest(allocationForm({ executionMode: "AUTO" }));

    assert.equal(request.rule_type === "INCOME_ALLOCATION" && request.execution_mode, "AUTO");
  });

  it("reports every missing or invalid field", () => {
    const errors = validateRuleForm(allocationForm({
      name: " ", sourceAccountId: null, targets: [], incomeSources: [], effectiveFrom: "2026-02-31",
      policy: "PERCENT_OF_INCOME_WATERFALL", percent: "0",
    }));

    assert.deepEqual(Object.keys(errors).sort(), ["effectiveFrom", "incomeSources", "name", "percent", "sourceAccountId", "targets"]);
  });

  it("fixed policy needs a positive amount per Goal; percent policy only validates a cap if given", () => {
    assert.ok(validateRuleForm(allocationForm({ targets: [{ goalId: GOAL_A, amount: "" }] }))[`target:${GOAL_A}`]);
    assert.ok(validateRuleForm(allocationForm({ targets: [{ goalId: GOAL_A, amount: "0" }] }))[`target:${GOAL_A}`]);

    const percent = allocationForm({ policy: "PERCENT_OF_INCOME_WATERFALL", percent: "10" });

    assert.ok(isFormValid(validateRuleForm({ ...percent, targets: [{ goalId: GOAL_A, amount: "" }] })));
    assert.ok(validateRuleForm({ ...percent, targets: [{ goalId: GOAL_A, amount: "-3" }] })[`target:${GOAL_A}`]);
  });

  it("rejects duplicate Goals and more than 50 Goals", () => {
    assert.equal(validateRuleForm(allocationForm({ targets: [{ goalId: GOAL_A, amount: "1" }, { goalId: GOAL_A, amount: "2" }] })).targets, ERROR_TEXT.targetsDuplicate);

    const many = Array.from({ length: 51 }, (_, i) => ({ goalId: `g${i}`, amount: "1" }));

    assert.equal(validateRuleForm(allocationForm({ targets: many })).targets, ERROR_TEXT.targetsTooMany);
  });

  it("buildCreateRequest refuses an invalid form instead of sending it", () => {
    assert.throws(() => buildCreateRequest(allocationForm({ name: "" })), RangeError);
  });
});

describe("editor 2: minimum unallocated floor", () => {
  const form = (floorAmount: string, account: string | null = ACCOUNT): RuleFormState => ({
    ...emptyFormState("MINIMUM_UNALLOCATED_FLOOR"), name: "Floor", sourceAccountId: account, floorAmount,
  } as RuleFormState);

  it("builds the request; zero is allowed", () => {
    assert.deepEqual(buildCreateRequest(form("500.00")), {
      name: "Floor", rule_type: "MINIMUM_UNALLOCATED_FLOOR", source_account_id: ACCOUNT, floor_amount: "500.00",
    });
    assert.ok(isFormValid(validateRuleForm(form("0"))));
  });

  it("requires an Account and a valid amount", () => {
    assert.equal(validateRuleForm(form("-1")).floorAmount, ERROR_TEXT.floorInvalid);
    assert.equal(validateRuleForm(form("1.234")).floorAmount, ERROR_TEXT.floorInvalid);
    assert.equal(validateRuleForm(form("")).floorAmount, ERROR_TEXT.floorInvalid);
    assert.equal(validateRuleForm(form("5", null)).sourceAccountId, ERROR_TEXT.accountRequired);
  });
});

describe("editors 3 and 4: overcommitment and budget alerts", () => {
  it("overcommitment needs only an Account", () => {
    const form = { ...emptyFormState("OVERCOMMITMENT_ALERT"), name: "Over", sourceAccountId: ACCOUNT } as RuleFormState;

    assert.deepEqual(buildCreateRequest(form), { name: "Over", rule_type: "OVERCOMMITMENT_ALERT", source_account_id: ACCOUNT });
    assert.ok(validateRuleForm({ ...form, sourceAccountId: null } as RuleFormState).sourceAccountId);
  });

  it("budget alert needs only a Budget and sends no account", () => {
    const form = { ...emptyFormState("BUDGET_ALERT"), name: "Food", budgetId: BUDGET } as RuleFormState;
    const request = buildCreateRequest(form);

    assert.deepEqual(request, { name: "Food", rule_type: "BUDGET_ALERT", budget_id: BUDGET });
    assert.equal("source_account_id" in request, false);
    assert.ok(validateRuleForm({ ...form, budgetId: null } as RuleFormState).budgetId);
  });

  it("name limits apply to every type", () => {
    for (const type of RULE_TYPES) {
      assert.ok(validateRuleForm({ ...emptyFormState(type), name: "x".repeat(151) } as RuleFormState).name);
    }
  });
});

describe("edit: only changed fields are sent", () => {
  it("an untouched form changes nothing, even across 300 vs 300.00", () => {
    const rule = allocationRule();

    assert.deepEqual(buildUpdatePlan(rule, formStateFromRule(rule)), { update: {}, changedFields: [] });
    assert.deepEqual(buildUpdatePlan(rule, { ...formStateFromRule(rule), targets: [{ goalId: GOAL_A, amount: "300" }] } as RuleFormState).changedFields, []);
  });

  it("round-trips every rule type", () => {
    const rules: FinancialRule[] = [
      allocationRule(),
      { ...stamp, id: "r2", name: "F", status: "enabled", rule_type: "MINIMUM_UNALLOCATED_FLOOR", source_account_id: ACCOUNT, floor_amount: "10.00" },
      { ...stamp, id: "r3", name: "O", status: "draft", rule_type: "OVERCOMMITMENT_ALERT", source_account_id: ACCOUNT },
      { ...stamp, id: "r4", name: "B", status: "draft", rule_type: "BUDGET_ALERT", budget_id: BUDGET },
    ];

    for (const rule of rules) {
      assert.deepEqual(buildUpdatePlan(rule, formStateFromRule(rule)).changedFields, [], rule.rule_type);
    }
  });

  it("sends just the edited fields", () => {
    const plan = buildUpdatePlan(allocationRule(), { ...formStateFromRule(allocationRule()), name: "New", allowPartial: true } as RuleFormState);

    assert.deepEqual(plan.update, { name: "New", allow_partial: true });
  });

  it("switching to the fixed policy clears a stored percent; description can be cleared", () => {
    const rule = allocationRule({ policy: "PERCENT_OF_INCOME_WATERFALL", percent: "10.00", description: "old" });
    const form = { ...formStateFromRule(rule), policy: "FIXED_PER_GOAL", percent: "10.00", description: "", targets: [{ goalId: GOAL_A, amount: "50" }] } as RuleFormState;
    const plan = buildUpdatePlan(rule, form);

    assert.equal(plan.update.policy, "FIXED_PER_GOAL");
    assert.equal(plan.update.percent, null);
    assert.equal(plan.update.description, null);
    assert.deepEqual(plan.update.targets, [{ goal_id: GOAL_A, amount_or_cap: "50", position: 0 }]);
  });

  it("floor, alert and budget edits send only their own field", () => {
    const floor: FinancialRule = { ...stamp, id: "r2", name: "F", status: "enabled", rule_type: "MINIMUM_UNALLOCATED_FLOOR", source_account_id: ACCOUNT, floor_amount: "10.00" };

    assert.deepEqual(buildUpdatePlan(floor, { ...formStateFromRule(floor), floorAmount: "20" } as RuleFormState).update, { floor_amount: "20" });
    assert.throws(() => buildUpdatePlan(floor, emptyFormState("BUDGET_ALERT")), RangeError);
  });
});

describe("AUTO cannot be activated through editing", () => {
  it("on/paused rules are limited to CONFIRM in the editor", () => {
    assert.deepEqual(allowedModes("enabled"), ["CONFIRM"]);
    assert.deepEqual(allowedModes("paused"), ["CONFIRM"]);
    assert.deepEqual(allowedModes("disabled"), ["CONFIRM", "AUTO"]);
  });

  it("a form that makes an enabled or paused rule AUTO is rejected by validation AND by the builder", () => {
    for (const status of ["enabled", "paused"] as const) {
      const rule = allocationRule({ status });
      const form = { ...formStateFromRule(rule), executionMode: "AUTO" } as RuleFormState;

      assert.equal(validateRuleForm(form, { status, originalMode: "CONFIRM" }).executionMode, MODE_LOCKED_MESSAGE);
      assert.throws(() => buildUpdatePlan(rule, form), AutoActivationBlockedError);
    }
  });

  it("draft and off rules may be saved as AUTO (still not turned on)", () => {
    for (const status of ["draft", "disabled"] as const) {
      const rule = allocationRule({ status });
      const plan = buildUpdatePlan(rule, { ...formStateFromRule(rule), executionMode: "AUTO" } as RuleFormState);

      assert.equal(plan.update.execution_mode, "AUTO");
    }
  });

  it("an on rule that is already AUTO can be edited without touching the mode", () => {
    const rule = allocationRule({ status: "enabled", execution_mode: "AUTO" });

    assert.doesNotThrow(() => buildUpdatePlan(rule, { ...formStateFromRule(rule), name: "Renamed" } as RuleFormState));
  });
});

describe("material-edit notice", () => {
  it("shows for on/paused allocation rules when a meaningful field changes", () => {
    assert.ok(needsMaterialEditNotice({ rule_type: "INCOME_ALLOCATION", status: "enabled" }, ["percent"]));
    assert.ok(needsMaterialEditNotice({ rule_type: "INCOME_ALLOCATION", status: "paused" }, ["targets"]));
    assert.match(MATERIAL_EDIT_NOTICE, /replaces any suggestions/);
  });

  it("not for name/description/order, drafts, or other rule types", () => {
    assert.ok(!needsMaterialEditNotice({ rule_type: "INCOME_ALLOCATION", status: "enabled" }, ["name", "description", "execution_order"]));
    assert.ok(!needsMaterialEditNotice({ rule_type: "INCOME_ALLOCATION", status: "draft" }, ["percent"]));
    assert.ok(!needsMaterialEditNotice({ rule_type: "MINIMUM_UNALLOCATED_FLOOR", status: "enabled" }, ["floor_amount"]));
  });
});

describe("normalizeDecimal", () => {
  it("compares text only", () => {
    assert.equal(normalizeDecimal("300.00"), "300");
    assert.equal(normalizeDecimal("0300.50"), "300.5");
    assert.equal(normalizeDecimal("0.10"), "0.1");
    assert.equal(normalizeDecimal(null), null);
  });
});
