import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { COPY } from "./financial-rule-copy.ts";
import {
  alertLevelInfo,
  alertLevelInfoOrFallback,
  alertMessage,
  executionModeInfo,
  executionStatusInfo,
  isAlertOpen,
  isKnownReasonCode,
  isMaterialRuleEdit,
  isProposalActionable,
  KNOWN_REASON_CODES,
  previewEffectText,
  previewNoticeTexts,
  previewOutcomeInfo,
  proposalOutcome,
  proposalStatusInfo,
  reasonText,
  ruleActionLabel,
  rulePolicyLabel,
  ruleStatusInfo,
  ruleTypeLabel,
  statusAfterAction,
} from "./financial-rule-presentation.ts";
import {
  ALERT_LEVELS,
  EXECUTION_MODES,
  EXECUTION_STATUSES,
  PREVIEW_EFFECTS,
  PREVIEW_OUTCOMES,
  PROPOSAL_STATUSES,
  RULE_ACTIONS,
  RULE_POLICIES,
  RULE_STATUSES,
  RULE_TYPES,
  type RuleAction,
  type RuleStatus,
} from "./financial-rule.types.ts";

describe("every union member has wording", () => {
  it("rule statuses, types, policies, modes and actions", () => {
    for (const status of RULE_STATUSES) assert.ok(ruleStatusInfo(status).label);
    for (const type of RULE_TYPES) assert.ok(ruleTypeLabel(type));
    for (const policy of RULE_POLICIES) assert.ok(rulePolicyLabel(policy));
    for (const mode of EXECUTION_MODES) assert.ok(executionModeInfo(mode).description);
    for (const action of RULE_ACTIONS) assert.ok(ruleActionLabel(action));
  });

  it("execution, proposal, preview outcome and effect statuses", () => {
    for (const status of EXECUTION_STATUSES) assert.ok(executionStatusInfo(status).label);
    for (const status of PROPOSAL_STATUSES) assert.ok(proposalStatusInfo(status).label);
    for (const outcome of PREVIEW_OUTCOMES) assert.ok(previewOutcomeInfo(outcome).label);

    for (const effect of PREVIEW_EFFECTS) {
      assert.equal(previewEffectText(effect) === null, effect === "none");
    }
  });

  it("alert levels have distinct labels and a severity", () => {
    const labels = ALERT_LEVELS.map((level) => alertLevelInfo(level).label);

    assert.equal(new Set(labels).size, ALERT_LEVELS.length);
    assert.ok(alertLevelInfo("exceeded").severity > alertLevelInfo("watch").severity);
  });
});

describe("rule lifecycle", () => {
  const table: Record<RuleStatus, { actions: RuleAction[]; canDelete: boolean }> = {
    draft: { actions: ["enable"], canDelete: true },
    enabled: { actions: ["pause", "disable"], canDelete: false },
    paused: { actions: ["enable", "disable"], canDelete: false },
    disabled: { actions: ["enable"], canDelete: true },
  };

  it("offers exactly the transitions the backend allows", () => {
    for (const status of RULE_STATUSES) {
      assert.deepEqual([...ruleStatusInfo(status).actions], table[status].actions, status);
      assert.equal(ruleStatusInfo(status).canDelete, table[status].canDelete, status);
    }
  });

  it("every offered action leads to the status the backend sets", () => {
    assert.equal(statusAfterAction("enable"), "enabled");
    assert.equal(statusAfterAction("pause"), "paused");
    assert.equal(statusAfterAction("disable"), "disabled");
  });

  it("only name and description edits are non-material", () => {
    assert.equal(isMaterialRuleEdit(["name"]), false);
    assert.equal(isMaterialRuleEdit(["name", "description"]), false);
    assert.equal(isMaterialRuleEdit(["name", "percent"]), true);
    assert.equal(isMaterialRuleEdit(["targets"]), true);
    assert.equal(isMaterialRuleEdit([]), false);
  });
});

describe("proposal outcomes come from the returned status (C5)", () => {
  it("confirm that executed", () => {
    const result = proposalOutcome("confirm", "executed");

    assert.equal(result.matchesRequest, true);
    assert.match(result.message, /Reserved/);
  });

  it("confirm that was only partly applied says so", () => {
    assert.match(proposalOutcome("confirm", "executed_partial").message, /Partly/);
  });

  it("confirm that returns expired / cancelled / rejected is NOT shown as success", () => {
    for (const status of ["expired", "cancelled", "rejected"] as const) {
      const result = proposalOutcome("confirm", status);

      assert.equal(result.matchesRequest, false, status);
      assert.match(result.message, /Nothing was reserved/, status);
    }
  });

  it("reject that returned rejected matches; reject that returned executed does not", () => {
    assert.equal(proposalOutcome("reject", "rejected").matchesRequest, true);
    assert.equal(proposalOutcome("reject", "executed").matchesRequest, false);
  });

  it("an undecided proposal is not a result and stays actionable", () => {
    assert.equal(proposalOutcome("confirm", "awaiting_confirmation").matchesRequest, false);
    assert.equal(isProposalActionable("awaiting_confirmation"), true);

    for (const status of PROPOSAL_STATUSES.filter((value) => value !== "awaiting_confirmation")) {
      assert.equal(isProposalActionable(status), false, status);
    }
  });
});

describe("reason codes", () => {
  it("every known code has its own text", () => {
    assert.equal(KNOWN_REASON_CODES.length, 11);

    for (const code of KNOWN_REASON_CODES) {
      assert.ok(isKnownReasonCode(code));
      assert.notEqual(reasonText(code), COPY.fallbackReason, code);
    }
  });

  it("null means no reason; an unknown code gets the generic text and is never echoed", () => {
    assert.equal(reasonText(null), null);
    assert.equal(reasonText("some_future_code"), COPY.fallbackReason);
    assert.ok(!String(reasonText("secret_internal_code")).includes("secret_internal_code"));
    // Prototype keys are not "known" codes.
    assert.equal(isKnownReasonCode("constructor"), false);
    assert.equal(reasonText("toString"), COPY.fallbackReason);
  });

  it("never explains a capacity shortfall with an invented total balance", () => {
    assert.doesNotMatch(String(reasonText("insufficient_capacity")), /balance/i);
  });
});

describe("alerts", () => {
  it("unknown levels fall back to a neutral label", () => {
    assert.equal(alertLevelInfoOrFallback("future_level").label, "Needs attention");
    assert.equal(alertLevelInfoOrFallback("watch").label, alertLevelInfo("watch").label);
  });

  it("each rule type produces a sentence; a deleted subject has a safe name", () => {
    const base = { subject_type: "account", subject_name: "Main", level: "breached" } as const;

    assert.match(alertMessage({ ...base, rule_type: "MINIMUM_UNALLOCATED_FLOOR" }), /Main/);
    assert.match(alertMessage({ ...base, rule_type: "OVERCOMMITMENT_ALERT" }), /Main/);
    assert.match(
      alertMessage({ rule_type: "BUDGET_ALERT", subject_type: "budget", subject_name: null, level: "exceeded" }),
      /deleted Budget/,
    );

    for (const level of ALERT_LEVELS) {
      assert.ok(alertMessage({ rule_type: "BUDGET_ALERT", subject_type: "budget", subject_name: "Food", level }));
    }
  });

  it("open means not acknowledged", () => {
    assert.equal(isAlertOpen({ acknowledged_at: null }), true);
    assert.equal(isAlertOpen({ acknowledged_at: "2026-10-01T00:00:00Z" }), false);
  });
});

describe("preview wording", () => {
  it("the hypothetical disclaimer is always present and first, even if the server omitted it", () => {
    assert.equal(previewNoticeTexts([])[0], COPY.previewDisclaimer);
    assert.equal(previewNoticeTexts(["income_not_recorded"])[0], COPY.previewDisclaimer);
  });

  it("known notices map in order, unknown ones are dropped", () => {
    const texts = previewNoticeTexts([
      "hypothetical_snapshot", "income_not_recorded", "real_event_eligibility_not_simulated",
      "other_enabled_rules_not_simulated", "rule_not_enabled", "brand_new_token",
    ]);

    assert.equal(texts.length, 5);
    assert.ok(!texts.some((text) => text.includes("brand_new_token")));
    assert.equal(texts.at(-1), COPY.previewRuleNotEnabled);
  });

  it("AUTO would_apply and CONFIRM would_hold are worded differently", () => {
    assert.notEqual(previewEffectText("would_apply"), previewEffectText("would_hold"));
    assert.match(String(previewEffectText("would_hold")), /Nothing is reserved until you confirm/);
  });
});
