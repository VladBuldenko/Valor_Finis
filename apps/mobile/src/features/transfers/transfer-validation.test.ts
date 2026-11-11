// The create-transfer form rules (VF-MVP-CORE-003): what the form can know before a request is
// sent. The backend stays authoritative for ownership, archived accounts and calendar validity.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { Account } from "../accounts/account.types.ts";
import {
  isTransferDateShape,
  prepareTransferCreatePayload,
  type TransferFormValues,
} from "./transfer-validation.ts";

function account(id: string, currency = "EUR"): Account {
  return { id, currency, name: id, status: "active" } as unknown as Account;
}

const valid: TransferFormValues = {
  sourceAccount: account("src"),
  destinationAccount: account("dst"),
  amount: "300",
  transferDate: "2026-11-11",
  description: "",
};

function errorOf(values: Partial<TransferFormValues>): string | null {
  const result = prepareTransferCreatePayload({ ...valid, ...values });

  return "error" in result ? result.error : null;
}

describe("prepareTransferCreatePayload", () => {
  it("builds the canonical payload: two-decimal amount, trimmed date, null for a blank description", () => {
    const result = prepareTransferCreatePayload({ ...valid, amount: "300", transferDate: " 2026-11-11 " });

    assert.deepEqual(result, {
      payload: {
        source_account_id: "src",
        destination_account_id: "dst",
        amount: "300.00",
        transfer_date: "2026-11-11",
        description: null,
      },
    });
  });

  it("normalizes amounts to one canonical form so a retry is the same logical request", () => {
    const amounts = ["10", "10.0", "10.00", "010", " 10,00 "];

    for (const amount of amounts) {
      const result = prepareTransferCreatePayload({ ...valid, amount });

      assert.ok("payload" in result, amount);
      assert.equal(result.payload.amount, "10.00", amount);
    }
  });

  it("keeps a trimmed description", () => {
    const result = prepareTransferCreatePayload({ ...valid, description: "  rent  " });

    assert.ok("payload" in result);
    assert.equal(result.payload.description, "rent");
  });

  it("requires two distinct accounts of the same currency", () => {
    assert.equal(errorOf({ sourceAccount: undefined }), "Select a source account.");
    assert.equal(errorOf({ destinationAccount: undefined }), "Select a destination account.");
    assert.equal(
      errorOf({ destinationAccount: account("src") }),
      "Source and destination accounts must be different.",
    );
    assert.equal(
      errorOf({ destinationAccount: account("dst", "USD") }),
      "Source and destination accounts must use the same currency.",
    );
  });

  it("rejects missing, zero, negative, over-precise and non-numeric amounts", () => {
    for (const amount of ["", "0", "0.00", "-5", "1.234", "abc", "1e3", "1.2.3"]) {
      assert.notEqual(errorOf({ amount }), null, JSON.stringify(amount));
    }
  });

  it("limits the amount to 10 whole digits (the backend's NUMERIC range)", () => {
    assert.equal(errorOf({ amount: "9999999999.99" }), null);
    assert.match(errorOf({ amount: "10000000000.00" }) ?? "", /at most 10 digits/);
  });

  it("requires the YYYY-MM-DD date shape (calendar validity is the backend's call)", () => {
    for (const transferDate of ["", "2026-1-5", "11/11/2026", "2026-11-11T00:00"]) {
      assert.equal(errorOf({ transferDate }), "Transfer date must use YYYY-MM-DD format.", transferDate);
    }

    assert.equal(isTransferDateShape("2026-02-30"), true);
  });

  it("limits the description to 500 characters", () => {
    assert.equal(errorOf({ description: "x".repeat(500) }), null);
    assert.match(errorOf({ description: "x".repeat(501) }) ?? "", /500 characters or fewer/);
  });

  it("never blocks a transfer for a low source balance (a negative balance is allowed)", () => {
    const poor = { ...account("src"), current_balance: "1.00" } as unknown as Account;

    assert.equal(errorOf({ sourceAccount: poor, amount: "999999.00" }), null);
  });

  it("reports the first problem only", () => {
    assert.equal(errorOf({ sourceAccount: undefined, amount: "abc" }), "Select a source account.");
  });
});
