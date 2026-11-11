// Budget status wording (VF-MVP-CORE-004). The screens show backend figures as text; nothing here may
// recompute, round or clamp a money value.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  formatAmount,
  formatPercent,
  formatPeriodLabel,
  formatPeriodStateLabel,
  formatRiskLabel,
  formatUnresolvedNotice,
} from "./budget-status-presentation.ts";

describe("budget status presentation", () => {
  it("labels every period, lifecycle state and risk the backend can return", () => {
    assert.deepEqual(
      (["weekly", "monthly", "yearly"] as const).map(formatPeriodLabel),
      ["Weekly", "Monthly", "Yearly"],
    );
    assert.deepEqual(
      (["not_started", "active", "ended"] as const).map(formatPeriodStateLabel),
      ["Not started", "Active", "Ended"],
    );
    assert.deepEqual(
      (["healthy", "watch", "at_risk", "exceeded"] as const).map(formatRiskLabel),
      ["On track", "Watch", "At risk", "Exceeded"],
    );
  });

  it("shows an amount exactly as the backend sent it, with no number parsing", () => {
    assert.equal(formatAmount("184.73", "EUR"), "184.73 EUR");
    assert.equal(formatAmount("0.10", "EUR"), "0.10 EUR", "a trailing zero survives (a float would print 0.1)");
    assert.equal(formatAmount("9999999999.99", "USD"), "9999999999.99 USD", "beyond float-safe cents precision");
    assert.equal(formatAmount("0.00", "EUR"), "0.00 EUR");
  });

  it("shows a percentage unclamped, including above 100 for an exceeded budget", () => {
    assert.equal(formatPercent("78.42"), "78.42%");
    assert.equal(formatPercent("100.02"), "100.02%");
    assert.equal(formatPercent("1250.00"), "1250.00%");
  });

  it("counts unresolved legacy expenses with the right grammar", () => {
    assert.equal(formatUnresolvedNotice(1), "1 legacy expense is not included in this total.");
    assert.equal(formatUnresolvedNotice(2), "2 legacy expenses are not included in this total.");
  });
});
