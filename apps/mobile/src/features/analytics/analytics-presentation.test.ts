// Dashboard / Analytics wording helpers (VF-MVP-CORE-006). Presentation only: every figure comes from the
// backend as a string and must reach the screen unchanged; nothing here may parse, recompute or invent a number.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  formatAmount,
  formatDateRange,
  formatDirectionLabel,
  formatExpenseCount,
  formatForecastStatusLabel,
  formatPercent,
  formatPeriodLabel,
  formatUnresolvedNotice,
} from "./analytics-presentation.ts";

describe("amounts and percentages are shown exactly as the backend sent them", () => {
  it("never reformats a Decimal string through a number (no float drift, no lost zeros)", () => {
    assert.equal(formatAmount("0.10", "EUR"), "0.10 EUR");
    assert.equal(formatAmount("1234567890.12", "USD"), "1234567890.12 USD");
    assert.equal(formatAmount("-40.00", "EUR"), "-40.00 EUR");
    assert.equal(formatAmount("0.00", "EUR"), "0.00 EUR");
    assert.equal(formatPercent("12.50"), "12.50%");
    assert.equal(formatPercent("0.00"), "0.00%");
  });

  it("can never print undefined, NaN or Infinity for any string the backend can send", () => {
    for (const value of ["0.00", "-1.50", "900.00", "99999999.99"]) {
      assert.doesNotMatch(formatAmount(value, "EUR"), /undefined|NaN|Infinity/);
      assert.doesNotMatch(formatPercent(value), /undefined|NaN|Infinity/);
    }
  });
});

describe("counts and notices", () => {
  it("singularizes exactly one", () => {
    assert.equal(formatExpenseCount(0), "0 expenses");
    assert.equal(formatExpenseCount(1), "1 expense");
    assert.equal(formatExpenseCount(2), "2 expenses");
    assert.equal(formatUnresolvedNotice(1), "1 unresolved expense is not included in this total.");
    assert.equal(formatUnresolvedNotice(3), "3 unresolved expenses are not included in this total.");
  });
});

describe("dates are read from the backend strings, never through a JS Date", () => {
  it("shows one day once and a range with both ends, without any timezone shift", () => {
    assert.equal(formatDateRange("2026-10-05", "2026-10-05"), "2026-10-05");
    assert.equal(formatDateRange("2026-10-01", "2026-10-31"), "2026-10-01 – 2026-10-31");
    assert.equal(formatDateRange("2028-02-01", "2028-02-29"), "2028-02-01 – 2028-02-29");
  });
});

describe("labels", () => {
  it("covers every backend literal", () => {
    assert.deepEqual((["day", "week", "month"] as const).map(formatPeriodLabel), ["Day", "Week", "Month"]);
    assert.deepEqual((["up", "down", "unchanged"] as const).map(formatDirectionLabel), ["Up", "Down", "Unchanged"]);
    assert.equal(formatForecastStatusLabel("available"), "Current spending pace");
    assert.equal(formatForecastStatusLabel("incomplete_data"), "Forecast unavailable");
  });
});
