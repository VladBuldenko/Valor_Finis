// VF-020F2 (M09): Account contract and capacity presentation.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import { findForbiddenCopy } from "../financial-rules/financial-rule-forbidden-copy.ts";
import {
  CAPACITY_FOOTNOTE,
  CAPACITY_SECTION_TITLE,
  NEGATIVE_CAPACITY_HINT,
  getAccountCapacityRows,
  isNegativeDecimalString,
} from "./account-capacity-presentation.ts";
import type { Account } from "./account.types.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const BACKEND_SCHEMA = join(HERE, "../../../../../services/api/app/modules/accounts/account_schemas.py");

const base = {
  currency: "EUR",
  reservable_amount: "1200.00",
  minimum_unallocated_floor: "500.00",
  active_rule_holds: "100.00",
  rule_capacity: "600.00",
};

describe("Account type contract", () => {
  it("declares the three rule fields as decimal strings (compile-time)", () => {
    const account: Pick<Account, "minimum_unallocated_floor" | "active_rule_holds" | "rule_capacity"> = {
      minimum_unallocated_floor: "0.00",
      active_rule_holds: "0.00",
      rule_capacity: "-1.00",
    };

    // @ts-expect-error money is a string, never a number
    const bad: Pick<Account, "rule_capacity"> = { rule_capacity: 1 };

    assert.equal(typeof account.rule_capacity, "string");
    void bad;
  });

  it("matches the backend AccountResponse field names exactly", () => {
    const source = readFileSync(BACKEND_SCHEMA, "utf8");

    for (const field of ["minimum_unallocated_floor", "active_rule_holds", "rule_capacity"]) {
      assert.match(source, new RegExp(`^    ${field}: Decimal = Field\\(`, "m"), field);
    }
  });
});

describe("capacity rows", () => {
  it("shows available to reserve, floor, holds and rule capacity, in the Account's currency", () => {
    const rows = getAccountCapacityRows(base);

    assert.deepEqual(rows.map((row) => [row.id, row.label, row.value]), [
      ["reservable", "Available to reserve", "1200.00 EUR"],
      ["floor", "Minimum unallocated floor", "500.00 EUR"],
      ["holds", "Active rule holds", "100.00 EUR"],
      ["rule_capacity", "Available for rules", "600.00 EUR"],
    ]);
  });

  it("renders decimal strings exactly: no rounding, no number formatting", () => {
    const rows = getAccountCapacityRows({
      ...base, currency: "JPY",
      reservable_amount: "0.10", minimum_unallocated_floor: "0.20",
      active_rule_holds: "12345678901.99", rule_capacity: "0.30",
    });

    assert.deepEqual(rows.map((row) => row.value), ["0.10 JPY", "0.20 JPY", "12345678901.99 JPY", "0.30 JPY"]);
  });

  it("keeps a negative rule capacity negative and flags it", () => {
    const rows = getAccountCapacityRows({ ...base, rule_capacity: "-125.50" });
    const capacity = rows[3];

    assert.equal(capacity.value, "-125.50 EUR");
    assert.equal(capacity.isNegative, true);
    assert.match(capacity.accessibilityLabel, /-125\.50 EUR, below zero/);
    assert.ok(NEGATIVE_CAPACITY_HINT.startsWith("Below zero"));
  });

  it("does not disguise or invent a negative: zero stays zero", () => {
    assert.equal(isNegativeDecimalString("-125.50"), true);
    assert.equal(isNegativeDecimalString("0.00"), false);
    assert.equal(isNegativeDecimalString("-0.00"), false);
    assert.equal(isNegativeDecimalString("600.00"), false);
    assert.equal(getAccountCapacityRows({ ...base, rule_capacity: "0.00" })[3].isNegative, false);
  });

  it("uses each Account's own currency and never combines Accounts", () => {
    const eur = getAccountCapacityRows(base);
    const usd = getAccountCapacityRows({ ...base, currency: "USD" });

    assert.ok(eur.every((row) => row.value.endsWith(" EUR")));
    assert.ok(usd.every((row) => row.value.endsWith(" USD")));
    assert.ok(![...eur, ...usd].some((row) => /total|all accounts|combined/i.test(row.label + row.note)));
  });
});

describe("terminology and accessibility", () => {
  const rows = getAccountCapacityRows({ ...base, rule_capacity: "-1.00" });

  it("every row has an accessible name that carries label, value and meaning", () => {
    for (const row of rows) {
      assert.ok(row.accessibilityLabel.startsWith(`${row.label}: ${row.value}`));
      assert.ok(row.accessibilityLabel.includes(row.note));
    }
  });

  it("explains floor, hold and balance without forbidden wording", () => {
    const byId = Object.fromEntries(rows.map((row) => [row.id, row.note]));

    assert.match(byId.floor, /threshold/);
    assert.match(byId.floor, /does not remove money/);
    assert.match(byId.holds, /not a completed reservation/);
    assert.match(CAPACITY_FOOTNOTE, /does not change this Account's balance/);
  });

  it("contains no forbidden copy (safe to spend, total balance, transfer language, unattended claims)", () => {
    const texts = [
      CAPACITY_SECTION_TITLE, CAPACITY_FOOTNOTE, NEGATIVE_CAPACITY_HINT,
      ...rows.flatMap((row) => [row.label, row.note, row.accessibilityLabel]),
    ];

    for (const text of texts) {
      assert.deepEqual(findForbiddenCopy(text), [], text);
    }
  });
});
