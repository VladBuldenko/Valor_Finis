// VF-GOALS-PLANNING-002C1: wording for "Upcoming bills". Fixtures are what the backend
// returns (the arithmetic is tested in services/api tests/unit/future_obligations);
// the app must show them as given, keep currencies apart, and never imply a bill is
// paid, set aside, recorded as an expense, compared with past spending or affordable.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import { findForbiddenCopy } from "../financial-rules/financial-rule-forbidden-copy.ts";
import {
  BILLS_ARCHIVED_EMPTY,
  BILLS_EMPTY,
  BILLS_INTRO,
  BILLS_NOT_PAID,
  BILLS_SCOPE,
  BILLS_SEPARATE_FROM_GOALS,
  BILLS_TITLE,
  FORM_NOT_PAID,
  archiveConfirmation,
  billCount,
  goalsCardLines,
  hasNoUpcomingBills,
  monthGroups,
  obligationLines,
  scheduleLabel,
  summaryLines,
  thisMonthHeadline,
} from "./future-obligation-view.ts";
import type { FutureObligation, UpcomingMonth, UpcomingObligations } from "./future-obligation.types.ts";

const HERE = dirname(fileURLToPath(import.meta.url));

const month = (start: string, over: Partial<UpcomingMonth> = {}): UpcomingMonth => ({
  period_start: start,
  period_end: start,
  occurrence_count: 0,
  base_currency_total: "0.00",
  totals_by_currency: [],
  occurrences: [],
  ...over,
});

const rent = (due: string) => ({ obligation_id: "o1", name: "Rent", schedule: "monthly" as const, due_date: due, amount: "950.00", currency: "EUR" });
const tax = { obligation_id: "o2", name: "Tax", schedule: "one_time" as const, due_date: "2026-11-30", amount: "850.00", currency: "EUR" };

const upcoming = (over: Partial<UpcomingObligations> = {}): UpcomingObligations => ({
  as_of: "2026-11-16",
  base_currency: "EUR",
  horizon_months: 12,
  window_start: "2026-11-01",
  window_end: "2027-10-31",
  is_base_total_complete: true,
  excluded_currencies: [],
  base_currency_window_total: "1800.00",
  totals_by_currency: [{ currency: "EUR", total: "1800.00", occurrence_count: 2 }],
  months: [
    month("2026-11-01", {
      occurrence_count: 2,
      base_currency_total: "1800.00",
      totals_by_currency: [{ currency: "EUR", total: "1800.00", occurrence_count: 2 }],
      occurrences: [rent("2026-11-20"), tax],
    }),
    month("2026-12-01"),
    month("2027-01-01"),
    month("2027-02-01"),
  ],
  ...over,
});

const bill = (over: Partial<FutureObligation> = {}): FutureObligation => ({
  id: "b1",
  user_id: "u1",
  name: "Rent",
  description: null,
  schedule: "monthly",
  amount: "950.00",
  currency: "EUR",
  first_due_date: "2026-11-20",
  final_due_date: null,
  status: "active",
  next_due_date: "2026-11-20",
  client_request_id: null,
  created_at: "",
  updated_at: "",
  ...over,
});

describe("this month", () => {
  it("shows the base-currency total for the rest of the month exactly as the backend sent it", () => {
    assert.deepEqual(thisMonthHeadline(upcoming()), { label: "Bills due for the rest of this month", amount: "1800.00 EUR" });
    assert.equal(thisMonthHeadline(upcoming({ months: [] })), null);
  });

  it("counts the bills due, and says plainly when none is", () => {
    assert.equal(summaryLines(upcoming())[0], "2 bills due between today and the end of the month.");
    assert.equal(summaryLines(upcoming({ months: [month("2026-11-01", { occurrence_count: 1 })] }))[0], "1 bill due between today and the end of the month.");
    assert.equal(summaryLines(upcoming({ months: [month("2026-11-01")] }))[0], "No bills fall due for the rest of this month.");
  });

  it("states the 12-month total in each currency, without a plus sign", () => {
    const lines = summaryLines(upcoming());

    assert.equal(lines[lines.length - 1], "Next 12 months: 1800.00 EUR");
  });
});

describe("mixed currencies are never combined", () => {
  const mixed = upcoming({
    is_base_total_complete: false,
    excluded_currencies: ["GBP", "USD"],
    base_currency_window_total: "1800.00",
    totals_by_currency: [
      { currency: "EUR", total: "1800.00", occurrence_count: 2 },
      { currency: "GBP", total: "7.50", occurrence_count: 1 },
      { currency: "USD", total: "40.00", occurrence_count: 1 },
    ],
    months: [
      month("2026-11-01", {
        occurrence_count: 3,
        base_currency_total: "950.00",
        totals_by_currency: [
          { currency: "EUR", total: "950.00", occurrence_count: 1 },
          { currency: "GBP", total: "7.50", occurrence_count: 1 },
          { currency: "USD", total: "40.00", occurrence_count: 1 },
        ],
        occurrences: [rent("2026-11-20")],
      }),
    ],
  });

  it("names the other currencies and says they are not added to the base totals", () => {
    assert.ok(summaryLines(mixed).some((line) => line === "Bills in GBP, USD are listed separately and are not added to the EUR totals."));
  });

  it("lists each currency's total on its own, separated without a plus sign", () => {
    const lines = summaryLines(mixed);

    assert.equal(lines[lines.length - 1], "Next 12 months: 1800.00 EUR; 7.50 GBP; 40.00 USD");
    assert.equal(monthGroups(mixed)[0].value, "950.00 EUR; 7.50 GBP; 40.00 USD (3 bills)");
    assert.ok(![...lines, monthGroups(mixed)[0].value].some((text) => text.includes("+")));
  });

  it("the Goals card shows the per-currency totals and says they are not added", () => {
    const lines = goalsCardLines(mixed);

    assert.match(lines[1], /Next 12 months: 1800\.00 EUR; 7\.50 GBP; 40\.00 USD\. Bills in different currencies are not added together\./);
  });

  it("a complete total is shown as a single base-currency amount on the Goals card", () => {
    assert.deepEqual(goalsCardLines(upcoming()), ["2 bills due between today and the end of the month.", "Next 12 months: 1800.00 EUR"]);
  });
});

describe("the 12 months", () => {
  it("lists each month with its bills, in the backend's order", () => {
    const [first] = monthGroups(upcoming());

    assert.equal(first.label, "2026-11");
    assert.equal(first.value, "1800.00 EUR (2 bills)");
    assert.deepEqual(first.items, [
      { label: "2026-11-20 · Rent", value: "950.00 EUR" },
      { label: "2026-11-30 · Tax", value: "850.00 EUR" },
    ]);
  });

  it("shows consecutive months with nothing due as one range, still covering every month", () => {
    const groups = monthGroups(upcoming());

    assert.deepEqual(groups.map((group) => [group.label, group.value]), [["2026-11", "1800.00 EUR (2 bills)"], ["2026-12 to 2027-02", "nothing due"]]);
  });

  it("keeps a single empty month, and separates empty runs around a month with bills", () => {
    const groups = monthGroups(
      upcoming({
        months: [
          month("2026-11-01"),
          month("2026-12-01", { occurrence_count: 1, totals_by_currency: [{ currency: "EUR", total: "10.00", occurrence_count: 1 }], occurrences: [rent("2026-12-20")] }),
          month("2027-01-01"),
          month("2027-02-01"),
        ],
      }),
    );

    assert.deepEqual(groups.map((group) => group.label), ["2026-11", "2026-12", "2027-01 to 2027-02"]);
  });

  it("an empty projection is one range and has nothing to summarize", () => {
    const empty = upcoming({ totals_by_currency: [], base_currency_window_total: "0.00", months: [month("2026-11-01"), month("2026-12-01")] });

    assert.deepEqual(monthGroups(empty).map((group) => group.label), ["2026-11 to 2026-12"]);
    assert.equal(hasNoUpcomingBills(empty), true);
    assert.equal(hasNoUpcomingBills(upcoming()), false);
  });
});

describe("a bill on the list", () => {
  it("a monthly bill shows its amount, next due date and that it has no end", () => {
    assert.deepEqual(obligationLines(bill()), ["Monthly: 950.00 EUR each month", "Next due: 2026-11-20", "No end date"]);
  });

  it("a monthly bill with an end date and a note", () => {
    assert.deepEqual(obligationLines(bill({ final_due_date: "2027-06-20", description: "Flat" })), [
      "Monthly: 950.00 EUR each month",
      "Next due: 2026-11-20",
      "Last due date: 2027-06-20",
      "Flat",
    ]);
  });

  it("a one-time bill has no end line", () => {
    assert.deepEqual(obligationLines(bill({ schedule: "one_time", amount: "850.00" })), ["One-time: 850.00 EUR", "Next due: 2026-11-20"]);
  });

  it("says when no due date is left, and when a bill is archived", () => {
    assert.ok(obligationLines(bill({ next_due_date: null })).includes("No more due dates."));
    assert.ok(obligationLines(bill({ status: "archived", next_due_date: null })).includes("Archived. It does not appear in upcoming bills."));
    assert.ok(!obligationLines(bill({ status: "archived", next_due_date: null })).includes("No more due dates."));
  });

  it("labels and counts", () => {
    assert.equal(scheduleLabel("one_time"), "One-time");
    assert.equal(scheduleLabel("monthly"), "Monthly");
    assert.deepEqual([billCount(0), billCount(1), billCount(2)], ["0 bills", "1 bill", "2 bills"]);
  });

  it("archiving is explained as reversible and as paying nothing", () => {
    const { title, message } = archiveConfirmation("Rent");

    assert.equal(title, "Archive this bill?");
    assert.match(message, /"Rent" will no longer appear in upcoming bills\. You can restore it later\. Nothing is paid or deleted\./);
  });
});

describe("the copy is honest about what a bill is", () => {
  const everything = [
    BILLS_TITLE,
    BILLS_INTRO,
    BILLS_NOT_PAID,
    BILLS_SCOPE,
    BILLS_SEPARATE_FROM_GOALS,
    BILLS_EMPTY,
    BILLS_ARCHIVED_EMPTY,
    FORM_NOT_PAID,
    archiveConfirmation("Rent").title,
    archiveConfirmation("Rent").message,
    ...summaryLines(upcoming()),
    ...summaryLines(upcoming({ excluded_currencies: ["USD"], is_base_total_complete: false })),
    ...goalsCardLines(upcoming()),
    ...goalsCardLines(upcoming({ is_base_total_complete: false })),
    ...monthGroups(upcoming()).flatMap((group) => [group.label, group.value, ...group.items.map((item) => `${item.label} ${item.value}`)]),
    ...obligationLines(bill({ final_due_date: "2027-06-20", description: "Flat" })),
    ...obligationLines(bill({ status: "archived", next_due_date: null })),
  ];

  it("passes the project's forbidden-copy rules (no transfer wording, no promise, no invented balances)", () => {
    for (const text of everything) {
      assert.deepEqual(findForbiddenCopy(text), [], text);
    }
  });

  it("states that adding a bill does not pay it, set money aside or add an expense", () => {
    assert.match(BILLS_NOT_PAID, /does not pay it, set money aside or add an expense/);
    assert.match(FORM_NOT_PAID, /does not pay it, set money aside or add an expense/);
  });

  it("says the bills are only what was entered, not compared with past spending, and no verdict", () => {
    assert.match(BILLS_SCOPE, /only the bills you enter/);
    assert.match(BILLS_SCOPE, /not found from your past spending, and they are not compared with it/);
    assert.match(BILLS_SCOPE, /does not say whether you can cover them/);
  });

  it("keeps bills apart from Goal contributions", () => {
    assert.match(BILLS_SEPARATE_FROM_GOALS, /shown separately from your Goal contributions/);
    assert.match(BILLS_SEPARATE_FROM_GOALS, /not added together/);
  });

  it("makes no affordability, free-cash, paid or reserved claim (a negation such as \"Nothing is paid\" is fine)", () => {
    for (const text of everything) {
      assert.doesNotMatch(text, /\b(you can afford|affordable|free cash|spare|left over|safe to spend|reserved for this bill)\b|(?<!\bnothing )(?<!\bnot )\b(is|are|has been|will be|marked as) paid\b/i, text);
    }
  });

  it("uses ordinary words rather than financial terminology", () => {
    for (const text of everything) {
      assert.doesNotMatch(text, /\b(obligation|liability|accrual|amortiz|forecast|cash ?flow|net flow)\b/i, text);
    }
  });
});

describe("the presentation does no money arithmetic", () => {
  it("has no number parsing, arithmetic or summing", () => {
    const code = readFileSync(join(HERE, "future-obligation-view.ts"), "utf8").replace(/\/\/.*$/gm, "");

    assert.doesNotMatch(code, /parseFloat|Number\(|parseInt|\.toFixed|Math\.|\bBigInt\b|\.reduce\(/);
  });
});
