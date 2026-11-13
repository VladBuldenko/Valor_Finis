// Calendar-month arithmetic behind the Overview month selector and the Dashboard period (VF-MVP-CORE-006).
// Pure calendar numbers: no money, and no YYYY-MM-DD string ever becomes a JS Date (UTC day shifts).
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  compareCalendarMonths,
  formatCalendarMonthLabel,
  formatPeriodMonthLabel,
  getLocalCalendarMonth,
  isSameCalendarMonth,
  nextCalendarMonth,
  previousCalendarMonth,
} from "./calendar-month.ts";

describe("month navigation", () => {
  it("crosses year boundaries in both directions", () => {
    assert.deepEqual(previousCalendarMonth({ year: 2026, month: 1 }), { year: 2025, month: 12 });
    assert.deepEqual(nextCalendarMonth({ year: 2026, month: 12 }), { year: 2027, month: 1 });
    assert.deepEqual(previousCalendarMonth({ year: 2026, month: 11 }), { year: 2026, month: 10 });
    assert.deepEqual(nextCalendarMonth({ year: 2028, month: 2 }), { year: 2028, month: 3 });
  });

  it("previous then next returns to the same month for all twelve months", () => {
    for (let month = 1; month <= 12; month += 1) {
      assert.deepEqual(nextCalendarMonth(previousCalendarMonth({ year: 2026, month })), { year: 2026, month });
    }
  });

  it("compares chronologically across years", () => {
    assert.ok(compareCalendarMonths({ year: 2025, month: 12 }, { year: 2026, month: 1 }) < 0);
    assert.ok(compareCalendarMonths({ year: 2026, month: 2 }, { year: 2026, month: 1 }) > 0);
    assert.equal(isSameCalendarMonth({ year: 2026, month: 5 }, { year: 2026, month: 5 }), true);
    assert.equal(isSameCalendarMonth({ year: 2026, month: 5 }, { year: 2025, month: 5 }), false);
  });
});

describe("the device's LOCAL month", () => {
  it("is read with local accessors, so the last evening of a month stays in that month", () => {
    assert.deepEqual(getLocalCalendarMonth(new Date(2026, 9, 31, 23, 59, 59)), { year: 2026, month: 10 });
    assert.deepEqual(getLocalCalendarMonth(new Date(2026, 10, 1, 0, 0, 0)), { year: 2026, month: 11 });
    assert.deepEqual(getLocalCalendarMonth(new Date(2028, 1, 29, 12, 0, 0)), { year: 2028, month: 2 });
  });
});

describe("labels", () => {
  it("names the month for the selector and for backend period_start strings, read straight from the string", () => {
    assert.equal(formatCalendarMonthLabel({ year: 2026, month: 9 }), "September 2026");
    assert.equal(formatPeriodMonthLabel("2026-09-01"), "September 2026");
    assert.equal(formatPeriodMonthLabel("2027-01-01"), "January 2027");
    assert.equal(formatPeriodMonthLabel("garbage"), "garbage", "an unexpected value is shown as-is, never guessed");
  });
});
