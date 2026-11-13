// Financial Overview wording (VF-MVP-CORE-006): Net is shown with its direction spelled out and is never
// presented as cash or an Account balance; a null savings rate is explained, never shown as 0%.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { FinancialFlowFigures, FinancialOverviewResponse } from "./analytics.types.ts";
import {
  formatBucketPeriodNote,
  formatIncompleteNotice,
  formatNetFlow,
  formatOverviewPeriodNote,
  formatRecordCounts,
  formatSavingsRate,
  hasNoRecords,
  hasUnresolvedRecords,
} from "./financial-overview-presentation.ts";

const figures = (overrides: Partial<FinancialFlowFigures> = {}): FinancialFlowFigures => ({
  income_total: "0.00", expense_total: "0.00", net_flow: "0.00", savings_rate_percent: null,
  income_count: 0, expense_count: 0, unresolved_income_count: 0, unresolved_expense_count: 0, ...overrides,
});

const overview = (overrides: Partial<FinancialOverviewResponse>): FinancialOverviewResponse => ({
  ...figures(), base_currency: "EUR", period_start: "2026-10-01", period_end: "2026-10-31", as_of: "2026-10-15",
  effective_end: "2026-10-15", period_state: "in_progress", data_status: "complete_data", ...overrides,
});

describe("Net", () => {
  it("spells out surplus, deficit and break-even without relying on color or arithmetic", () => {
    assert.equal(formatNetFlow("554.50", "EUR"), "554.50 EUR (surplus)");
    assert.equal(formatNetFlow("-150.00", "EUR"), "-150.00 EUR (deficit)");
    assert.equal(formatNetFlow("0.00", "EUR"), "0.00 EUR (break-even)");
    assert.equal(formatNetFlow("-0.00", "EUR"), "-0.00 EUR (break-even)");
  });

  it("never mentions cash, balance or net worth", () => {
    assert.doesNotMatch(formatNetFlow("1.00", "EUR"), /cash|balance|worth/i);
  });
});

describe("savings rate", () => {
  it("shows the backend's rate as-is, negative included, and explains null instead of showing 0%", () => {
    assert.equal(formatSavingsRate("79.21"), "79.21%");
    assert.equal(formatSavingsRate("-12.50"), "-12.50%");
    assert.equal(formatSavingsRate("0.00"), "0.00%");
    assert.equal(formatSavingsRate(null), "Unavailable (no resolved income in this period)");
  });
});

describe("period notes come from the backend's state, never from the device date", () => {
  it("complete, in progress and future", () => {
    assert.equal(formatOverviewPeriodNote(overview({ period_state: "complete", effective_end: "2026-10-31" })), "Complete month · 2026-10-01 – 2026-10-31");
    assert.equal(formatOverviewPeriodNote(overview({})), "In progress · includes records through 2026-10-15");
    assert.equal(formatOverviewPeriodNote(overview({ period_state: "future", effective_end: null })), "This month has not started yet, so nothing is included.");
    assert.equal(formatOverviewPeriodNote(overview({ effective_end: null })), "In progress");
    assert.equal(formatBucketPeriodNote(true, "2026-09-30"), "Complete month");
    assert.equal(formatBucketPeriodNote(false, "2026-10-15"), "In progress · through 2026-10-15");
  });
});

describe("incomplete data", () => {
  it("is flagged by the unresolved counts and says exactly what is missing", () => {
    assert.equal(hasUnresolvedRecords(figures()), false);
    assert.equal(hasUnresolvedRecords(figures({ unresolved_income_count: 1 })), true);
    assert.equal(hasUnresolvedRecords(figures({ unresolved_expense_count: 2 })), true);
    assert.equal(
      formatIncompleteNotice(figures({ unresolved_income_count: 1, unresolved_expense_count: 2 }), "EUR"),
      "1 income record and 2 expenses could not be counted in EUR and are not included in these totals.",
    );
    assert.equal(
      formatIncompleteNotice(figures({ unresolved_expense_count: 1 }), "EUR"),
      "1 expense could not be counted in EUR and is not included in these totals.",
    );
  });

  it("an empty period is empty only when there are no resolved AND no unresolved records", () => {
    assert.equal(hasNoRecords(figures()), true);
    assert.equal(hasNoRecords(figures({ income_count: 1 })), false);
    assert.equal(hasNoRecords(figures({ unresolved_expense_count: 1 })), false);
  });

  it("counts read naturally", () => {
    assert.equal(formatRecordCounts(1, 1), "1 income record · 1 expense");
    assert.equal(formatRecordCounts(0, 41), "0 income records · 41 expenses");
  });
});
