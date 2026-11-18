// VF-GOALS-PLANNING-002C2: wording and ordering for linking an expense to a bill date.
// Fixtures are what the backend returns (the rules are tested in services/api); the app
// must show them as given and never imply a bill is paid, confirmed, overdue or owed.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import { findForbiddenCopy } from "../financial-rules/financial-rule-forbidden-copy.ts";
import {
  LINKS_EMPTY,
  LINKS_INTRO,
  LINKS_TITLE,
  LINK_MEANING,
  NOT_LINKED_NOTE,
  OCCURRENCE_GONE,
  PICKER_RULES,
  PICKER_TITLE,
  STATUS_LINKED,
  STATUS_NOT_LINKED,
  UPCOMING_PREVIEW_COUNT,
  candidateLines,
  exclusionLines,
  findOccurrence,
  linkConfirmation,
  noCandidatesMessage,
  occurrenceAccessibilityLabel,
  occurrenceAmount,
  occurrenceRowLines,
  occurrenceSections,
  occurrenceTitle,
  statusLabel,
  unlinkConfirmation,
} from "./future-obligation-link-view.ts";
import type {
  CandidateExpense,
  OccurrenceCandidates,
  ReconciliationOccurrence,
  ReconciliationOverview,
} from "./future-obligation-link.types.ts";

const HERE = dirname(fileURLToPath(import.meta.url));

const RENT_NOV: ReconciliationOccurrence = {
  obligation_id: "rent",
  name: "Rent",
  schedule: "monthly",
  obligation_status: "active",
  due_date: "2026-11-30",
  amount: "950.00",
  currency: "EUR",
  is_past: false,
  linked_expense: null,
};

const LINKED_EXPENSE = {
  link_id: "link-1",
  expense_id: "exp-1",
  title: "Rent payment",
  expense_date: "2026-11-10",
  amount: "950.00",
  currency: "EUR",
  linked_at: "2026-11-11T10:00:00Z",
};

const RENT_OCT: ReconciliationOccurrence = {
  ...RENT_NOV,
  due_date: "2026-10-31",
  is_past: true,
  linked_expense: { ...LINKED_EXPENSE, expense_date: "2026-11-02" },
};

const overview = (occurrences: ReconciliationOccurrence[]): ReconciliationOverview => ({
  as_of: "2026-11-16",
  window_start: "2026-08-01",
  window_end: "2027-10-31",
  occurrences,
});

const candidate: CandidateExpense = {
  expense_id: "exp-9",
  title: "Rent November",
  expense_date: "2026-11-10",
  amount: "950.00",
  currency: "EUR",
};

const candidates = (over: Partial<OccurrenceCandidates> = {}): OccurrenceCandidates => ({
  obligation_id: "rent",
  due_date: "2026-11-30",
  amount: "950.00",
  currency: "EUR",
  candidate_limit: 50,
  candidates: [candidate],
  excluded: { different_currency: 0, different_amount: 0, already_linked: 0, dated_in_future: 0 },
  ...over,
});

describe("status and rows", () => {
  it("says whether an expense is linked, never that the bill is paid or unpaid", () => {
    assert.equal(statusLabel(RENT_NOV), "No expense linked");
    assert.equal(statusLabel(RENT_OCT), "Expense linked");
    assert.equal(STATUS_LINKED, "Expense linked");
    assert.equal(STATUS_NOT_LINKED, "No expense linked");
  });

  it("an unlinked date row shows the date, bill, amount and status only", () => {
    assert.equal(occurrenceTitle(RENT_NOV), "2026-11-30 · Rent");
    assert.equal(occurrenceAmount(RENT_NOV), "950.00 EUR");
    assert.deepEqual(occurrenceRowLines(RENT_NOV), ["950.00 EUR", "No expense linked"]);
  });

  it("a linked date row names the linked expense and its recorded date", () => {
    assert.deepEqual(occurrenceRowLines(RENT_OCT), ["950.00 EUR", "Expense linked", "Rent payment · 2026-11-02"]);
  });

  it("an archived bill's date says so", () => {
    assert.ok(occurrenceRowLines({ ...RENT_OCT, obligation_status: "archived" }).includes("This bill is archived."));
  });

  it("the accessibility label carries the date, amount and status", () => {
    assert.equal(occurrenceAccessibilityLabel(RENT_NOV), "2026-11-30 · Rent, 950.00 EUR, No expense linked");
  });

  it("a date without a link is explicitly not a statement that it is unpaid", () => {
    assert.match(NOT_LINKED_NOTE, /does not mean it is unpaid/);
  });
});

describe("sections (the backend's order and is_past are used as given)", () => {
  const jan = { ...RENT_NOV, due_date: "2027-01-31" };
  const sep = { ...RENT_OCT, due_date: "2026-09-30", linked_expense: null };

  it("recent dates come most recent first and coming ones soonest first", () => {
    const sections = occurrenceSections(overview([sep, RENT_OCT, RENT_NOV, jan]), false);

    assert.deepEqual(sections.recent.map((o) => o.due_date), ["2026-10-31", "2026-09-30"]);
    assert.deepEqual(sections.upcoming.map((o) => o.due_date), ["2026-11-30", "2027-01-31"]);
    assert.equal(sections.hiddenUpcoming, 0);
  });

  it("shows a preview of the coming dates and reports how many are hidden", () => {
    const many = Array.from({ length: UPCOMING_PREVIEW_COUNT + 5 }, (_, index) => ({
      ...RENT_NOV,
      due_date: `2027-01-${String(index + 1).padStart(2, "0")}`,
    }));

    const preview = occurrenceSections(overview(many), false);
    const all = occurrenceSections(overview(many), true);

    assert.equal(preview.upcoming.length, UPCOMING_PREVIEW_COUNT);
    assert.equal(preview.hiddenUpcoming, 5);
    assert.equal(all.upcoming.length, UPCOMING_PREVIEW_COUNT + 5);
    assert.equal(all.hiddenUpcoming, 0);
  });

  it("does not change the backend's list", () => {
    const original = overview([sep, RENT_OCT, RENT_NOV]);
    const before = JSON.stringify(original);

    occurrenceSections(original, true);

    assert.equal(JSON.stringify(original), before);
  });

  it("finds the date a route points to, by bill and due date, or null", () => {
    const data = overview([RENT_OCT, RENT_NOV]);

    assert.equal(findOccurrence(data, "rent", "2026-11-30"), RENT_NOV);
    assert.equal(findOccurrence(data, "rent", "2026-12-31"), null); // another month is another date
    assert.equal(findOccurrence(data, "other-bill", "2026-11-30"), null);
  });
});

describe("the picker", () => {
  it("shows each expense's title, recorded date and amount", () => {
    assert.deepEqual(candidateLines(candidate), ["Rent November", "2026-11-10 · 950.00 EUR"]);
  });

  it("explains why other expenses are missing, in plain words, and only what is non-zero", () => {
    assert.deepEqual(exclusionLines(candidates()), []);
    assert.deepEqual(
      exclusionLines(
        candidates({ excluded: { different_currency: 2, different_amount: 1, already_linked: 3, dated_in_future: 1 } }),
      ),
      [
        "1 expense in EUR has a different amount than 950.00 EUR, so cannot be linked.",
        "2 expenses are not in EUR and cannot be linked. Nothing is converted.",
        "3 expenses with this amount are already linked to another bill date.",
        "1 expense with this amount is dated after today and cannot be linked yet.",
      ],
    );
  });

  it("explains an empty picker, naming the exact amount and what to do", () => {
    assert.equal(
      noCandidatesMessage(candidates()),
      "No recorded expense of exactly 950.00 EUR can be linked to this date yet. Record the expense first, or correct its amount in Expenses.",
    );
  });

  it("states the matching rules and never converts", () => {
    assert.match(PICKER_RULES, /same currency with exactly the same amount/);
    assert.match(PICKER_RULES, /never converted/);
  });
});

describe("confirmations", () => {
  it("linking names both records and says nothing is paid or changed", () => {
    const { title, message } = linkConfirmation(RENT_NOV, candidate);

    assert.equal(title, "Link this expense?");
    assert.match(message, /"Rent November" \(2026-11-10, 950\.00 EUR\) will be linked to Rent due 2026-11-30\./);
    assert.match(message, /only records that they go together\. It does not pay anything or change any balance\./);
  });

  it("removing a link says the expense itself is untouched", () => {
    const { title, message } = unlinkConfirmation(RENT_OCT);

    assert.equal(title, "Remove this link?");
    assert.match(message, /"Rent payment" will no longer be linked to Rent due 2026-10-31\. The expense itself is not changed or deleted\./);
  });
});

describe("copy", () => {
  const everything = [
    LINKS_TITLE,
    LINKS_INTRO,
    LINK_MEANING,
    LINKS_EMPTY,
    NOT_LINKED_NOTE,
    PICKER_TITLE,
    PICKER_RULES,
    OCCURRENCE_GONE,
    STATUS_LINKED,
    STATUS_NOT_LINKED,
    ...occurrenceRowLines(RENT_NOV),
    ...occurrenceRowLines(RENT_OCT),
    ...Object.values(linkConfirmation(RENT_NOV, candidate)),
    ...Object.values(unlinkConfirmation(RENT_OCT)),
    ...exclusionLines(candidates({ excluded: { different_currency: 2, different_amount: 1, already_linked: 3, dated_in_future: 1 } })),
    noCandidatesMessage(candidates()),
  ];

  it("passes the project's forbidden-copy rules", () => {
    for (const text of everything) {
      assert.deepEqual(findForbiddenCopy(text), [], text);
    }
  });

  it("says what a link is not: no payment, no bank check", () => {
    assert.match(LINK_MEANING, /does not pay the bill, move money, change an account balance or add an expense/);
    assert.match(LINK_MEANING, /nothing is checked with your bank/);
    assert.match(LINKS_INTRO, /nothing is matched automatically/);
  });

  it("never claims a bill is paid, confirmed, verified, overdue, late or owed (a negation is fine)", () => {
    for (const text of everything) {
      assert.doesNotMatch(
        text,
        /\b(overdue|late|outstanding|you owe|still owed|past due|defaulted|verified|confirmed)\b|(?<!\bnot )(?<!\bnothing )\b(is|are|was|were|has been|will be|marked as) paid\b/i,
        text,
      );
    }
  });

  it("avoids the app's own 'Paid' status wording", () => {
    for (const text of everything) {
      assert.doesNotMatch(text, /^paid$/i, text);
    }
  });
});

describe("the presentation does no money arithmetic", () => {
  it("has no number parsing, arithmetic or summing", () => {
    const code = readFileSync(join(HERE, "future-obligation-link-view.ts"), "utf8").replace(/\/\/.*$/gm, "");

    assert.doesNotMatch(code, /parseFloat|Number\(|parseInt|\.toFixed|Math\.|\bBigInt\b|\.reduce\(/);
  });
});
