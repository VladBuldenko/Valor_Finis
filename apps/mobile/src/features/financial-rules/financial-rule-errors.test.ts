import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { ApiError } from "../../api/api-error.ts";
import { SERVER_ERROR_MESSAGE } from "../../api/user-facing-error.ts";
import { COPY } from "./financial-rule-copy.ts";
import { describeRuleError, KNOWN_RULE_ERROR_CODES } from "./financial-rule-errors.ts";

const FALLBACK = "Could not complete that.";

function http(status: number, code: string | null, detail: string | null = "server words"): ApiError {
  return new ApiError({
    kind: "http",
    status,
    code,
    detail,
    body: JSON.stringify({ detail, code }),
    message: `API request failed: ${status} ${JSON.stringify({ detail, code })}`,
  });
}

describe("the BE-1 code is read first", () => {
  const expected: [string, string][] = [
    ["financial_rule_not_found", "not_found"],
    ["rule_proposal_not_found", "not_found"],
    ["rule_alert_not_found", "not_found"],
    ["rule_proposal_stale", "stale"],
    ["financial_rule_already_exists", "conflict"],
    ["financial_rule_invalid_transition", "invalid_transition"],
    ["financial_rule_activation_not_available", "activation_unavailable"],
    ["financial_rule_deletion_not_allowed", "deletion_blocked"],
    ["financial_rule_subject_archived", "subject_archived"],
    ["financial_rule_currency_mismatch", "invalid_config"],
    ["financial_rule_invalid_fields", "invalid_config"],
    ["financial_rule_preview_not_available", "preview_unavailable"],
    ["goal_reservation_capacity_exceeded", "capacity"],
    ["account_archived", "subject_archived"],
    ["goal_archived", "subject_archived"],
    ["validation_error", "validation"],
    ["unauthorized", "auth"],
  ];

  it("maps each known code to its category with fixed wording", () => {
    assert.equal(KNOWN_RULE_ERROR_CODES.length, expected.length);

    for (const [code, category] of expected) {
      const info = describeRuleError(http(409, code), FALLBACK);

      assert.equal(info.category, category, code);
      assert.equal(info.code, code);
      assert.notEqual(info.message, FALLBACK, code);
      assert.ok(!info.message.includes("server words"), code);
    }
  });

  it("the code wins over a misleading status and detail", () => {
    const info = describeRuleError(http(500, "rule_proposal_stale", "Traceback (most recent call last)"), FALLBACK);

    assert.equal(info.category, "stale");
    assert.doesNotMatch(info.message, /Traceback/);
  });

  it("every auth_* code means sign in again", () => {
    for (const code of ["auth_invalid_token", "auth_missing_credentials", "auth_service_unavailable"]) {
      assert.equal(describeRuleError(http(401, code), FALLBACK).category, "auth", code);
    }
  });

  it("stale and capacity messages say nothing was reserved", () => {
    assert.match(describeRuleError(http(409, "rule_proposal_stale"), FALLBACK).message, /Nothing was reserved/);
    assert.match(describeRuleError(http(409, "goal_reservation_capacity_exceeded"), FALLBACK).message, /Nothing was reserved/);
  });
});

describe("unknown codes fall back safely", () => {
  it("an unknown 4xx code uses the shared 4xx message path, never the code itself", () => {
    const info = describeRuleError(http(409, "brand_new_code", "A short domain sentence."), FALLBACK);

    assert.equal(info.category, "unknown");
    assert.equal(info.message, "A short domain sentence.");
    assert.ok(!info.message.includes("brand_new_code"));
  });

  it("a technical detail is replaced by the caller's fallback", () => {
    const info = describeRuleError(http(409, "brand_new_code", 'Traceback: {"x": 1} at app.py:12'), FALLBACK);

    assert.equal(info.message, FALLBACK);
  });

  it("5xx never shows the body", () => {
    const info = describeRuleError(http(500, null, "SELECT * FROM rules"), FALLBACK);

    assert.equal(info.category, "server");
    assert.equal(info.message, SERVER_ERROR_MESSAGE);
    assert.equal(info.retryable, true);
  });

  it("a non-ApiError becomes the fallback and exposes nothing", () => {
    assert.equal(describeRuleError(new Error("secret internals"), FALLBACK).message, FALLBACK);
    assert.equal(describeRuleError("oops", FALLBACK).message, FALLBACK);
    assert.equal(describeRuleError(undefined, FALLBACK).category, "unknown");
  });

  it("never renders raw response JSON", () => {
    const info = describeRuleError(http(418, null, null), FALLBACK);

    assert.doesNotMatch(info.message, /\{|\}|API request failed/);
  });
});

describe("connectivity and mutations", () => {
  const net = (kind: "network" | "timeout") => new ApiError({ kind, message: "x" });

  it("a lost read is a retryable network problem", () => {
    const info = describeRuleError(net("network"), FALLBACK);

    assert.equal(info.category, "network");
    assert.equal(info.retryable, true);
  });

  it("a lost or timed-out MUTATION is 'outcome unknown' and not retryable by hand blindly", () => {
    for (const kind of ["network", "timeout"] as const) {
      const info = describeRuleError(net(kind), FALLBACK, { mutation: true });

      assert.equal(info.category, "outcome_unknown");
      assert.equal(info.message, COPY.outcomeUnknown);
      assert.equal(info.retryable, false);
    }
  });

  it("an unreadable 2xx on a mutation is also 'outcome unknown'", () => {
    const info = describeRuleError(new ApiError({ kind: "malformed_response", message: "x" }), FALLBACK, { mutation: true });

    assert.equal(info.category, "outcome_unknown");
  });

  it("no session and cancelled requests map to auth and a neutral message", () => {
    assert.equal(describeRuleError(new ApiError({ kind: "unauthenticated", message: "x" }), FALLBACK).category, "auth");
    assert.equal(describeRuleError(new ApiError({ kind: "unauthorized", message: "x", status: 401 }), FALLBACK).category, "auth");
    assert.equal(describeRuleError(new ApiError({ kind: "cancelled", message: "x" }), FALLBACK).category, "unknown");
  });
});
