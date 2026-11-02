// VF-020F6: what a history card says. Every status, every persisted reason
// code, null/unknown handling, verbatim amounts, dates, names and audit rows.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  HISTORY_COPY,
  UNLOADED_DIRECTORY,
  auditLine,
  auditLines,
  buildHistoryCard,
  checkNotice,
  formatDateOnly,
  formatInstant,
  goalName,
  ruleName,
  statusExplanation,
  type NameDirectory,
} from "./execution-history-view.ts";
import { COPY } from "./financial-rule-copy.ts";
import { findForbiddenCopy } from "./financial-rule-forbidden-copy.ts";
import { KNOWN_REASON_CODES, executionStatusInfo, reasonText } from "./financial-rule-presentation.ts";
import { EXECUTION_STATUSES } from "./financial-rule.types.ts";
import {
  GOAL_1,
  GOAL_2,
  PERSISTED_REASON_CODES,
  RULE_1,
  STATUS_REASONS,
  audit,
  execution,
  item,
} from "./history-fixtures.test-support.ts";

const names = (entries: [string, string][], loaded = true): NameDirectory => ({ loaded, names: new Map(entries) });
const rules = names([[RULE_1, "Save for later"]]);
const goals = names([[GOAL_1, "Holiday"]]);
const card = (over = {}) => buildHistoryCard(execution(over), rules, goals);

describe("every execution status", () => {
  it("has its own text label and its own explanation", () => {
    const labels = new Set<string>();
    const explanations = new Set<string>();

    for (const status of EXECUTION_STATUSES) {
      const view = card({ status, reason_code: STATUS_REASONS[status] });

      assert.equal(view.statusLabel, executionStatusInfo(status).label);
      assert.ok(view.statusLabel.length > 0 && view.explanation.length > 0);
      labels.add(view.statusLabel);
      explanations.add(statusExplanation(status));
    }

    assert.equal(labels.size, 8, "eight statuses are told apart by text, not colour");
    assert.equal(explanations.size, 8);
  });

  it("awaiting_confirmation points to the Inbox and offers no decision here", () => {
    const view = card({ status: "awaiting_confirmation", decided_at: null });

    assert.equal(view.awaitingDecision, true);
    assert.match(view.explanation, /Open the Inbox/);
    assert.equal(view.decidedAt, null);
    assert.equal(card({ status: "executed" }).awaitingDecision, false);
  });

  it("executed vs executed_partial are not confused", () => {
    assert.match(card({ status: "executed" }).explanation, /full planned amount/);
    assert.match(card({ status: "executed_partial" }).explanation, /Only part/);
  });

  it("the summary label for a screen reader names the outcome in words", () => {
    const view = card({ status: "blocked", reason_code: "currency_mismatch" });

    assert.match(view.summaryLabel, /^Blocked\. Income 3000\.00 EUR, received 2 Nov 2026\./);
    assert.match(view.summaryLabel, /different currencies/);
  });
});

describe("reason codes", () => {
  it("every code the backend persists has its own known text", () => {
    const seen = new Set<string>();

    for (const code of PERSISTED_REASON_CODES) {
      const text = reasonText(code);

      assert.ok(text !== null && text !== COPY.fallbackReason, `${code} must be mapped`);
      seen.add(text);
    }

    assert.equal(seen.size, PERSISTED_REASON_CODES.length, "no two codes share a text");
  });

  it("the known set is the persisted set plus the preview-only code, which history never receives", () => {
    assert.deepEqual(
      [...KNOWN_REASON_CODES].sort(),
      [...PERSISTED_REASON_CODES, "income_source_not_selected"].sort(),
    );
  });

  it("null stays null and is not the fallback", () => {
    assert.equal(card({ status: "rejected", reason_code: null }).reason, null);
    assert.equal(card({ reason_code: null }).reason, null);
  });

  it("an unknown code gets the neutral text and is never echoed", () => {
    for (const code of ["brand_new_code", "", "INSUFFICIENT_CAPACITY", "__proto__", "toString"]) {
      const view = card({ status: "skipped", reason_code: code });

      assert.equal(view.reason, COPY.fallbackReason, JSON.stringify(code));
      assert.ok(!view.summaryLabel.includes("brand_new_code"));
    }
  });

  it("every code reaches the card for its own status", () => {
    for (const status of EXECUTION_STATUSES) {
      const code = STATUS_REASONS[status];

      assert.equal(card({ status, reason_code: code }).reason, reasonText(code));
    }
  });
});

describe("rejected, expired and cancelled", () => {
  it("rejected and expired (no reason in the backend) are explained from the status", () => {
    const rejected = card({ status: "rejected", reason_code: null });
    const expired = card({ status: "expired", reason_code: null });

    assert.equal(rejected.explanation, "You declined this suggestion.");
    assert.equal(expired.explanation, "This suggestion was not confirmed in time.");
    assert.equal(rejected.nothingReserved, HISTORY_COPY.nothingReserved);
    assert.equal(expired.nothingReserved, HISTORY_COPY.nothingReserved);
    assert.equal(rejected.reason, null);
  });

  it("a cancelled suggestion gets its stored reason and says nothing was reserved once", () => {
    const superseded = card({ status: "cancelled", reason_code: "superseded" });
    const stale = card({ status: "cancelled", reason_code: "stale" });

    assert.equal(superseded.nothingReserved, HISTORY_COPY.nothingReserved);
    assert.equal(stale.nothingReserved, null, "the stale text already says it");
    assert.ok(`${stale.explanation} ${stale.reason}`.split("Nothing was reserved").length === 2);
  });

  it("skipped, blocked and executed never claim 'nothing was reserved' separately", () => {
    for (const status of ["skipped", "blocked", "executed", "executed_partial", "awaiting_confirmation"] as const) {
      assert.equal(card({ status, reason_code: STATUS_REASONS[status] }).nothingReserved, null);
    }
  });
});

describe("amounts are the server's strings", () => {
  it("planned and applied are verbatim; null applied is 'Not applied', never a number", () => {
    const view = card({
      status: "executed_partial",
      items: [
        item({ id: "i1", planned_amount: "300.00", applied_amount: "300.00" }),
        item({ id: "i2", goal_id: GOAL_2, position: 1, planned_amount: "150.5", applied_amount: null, goal_transaction_id: null }),
      ],
    });

    assert.deepEqual(view.goals.map((g) => [g.planned, g.applied, g.reservationRecorded]), [
      ["300.00 EUR", "300.00 EUR", true],
      ["150.5 EUR", HISTORY_COPY.notApplied, false],
    ]);
    assert.notEqual(view.goals[1].applied, "0.00 EUR");
    assert.ok(!view.goals[1].applied.match(/\d/), "a missing amount shows words, not digits");
  });

  it("a server-sent zero is shown as sent and is not confused with null", () => {
    const view = card({ items: [item({ applied_amount: "0.00", goal_transaction_id: null })] });

    assert.equal(view.goals[0].applied, "0.00 EUR");
  });

  it("amounts keep long precision untouched and no total is invented", () => {
    const view = card({
      source_amount: "1234567890.12",
      items: [item({ planned_amount: "0.10", applied_amount: "0.20" }), item({ id: "i2", planned_amount: "0.20", applied_amount: "0.10" })],
    });

    assert.match(view.heading, /1234567890\.12 EUR/);
    assert.deepEqual(view.goals.map((g) => g.planned), ["0.10 EUR", "0.20 EUR"]);
    assert.ok(!JSON.stringify(view).includes("0.30"), "no sum of planned or applied is shown");
  });

  it("stored Goal order is kept, even when it is not by position", () => {
    const view = card({ items: [item({ id: "b", position: 5 }), item({ id: "a", position: 1 })] });

    assert.deepEqual(view.goals.map((g) => g.key), ["b", "a"]);
  });

  it("a run with no items says so (blocked runs have none)", () => {
    const view = card({ status: "blocked", reason_code: "source_account_archived", items: [] });

    assert.deepEqual([view.goals.length, view.goalsNote], [0, HISTORY_COPY.noGoals]);
  });

  it("the recorded figures are labelled as historical and nullable", () => {
    const view = card({ capacity_reservable: "1200.00", capacity_floor: null, capacity_holds: "0.00" });

    assert.deepEqual(view.figures, [
      { label: "Available to reserve then", value: "1200.00 EUR" },
      { label: "Minimum unallocated amount then", value: HISTORY_COPY.notRecorded },
      { label: "Held for pending suggestions then", value: "0.00 EUR" },
    ]);
  });

  it("a currency mismatch does not label Account figures with the income currency", () => {
    const view = card({ status: "blocked", reason_code: "currency_mismatch", items: [], capacity_reservable: "10.00" });

    assert.equal(view.figures[0].value, "10.00");
    assert.equal(view.figuresNote, HISTORY_COPY.currencyNote);
    assert.equal(card().figuresNote, null);
  });
});

describe("dates", () => {
  const original = process.env.TZ;

  it("a calendar date is shown as that date in every time zone", () => {
    try {
      for (const zone of ["America/Los_Angeles", "Pacific/Honolulu", "UTC", "Pacific/Kiritimati", "Asia/Tokyo"]) {
        process.env.TZ = zone;
        assert.equal(formatDateOnly("2026-11-02"), "2 Nov 2026", zone);
        assert.equal(formatDateOnly("2026-01-01"), "1 Jan 2026", zone);
        assert.equal(formatDateOnly("2026-12-31"), "31 Dec 2026", zone);
      }
    } finally {
      if (original === undefined) {
        delete process.env.TZ;
      } else {
        process.env.TZ = original;
      }
    }
  });

  it("anything that is not a real calendar date is 'Unknown date', never raw", () => {
    for (const bad of ["", "2026-02-30", "2026-13-01", "2026-00-10", "2026-11-00", "garbage", "2026-11-02T00:00:00Z", "02/11/2026"]) {
      assert.equal(formatDateOnly(bad), HISTORY_COPY.unknownDate, bad);
    }

    assert.equal(formatDateOnly("2028-02-29"), "29 Feb 2028");
    assert.equal(formatDateOnly("2026-02-29"), HISTORY_COPY.unknownDate);
  });

  it("instants format and bad ones are 'Unknown time'", () => {
    assert.notEqual(formatInstant("2026-11-02T09:00:00+00:00"), HISTORY_COPY.unknownTime);
    assert.equal(formatInstant("nope"), HISTORY_COPY.unknownTime);
    assert.match(card({ created_at: "nope" }).ranAt, /Unknown time/);
  });
});

describe("current names", () => {
  it("a found name is returned; the card holds only the name text", () => {
    assert.equal(ruleName(rules, RULE_1), "Save for later");
    assert.equal(goalName(goals, GOAL_1), "Holiday");
    assert.equal(card().rule, "Save for later");
  });

  it("a name that cannot be found is 'gone' only once the list has loaded", () => {
    assert.equal(ruleName(names([]), RULE_1), HISTORY_COPY.ruleGone);
    assert.equal(goalName(names([]), GOAL_2), HISTORY_COPY.goalGone);
    assert.equal(ruleName(UNLOADED_DIRECTORY, RULE_1), HISTORY_COPY.ruleFallback);
    assert.equal(goalName(UNLOADED_DIRECTORY, GOAL_2), HISTORY_COPY.goalFallback);
    assert.equal(ruleName(names([], false), RULE_1), HISTORY_COPY.ruleFallback, "a failed list is unknown, not deleted");
  });

  it("a renamed rule shows the new name next to the recorded version", () => {
    const view = buildHistoryCard(execution({ rule_version: 7 }), names([[RULE_1, "Renamed"]]), goals);

    assert.deepEqual([view.rule, view.version], ["Renamed", "Recorded version 7"]);
  });
});

describe("audit rows", () => {
  it("each known code is translated with a known actor", () => {
    const codes = ["proposed", "applied", "applied_partial", "skipped", "blocked", "confirmed", "rejected", "expired", "cancelled", "source_changed", "source_deleted"];
    const lines = codes.map((code) => auditLine({ code, actor: "system" }));

    assert.ok(lines.every((line) => line !== null && line.startsWith("Valor Finis: ")));
    assert.equal(new Set(lines).size, codes.length);
    assert.equal(auditLine({ code: "confirmed", actor: "user" }), "You: Confirmed");
  });

  it("an unknown code or actor is dropped, not shown raw", () => {
    assert.equal(auditLine({ code: "mystery", actor: "system" }), null);
    assert.equal(auditLine({ code: "applied", actor: "robot" }), null);
    assert.equal(auditLine({ code: "toString", actor: "system" }), null);
    assert.equal(auditLine({ code: "applied", actor: "constructor" }), null);
  });

  it("details, ids and event ids never reach the card", () => {
    const view = card({
      audit: [audit({ details: { reason_code: "SECRET_DETAIL", changed_fields: ["SECRET_FIELD"] }, related_event_id: "SECRET_EVENT", id: "SECRET_AUDIT" })],
      triggering_event_id: "SECRET_TRIGGER",
    });

    assert.ok(!JSON.stringify(view).includes("SECRET"));
  });

  it("rows are listed oldest first, ties keep the stored order, unreadable times stay put", () => {
    const lines = auditLines([
      audit({ code: "confirmed", actor: "user", created_at: "2026-11-02T10:00:00+00:00" }),
      audit({ code: "proposed", created_at: "2026-11-02T09:00:00+00:00" }),
      audit({ code: "applied", created_at: "2026-11-02T10:00:00+00:00" }),
    ]);

    assert.deepEqual(lines, ["Valor Finis: Suggested to you", "You: Confirmed", "Valor Finis: Reserved for your Goals"]);
    assert.deepEqual(auditLines([audit({ code: "blocked", created_at: "bad" }), audit({ code: "skipped", created_at: "bad" })]).length, 2);
  });

  it("source_changed on a completed run says the record is from the time it ran", () => {
    assert.match(auditLine({ code: "source_changed", actor: "system" }) ?? "", /what happened at the time/);
  });
});

describe("the session check line", () => {
  it("only incomplete and failed say anything, and never promise a retry", () => {
    assert.equal(checkNotice("incomplete"), HISTORY_COPY.checkIncomplete);
    assert.equal(checkNotice("failed"), HISTORY_COPY.checkFailed);

    for (const status of ["not_attempted", "pending", "succeeded"] as const) {
      assert.equal(checkNotice(status), null);
    }
  });
});

describe("wording", () => {
  const every = (): string[] => {
    const strings: string[] = [...Object.values(HISTORY_COPY)];

    for (const status of EXECUTION_STATUSES) {
      strings.push(statusExplanation(status));
    }

    for (const code of PERSISTED_REASON_CODES) {
      strings.push(reasonText(code) ?? "");
    }

    for (const code of ["proposed", "applied", "applied_partial", "skipped", "blocked", "confirmed", "rejected", "expired", "cancelled", "source_changed", "source_deleted"]) {
      strings.push(auditLine({ code, actor: "system" }) ?? "");
    }

    return strings;
  };

  it("breaks no copy rule (C1-C3, C7, C8)", () => {
    for (const text of every()) {
      assert.deepEqual(findForbiddenCopy(text), [], text);
    }
  });

  it("invents no retry, recovery, dead-event or 'failed execution' wording", () => {
    const invented = /\b(retr(y|ies|ied)|recover\w*|dead|failed execution|will be tried again|try again automatically|in the background|guarantee\w*)\b/i;

    for (const text of every()) {
      assert.doesNotMatch(text, invented, text);
    }
  });

  it("never describes a reservation as moving bank money", () => {
    assert.match(COPY.reservationMeaning, /does not move any money in your bank/);
  });
});
